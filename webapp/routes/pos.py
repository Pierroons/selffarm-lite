"""Route SelfPOS — Caisse marché PWA.

Endpoints :
- GET  /pos                          → liste sessions + bouton "Nouveau marché"
- GET  /pos/produits                 → CRUD catalogue
- POST /pos/produits/new
- POST /pos/produits/{id}/toggle
- POST /pos/produits/{id}/delete
- POST /pos/sessions/new
- GET  /pos/sessions/{id}            → page caisse
- POST /pos/sessions/{id}/vente      → enregistre une vente (form)
- POST /pos/sessions/{id}/cloturer   → clôt + écriture compta
- GET  /pos/sessions/{id}/recap      → récap post-clôture
- POST /api/pos/sessions/{id}/sync   → endpoint JSON pour service worker (batch ventes offline)
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from self_pos.chargement import list_chargement, replace_chargement
from self_pos.collectifs import (
    create_depot,
    deactivate_collectif,
    list_collectifs,
    list_sessions_collectif,
    save_collectif,
)
from self_pos.residus import (
    confirm_stock_revue,
    list_residus,
    list_stock_a_reviewer,
    replace_residus,
    update_residu_status,
)
from self_pos.seed import seed_demo_if_needed, seed_if_empty
from self_pos.services import cloture_session
from self_pos.storage import (
    create_session,
    delete_produit,
    get_session,
    get_session_ouverte,
    list_produits,
    list_sessions,
    list_ventes,
    save_produit,
    save_vente,
    toggle_produit,
)

from webapp import __version__

log = logging.getLogger(__name__)

router = APIRouter(tags=["pos"])

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ============================================================
# Page d'accueil POS
# ============================================================

@router.get("/pos", response_class=HTMLResponse)
async def pos_index(request: Request):
    """Liste sessions historiques + mini-stats + accès rapide session ouverte."""
    # En démo publique, toute arrivée sur SelfPOS montre la vitrine split PC+mobile.
    # Le mode "embed" (iframe de la vitrine) est rendu STICKY via cookie : une fois
    # dans l'iframe, la navigation interne reste en mode caisse et ne reboucle plus
    # vers /pos/demo (sinon le split se ré-affiche dans l'iframe → récursion).
    embed = (
        request.query_params.get("embed") == "1"
        or request.cookies.get("pos_embed") == "1"
    )
    if os.environ.get("SELFFARM_ENV", "prod") == "demo" and not embed:
        return RedirectResponse("/pos/demo", status_code=302)
    seed_if_empty()  # idempotent — première visite seed le catalogue
    from self_agri_book.exploitation import get_exploitation
    from self_pos.stats import stats_globales_pos
    exp = get_exploitation()
    seuil_jours = int(exp.get("stock_revue_jours", 7)) if exp else 7
    response = templates.TemplateResponse(
        "pos/index.html",
        {
            "request": request,
            "version": __version__,
            "sessions": list_sessions(),
            "session_ouverte": get_session_ouverte(),
            "nb_produits": len(list_produits(actifs_only=True)),
            "today": date.today().isoformat(),
            "kpis": stats_globales_pos(),
            "nb_stock_a_reviewer": len(list_stock_a_reviewer(seuil_jours)),
        },
    )
    if request.query_params.get("embed") == "1":
        # Pose le cookie sticky uniquement à l'entrée de l'iframe (caisse PC).
        response.set_cookie("pos_embed", "1", max_age=3600, samesite="lax")
    return response


# ============================================================
# Vitrine split-screen : caisse PC + app mobile côte à côte
# ============================================================

@router.get("/pos/demo", response_class=HTMLResponse)
async def pos_demo_split(request: Request):
    """Vitrine : la caisse PC (/pos) et l'app mobile (/pos/mobile) affichées
    côte à côte en iframes live (même origine). Montre que SelfPOS = les deux."""
    seed_demo_if_needed()
    return templates.TemplateResponse(
        "pos/demo_split.html",
        {"request": request, "version": __version__},
    )


@router.post("/pos/demo/reset")
async def pos_demo_reset():
    """Bac à sable : remet la démo à zéro (mode démo strict, no-op sinon)."""
    from self_pos.seed import reset_demo_activity
    reset_demo_activity()
    return RedirectResponse("/pos/demo", status_code=303)


# ============================================================
# Catalogue produits
# ============================================================

@router.get("/pos/produits", response_class=HTMLResponse)
async def pos_produits(request: Request):
    return templates.TemplateResponse(
        "pos/produits.html",
        {
            "request": request,
            "version": __version__,
            "produits": list_produits(actifs_only=False),
        },
    )


@router.post("/pos/produits/new")
async def pos_produit_new(
    nom: str = Form(...),
    prix_unitaire: float = Form(...),
    unite: str = Form("pièce"),
    categorie: str = Form(""),
    emoji: str = Form(""),
):
    try:
        save_produit({
            "nom": nom.strip(),
            "prix_unitaire": float(prix_unitaire),
            "unite": unite.strip() or "pièce",
            "categorie": categorie.strip() or None,
            "emoji": emoji.strip() or None,
            "actif": 1,
        })
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RedirectResponse(url="/pos/produits", status_code=303)


@router.post("/pos/produits/{produit_id}/toggle")
async def pos_produit_toggle(produit_id: int):
    toggle_produit(produit_id)
    return RedirectResponse(url="/pos/produits", status_code=303)


@router.post("/pos/produits/{produit_id}/delete")
async def pos_produit_delete(produit_id: int):
    delete_produit(produit_id)
    return RedirectResponse(url="/pos/produits", status_code=303)


# ============================================================
# Sessions de marché
# ============================================================

@router.post("/pos/sessions/new")
async def pos_session_new(
    date_marche: str = Form(...),
    lieu: str = Form(...),
    notes: str = Form(""),
):
    """Crée une session puis redirige vers la caisse."""
    # Empêche multi-session ouverte simultanée
    en_cours = get_session_ouverte()
    if en_cours:
        return RedirectResponse(url=f"/pos/sessions/{en_cours['id']}", status_code=303)
    try:
        session = create_session(date_marche.strip(), lieu.strip(), notes.strip() or None)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RedirectResponse(url=f"/pos/sessions/{session['id']}", status_code=303)


@router.get("/pos/sessions/{session_id}", response_class=HTMLResponse)
async def pos_session_caisse(request: Request, session_id: int):
    """Page caisse en cours OU récap si cloturée."""
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session introuvable")
    if session["statut"] == "cloturee":
        return RedirectResponse(url=f"/pos/sessions/{session_id}/recap", status_code=303)
    return templates.TemplateResponse(
        "pos/caisse.html",
        {
            "request": request,
            "version": __version__,
            "session": session,
            "produits": list_produits(actifs_only=True),
            "ventes": list_ventes(session_id),
        },
    )


@router.get("/pos/sessions/{session_id}/recap", response_class=HTMLResponse)
async def pos_session_recap(request: Request, session_id: int):
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session introuvable")
    return templates.TemplateResponse(
        "pos/recap.html",
        {
            "request": request,
            "version": __version__,
            "session": session,
            "ventes": list_ventes(session_id),
            "chargement": list_chargement(session_id),
            "residus": list_residus(session_id=session_id, active_only=False),
        },
    )


@router.post("/pos/sessions/{session_id}/vente")
async def pos_session_vente(
    request: Request,
    session_id: int,
    lignes_json: str = Form(...),
    total_ttc: float = Form(...),
    mode_paiement: str = Form(...),
    details_paiement_json: str = Form(""),
    client_libelle: str = Form(""),
    offline_uuid: str = Form(""),
):
    """Enregistre 1 vente. Appelé depuis la page caisse (form POST + redirect 303)."""
    try:
        lignes = json.loads(lignes_json)
        details = json.loads(details_paiement_json) if details_paiement_json else None
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"JSON invalide : {e}")
    try:
        save_vente(
            session_id=session_id,
            lignes=lignes,
            total_ttc=float(total_ttc),
            mode_paiement=mode_paiement.strip(),
            details_paiement=details,
            client_libelle=client_libelle.strip() or None,
            offline_uuid=offline_uuid.strip() or None,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RedirectResponse(url=f"/pos/sessions/{session_id}", status_code=303)


@router.post("/pos/sessions/{session_id}/cloturer")
async def pos_session_cloturer(session_id: int):
    try:
        result = cloture_session(session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    log.info("Clôture POS session #%s → écriture compta #%s", session_id, result.get("ecriture_id"))
    return RedirectResponse(url=f"/pos/sessions/{session_id}/recap", status_code=303)


# ============================================================
# API JSON — sync offline service worker
# ============================================================

@router.post("/api/pos/sessions/{session_id}/sync")
async def api_pos_sync(session_id: int, request: Request):
    """Reçoit un batch de ventes offline en JSON. Idempotent via offline_uuid."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Body JSON invalide")
    ventes_payload = body.get("ventes", [])
    if not isinstance(ventes_payload, list):
        raise HTTPException(status_code=400, detail="Champ 'ventes' attendu en liste")

    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for v in ventes_payload:
        try:
            saved = save_vente(
                session_id=session_id,
                lignes=v.get("lignes", []),
                total_ttc=float(v.get("total_ttc", 0)),
                mode_paiement=v.get("mode_paiement", "especes"),
                details_paiement=v.get("details_paiement"),
                client_libelle=v.get("client_libelle"),
                offline_uuid=v.get("offline_uuid"),
            )
            results.append({"offline_uuid": v.get("offline_uuid"), "id": saved.get("id"), "ok": True})
        except Exception as e:
            errors.append({"offline_uuid": v.get("offline_uuid"), "error": str(e)})
    return JSONResponse({"results": results, "errors": errors, "count": len(results)})


@router.get("/api/pos/sessions/{session_id}/ventes")
async def api_pos_ventes(session_id: int):
    """Liste des ventes (utile pour réconcilier l'UI offline → online)."""
    if not get_session(session_id):
        raise HTTPException(status_code=404, detail="Session introuvable")
    return JSONResponse({"ventes": list_ventes(session_id)})


# ============================================================
# V0.3 — Export catalogue pour PWA mobile
# ============================================================

@router.get("/api/pos/catalogue-export")
async def api_pos_catalogue_export():
    """Export du catalogue produits actifs au format JSON compatible PWA mobile."""
    from datetime import datetime
    produits = list_produits(actifs_only=True)
    return JSONResponse({
        "format": "selffarm-pos-catalogue",
        "version": "0.3.0",
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "produits": [
            {
                "id": p["id"],
                "nom": p["nom"],
                "prix_unitaire": p["prix_unitaire"],
                "unite": p["unite"],
                "categorie": p.get("categorie"),
                "emoji": p.get("emoji"),
                "actif": bool(p.get("actif", 1)),
                "ordre": p.get("ordre", 0),
            }
            for p in produits
        ],
    })


@router.get("/pos/catalogue-export", response_class=HTMLResponse)
async def pos_catalogue_export_page(request: Request):
    """Page de téléchargement du catalogue pour la PWA mobile."""
    produits = list_produits(actifs_only=True)
    return templates.TemplateResponse(
        "pos/catalogue_export.html",
        {"request": request, "version": __version__, "produits": produits},
    )


# ============================================================
# V0.3 — Import retour marché depuis PWA mobile
# ============================================================

@router.get("/pos/import-marche", response_class=HTMLResponse)
async def pos_import_marche_page(request: Request):
    """Page d'upload du fichier marché exporté depuis la PWA mobile."""
    return templates.TemplateResponse(
        "pos/import_marche.html",
        {"request": request, "version": __version__},
    )


@router.post("/pos/import-marche")
async def pos_import_marche(request: Request):
    """Importe un fichier marché JSON depuis la PWA mobile.

    Crée :
    - 1 session pos_session (cloturee)
    - N pos_chargement
    - N pos_vente (avec dédup offline_uuid)
    - N pos_residu_marche
    - 1 écriture compta agrégée (411/701) via cloture_session
    """
    from datetime import datetime
    form = await request.form()
    upload = form.get("file")
    if not upload or not hasattr(upload, "read"):
        raise HTTPException(status_code=400, detail="Fichier manquant")
    try:
        raw = await upload.read()
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise HTTPException(status_code=400, detail=f"JSON invalide : {e}")

    if data.get("format") != "selffarm-pos-marche":
        raise HTTPException(status_code=400, detail="Format de fichier invalide (selffarm-pos-marche attendu)")

    session_data = data.get("session", {})
    date_marche = session_data.get("date_marche") or datetime.now().date().isoformat()
    lieu = session_data.get("lieu") or "Marché mobile"
    notes_extra = session_data.get("notes") or ""

    # Crée la session
    try:
        session = create_session(date_marche, lieu, notes_extra or None)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    session_id = session["id"]
    summary = {"session_id": session_id, "ventes_creees": 0, "ventes_dedup": 0,
               "chargement_lignes": 0, "residus_lignes": 0,
               "ecriture_compta_id": None, "total_ttc": 0.0}

    # Chargement
    chargement = data.get("chargement", [])
    if chargement and isinstance(chargement, list):
        summary["chargement_lignes"] = replace_chargement(session_id, chargement)

    # Ventes (dédup via offline_uuid)
    ventes = data.get("ventes", [])
    if ventes and isinstance(ventes, list):
        for v in ventes:
            try:
                saved = save_vente(
                    session_id=session_id,
                    lignes=v.get("lignes", []),
                    total_ttc=float(v.get("total_ttc", 0)),
                    mode_paiement=v.get("mode_paiement", "especes"),
                    details_paiement=v.get("details_paiement"),
                    client_libelle=v.get("client_libelle"),
                    offline_uuid=v.get("offline_uuid"),
                )
                # save_vente retourne dict ; pas de flag explicit dédup mais pas grave pour le récap
                summary["ventes_creees"] += 1
                summary["total_ttc"] += float(saved.get("total_ttc", 0))
            except ValueError as e:
                log.warning("Vente ignorée import-marche : %s", e)
                continue

    # Résidus
    residus = data.get("residus", [])
    if residus and isinstance(residus, list):
        summary["residus_lignes"] = replace_residus(session_id, residus)

    # Clôture session + génération écriture compta
    try:
        cloture_result = cloture_session(session_id)
        summary["ecriture_compta_id"] = cloture_result.get("ecriture_id")
        summary["total_ttc"] = cloture_result.get("total_ttc", summary["total_ttc"])
    except Exception:
        log.exception("Clôture après import-marche échouée")

    log.info("Import marché session #%s : %d ventes, %d chargement, %d résidus, écriture #%s",
             session_id, summary["ventes_creees"], summary["chargement_lignes"],
             summary["residus_lignes"], summary["ecriture_compta_id"])

    # Affiche page récap
    return RedirectResponse(url=f"/pos/sessions/{session_id}/recap?imported=1", status_code=303)


# ============================================================
# V0.3 — Stock résiduel : revue hebdo
# ============================================================

@router.get("/pos/stock-revue", response_class=HTMLResponse)
async def pos_stock_revue(request: Request):
    """Page de revue du stock résiduel des marchés précédents."""
    seed_demo_if_needed()
    from self_agri_book.exploitation import get_exploitation
    exp = get_exploitation()
    seuil_jours = int(exp.get("stock_revue_jours", 7)) if exp else 7
    all_stock = list_residus(status="stock", active_only=True)
    a_reviewer = list_stock_a_reviewer(seuil_jours)
    return templates.TemplateResponse(
        "pos/stock_revue.html",
        {
            "request": request,
            "version": __version__,
            "all_stock": all_stock,
            "a_reviewer": a_reviewer,
            "seuil_jours": seuil_jours,
        },
    )


@router.post("/pos/residus/{residu_id}/confirm-stock")
async def pos_residu_confirm_stock(residu_id: int):
    confirm_stock_revue(residu_id)
    return RedirectResponse(url="/pos/stock-revue", status_code=303)


@router.post("/pos/residus/{residu_id}/reclasser")
async def pos_residu_reclasser(
    residu_id: int,
    new_status: str = Form(...),
    destination: str = Form(""),
    notes: str = Form(""),
):
    try:
        update_residu_status(
            residu_id,
            new_status.strip(),
            destination.strip() or None,
            notes.strip() or None,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RedirectResponse(url="/pos/stock-revue", status_code=303)


# ============================================================
# V0.3 — Points de vente collectifs (magasins producteurs)
# ============================================================

@router.get("/pos/collectifs", response_class=HTMLResponse)
async def pos_collectifs_index(request: Request):
    """Liste des magasins points de vente collectifs."""
    collectifs = list_collectifs(active_only=False)
    sessions = list_sessions_collectif(limit=20)
    return templates.TemplateResponse(
        "pos/collectifs/index.html",
        {
            "request": request,
            "version": __version__,
            "collectifs": collectifs,
            "sessions": sessions,
        },
    )


@router.post("/pos/collectifs/new")
async def pos_collectif_new(
    nom: str = Form(...),
    adresse: str = Form(""),
    convention: str = Form("depot_vente"),
    commission_pct: str = Form(""),
    jour_recap: str = Form(""),
    contact: str = Form(""),
    notes: str = Form(""),
):
    try:
        save_collectif({
            "nom": nom.strip(),
            "adresse": adresse.strip() or None,
            "convention": convention,
            "commission_pct": float(commission_pct) if commission_pct.strip() else None,
            "jour_recap": int(jour_recap) if jour_recap.strip() else None,
            "contact": contact.strip() or None,
            "notes": notes.strip() or None,
            "active": True,
        })
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RedirectResponse(url="/pos/collectifs", status_code=303)


@router.post("/pos/collectifs/{collectif_id}/deactivate")
async def pos_collectif_deactivate(collectif_id: int):
    deactivate_collectif(collectif_id)
    return RedirectResponse(url="/pos/collectifs", status_code=303)


@router.post("/pos/collectifs/{collectif_id}/depot")
async def pos_collectif_depot_new(
    collectif_id: int,
    date_depot: str = Form(...),
    notes: str = Form(""),
):
    try:
        session = create_depot(collectif_id, date_depot, notes.strip() or None)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RedirectResponse(url=f"/pos/sessions/{session['id']}/chargement", status_code=303)


@router.get("/pos/sessions/{session_id}/chargement", response_class=HTMLResponse)
async def pos_session_chargement(request: Request, session_id: int):
    """Page saisie du chargement (dépôt collectif ou prepa marché)."""
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session introuvable")
    chargement = list_chargement(session_id)
    produits = list_produits(actifs_only=True)
    return templates.TemplateResponse(
        "pos/chargement.html",
        {
            "request": request,
            "version": __version__,
            "session": session,
            "chargement": chargement,
            "produits": produits,
        },
    )


@router.get("/pos/mobile", response_class=HTMLResponse)
async def pos_mobile(request: Request):
    """PWA mobile autonome — single-page, IndexedDB, offline-first."""
    return templates.TemplateResponse(
        "pos/mobile.html",
        {"request": request, "version": __version__},
    )


@router.get("/pos/stats", response_class=HTMLResponse)
async def pos_stats(request: Request):
    """Statistiques produits : top vendus, CA, évolution, taux invendu."""
    seed_demo_if_needed()
    from self_pos.stats import get_all_stats
    return templates.TemplateResponse(
        "pos/stats.html",
        {"request": request, "version": __version__, "stats": get_all_stats()},
    )


def _classify_interface(iface: str) -> dict:
    """Classe une interface réseau par type + stabilité.

    Stabilité décroissante : Ethernet câblé > USB tethering > WiFi.
    """
    if iface.startswith(("eno", "enp", "ens", "eth")):
        return {"type": "ethernet", "label": "🔌 Filaire (Ethernet)", "stable": True, "priority": 0}
    if iface.startswith(("enx", "usb")):
        return {"type": "usb", "label": "🔌 Filaire (USB / tél)", "stable": True, "priority": 1}
    if iface.startswith(("wl", "wlan", "wlo", "wlp", "wifi")):
        return {"type": "wifi", "label": "📶 WiFi (peut décrocher)", "stable": False, "priority": 2}
    return {"type": "autre", "label": "🔗 Réseau", "stable": False, "priority": 3}


def _detect_lan_ips() -> list[dict]:
    """Détecte les IPs LAN du PC + classe par type/stabilité.

    Priorise Ethernet > USB tethering > WiFi. Skip libvirt/docker/loopback.
    Couvre tous les cas : box maison, PC hotspot, tel hotspot WiFi, USB tethering.
    """
    import socket

    import psutil

    SKIP_PREFIX = ("lo", "virbr", "docker", "br-", "veth", "tun", "tap")
    out: list[dict] = []
    try:
        addrs = psutil.net_if_addrs()
        for iface, snics in addrs.items():
            if iface.startswith(SKIP_PREFIX):
                continue
            for snic in snics:
                if snic.family != socket.AF_INET:
                    continue
                ip = snic.address
                if ip.startswith("127."):
                    continue
                cls = _classify_interface(iface)
                out.append({
                    "interface": iface,
                    "ip": ip,
                    "type": cls["type"],
                    "label": cls["label"],
                    "stable": cls["stable"],
                    "priority": cls["priority"],
                })
    except Exception:
        log.exception("Détection IPs LAN échouée")
    out.sort(key=lambda x: (x["priority"], x["interface"]))
    return out


@router.get("/pos/mode-marche", response_class=HTMLResponse)
async def pos_mode_marche(request: Request):
    """Page d'aide hotspot : détecte IP PC, génère QR pour scan tel."""
    return templates.TemplateResponse(
        "pos/mode_marche.html",
        {"request": request, "version": __version__},
    )


@router.get("/api/pos/health")
async def api_pos_health():
    """Endpoint de ping pour la PWA mobile (CORS permissif).

    Retourne un JSON simple : {ok, app, version, pos_ready}.
    Utilisé par la PWA pour afficher le point vert/rouge.
    """
    return JSONResponse({
        "ok": True,
        "app": "selffarm-lite",
        "version": __version__,
        "pos_ready": True,
    }, headers={"Access-Control-Allow-Origin": "*"})


@router.get("/api/pos/hotspot-status")
async def api_pos_hotspot_status():
    """Détecte les IPs LAN du PC, classées par stabilité. Recommande la plus stable."""
    ips = _detect_lan_ips()
    # ips déjà trié : ethernet > usb > wifi. La 1ʳᵉ stable = recommandée.
    recommended = next((i for i in ips if i["stable"]), ips[0] if ips else None)
    return JSONResponse({
        "ips": [
            {**i, "pwa_url": f"http://{i['ip']}:8003/pos/mobile"}
            for i in ips
        ],
        "recommended_ip": recommended["ip"] if recommended else None,
        "any_lan": len(ips) > 0,
    })


@router.get("/api/pos/qr-code")
async def api_pos_qr_code(url: str | None = None):
    """Génère un QR SVG de l'URL fournie (ou IP courante par défaut)."""
    from io import BytesIO

    import segno
    if not url:
        ips = _detect_lan_ips()
        if not ips:
            raise HTTPException(status_code=404, detail="Aucune IP LAN détectée")
        url = f"http://{ips[0]['ip']}:8003/pos/mobile"
    qr = segno.make(url, error="m")
    buf = BytesIO()
    qr.save(buf, kind="svg", scale=8, dark="#0a0f0d", light="#ffffff", border=2)
    return HTMLResponse(buf.getvalue().decode("utf-8"), media_type="image/svg+xml")


# ── Coffre de sauvegarde mobile : appairage (Lot C, Partie D) ────────────────
@router.post("/api/pos/pair")
async def api_pos_pair(request: Request):
    """Appairage du coffre : le tel présente le jeton du QR, reçoit la clé de coffre."""
    from self_backup.vault import vault_key_b64
    from self_pos.devices import consume_pair_token, register_device
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not consume_pair_token(body.get("token", "")):
        raise HTTPException(status_code=403, detail="Jeton d'appairage invalide ou expiré")
    device_id = register_device(label=body.get("label", ""))
    return JSONResponse({
        "device_id": device_id,
        "vault_key": vault_key_b64(),
        "server_url": str(request.base_url).rstrip("/"),
    }, headers={"Access-Control-Allow-Origin": "*"})


@router.get("/pos/coffre/appairer", response_class=HTMLResponse)
async def pos_coffre_appairer(request: Request):
    """Page PC : génère un jeton + QR pour appairer le coffre de sauvegarde d'un tel."""
    from self_pos.devices import load_devices, new_pair_token
    token = new_pair_token()
    ips = _detect_lan_ips()
    ip = ips[0]["ip"] if ips else "127.0.0.1"
    port = request.url.port or 80
    pair_url = f"http://{ip}:{port}/pos/mobile?pair={token}"
    return templates.TemplateResponse(
        "pos/coffre_appairer.html",
        {"request": request, "version": __version__,
         "pair_url": pair_url, "devices": load_devices()},
    )


# ── Coffre mobile : dépôt du backup chiffré (Lot D, Partie D) ────────────────
_POS_BACKUP_CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Expose-Headers": "X-Backup-Name, X-Backup-Sha",
}


@router.get("/api/pos/backup/manifest")
async def api_pos_backup_manifest():
    """Empreinte du backup courant — le tel compare pour savoir s'il doit re-télécharger."""
    from self_backup import _db_path, _file_sha256
    db = _db_path()
    if not db.exists():
        return JSONResponse({"available": False}, headers=_POS_BACKUP_CORS)
    return JSONResponse({
        "available": True,
        "sha256": _file_sha256(db),
        "db_size": db.stat().st_size,
        "generated_at": datetime.now(UTC).isoformat(),
    }, headers=_POS_BACKUP_CORS)


@router.get("/api/pos/backup/download")
async def api_pos_backup_download():
    """Sert le backup courant CHIFFRÉ (clé de coffre) à déposer sur le tel."""
    from self_backup import _db_path, _file_sha256, make_backup
    from self_backup.vault import encrypt
    db = _db_path()
    if not db.exists():
        raise HTTPException(status_code=404, detail="Aucune base à sauvegarder")
    sha = _file_sha256(db)
    zip_bytes, fn = make_backup(version=__version__)
    blob = encrypt(zip_bytes)
    name = fn + ".vault"
    return Response(content=blob, media_type="application/octet-stream", headers={
        **_POS_BACKUP_CORS, "X-Backup-Name": name, "X-Backup-Sha": sha,
        "Content-Disposition": f'attachment; filename="{name}"',
    })


@router.post("/api/pos/backup/restore-push")
async def api_pos_backup_restore_push(request: Request):
    """Le tel renvoie un backup chiffré (vault) → le PC déchiffre + restaure.
    Pour un PC neuf, le tel fournit aussi sa clé de coffre via X-Vault-Key."""
    from self_backup import restore_from_bytes
    from self_backup.vault import decrypt, has_vault_key, import_vault_key
    from self_pos.devices import touch_device
    device_id = request.headers.get("X-Device-Id", "")
    if device_id:
        touch_device(device_id)
    blob = await request.body()
    if not blob:
        raise HTTPException(status_code=400, detail="Corps vide")
    pushed_key = request.headers.get("X-Vault-Key", "")
    if pushed_key and not has_vault_key():
        try:
            import_vault_key(pushed_key)
        except Exception:  # best-effort, mais tracé
            log.warning("Import de la clé de coffre poussée par le mobile échoué",
                        exc_info=True)
    try:
        zip_bytes = decrypt(blob)
    except Exception:
        if pushed_key:
            try:
                import_vault_key(pushed_key)
                zip_bytes = decrypt(blob)
            except Exception:
                raise HTTPException(status_code=400, detail="Déchiffrement impossible (clé de coffre invalide)")
        else:
            raise HTTPException(status_code=400, detail="Déchiffrement impossible (clé de coffre absente)")
    confirm = request.headers.get("X-Confirm-Rollback", "") == "1"
    try:
        result = restore_from_bytes(zip_bytes, confirm_rollback=confirm)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if result.get("needs_confirmation"):
        return JSONResponse({"restored": False, "needs_confirmation": True,
                             "gen_base": result.get("gen_base"), "gen_backup": result.get("gen_backup")},
                            status_code=409, headers=_POS_BACKUP_CORS)
    return JSONResponse({"restored": True,
                         "nb_factures": result.get("nb_factures_restaurees", 0)},
                        headers=_POS_BACKUP_CORS)


@router.post("/pos/sessions/{session_id}/chargement")
async def pos_session_chargement_save(request: Request, session_id: int):
    """Sauvegarde le chargement d'une session (replace complet)."""
    form = await request.form()
    # form contient des lignes formattées produit_X_charged, produit_X_qte
    lignes: list[dict[str, Any]] = []
    for key in form:
        if not key.startswith("produit_") or not key.endswith("_charged"):
            continue
        produit_id = key.replace("produit_", "").replace("_charged", "")
        try:
            produit_id_int = int(produit_id)
        except ValueError:
            continue
        produit = next((p for p in list_produits(actifs_only=True) if p["id"] == produit_id_int), None)
        if not produit:
            continue
        qte_raw = form.get(f"produit_{produit_id}_qte", "").strip()
        try:
            qte = float(qte_raw) if qte_raw else None
        except ValueError:
            qte = None
        lignes.append({
            "produit_id": produit_id_int,
            "produit_nom": produit["nom"],
            "unite": produit.get("unite", "pièce"),
            "quantite_chargee": qte,
        })
    replace_chargement(session_id, lignes)
    return RedirectResponse(url=f"/pos/sessions/{session_id}", status_code=303)
