"""Route /elevage — atelier volailles : ponte, cheptel, lots d'œufs, aliment.

Quatre écrans, quatre rythmes d'usage — c'est ce qui gouverne leur ergonomie :

- **`/elevage`** — le tableau de bord et la **saisie de la ponte**. C'est l'écran
  du quotidien, utilisé tous les jours en sortant du poulailler, souvent les
  mains sales et en plein soleil. Un champ, un bouton, date pré-remplie. Si
  c'est pénible, il sera abandonné en une semaine, et tout le module avec.
- **`/elevage/bandes`** — la gestion du cheptel : création de bande, mortalités,
  réformes, ajouts. Écran occasionnel, on peut y être plus verbeux.
- **`/elevage/lots`** — constitution des lots d'œufs et suivi du délai
  réglementaire de 21 jours. Rythme hebdomadaire, au moment de préparer une
  vente.
- **`/elevage/aliment`** — livraisons et coût alimentaire. Saisie à la
  livraison, bon de livraison en main.

Le moteur vient de `self_elevage.elevage` : rien n'est réimplémenté ici. En
particulier le **taux de ponte se calcule sur l'effectif vivant**, jamais sur
l'effectif initial — c'est le module qui s'en charge.
"""

from __future__ import annotations

import logging
from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from self_agri_book.exploitation import get_exploitation
from self_elevage.elevage import (
    DELAI_VENTE_DIRECTE_JOURS,
    VALID_ESPECES,
    VALID_MODES_ELEVAGE,
    VALID_STATUTS_LOT,
    VALID_TYPES_ALIMENT,
    VALID_TYPES_MOUVEMENT,
    add_aliment,
    add_mouvement,
    creer_lot,
    effectif_vivant,
    get_bande,
    get_lot,
    list_aliment,
    list_bandes,
    list_lots,
    list_mouvements,
    list_ponte,
    lots_a_ecouler,
    oeufs_periode,
    registre_elevage,
    save_bande,
    save_ponte,
    stats_aliment,
    stats_elevage,
    taux_ponte,
    update_lot_statut,
)

from webapp import __version__

log = logging.getLogger(__name__)

router = APIRouter(prefix="/elevage", tags=["elevage"])
templates = Jinja2Templates(directory="webapp/templates")

# Libellés d'affichage — le stockage reste sur les clés techniques.
LABELS_ESPECE = {
    "poule_pondeuse": "Poules pondeuses",
    "poulet_chair": "Poulets de chair",
    "canard": "Canards",
    "caille": "Cailles",
    "autre": "Autre",
}
LABELS_MODE = {
    "bio": "Biologique",
    "plein_air": "Plein air",
    "sol": "Au sol",
    "cage": "En cage",
}
LABELS_MOUVEMENT = {
    "mortalite": "Mortalité",
    "reforme": "Réforme",
    "ajout": "Ajout",
}
LABELS_ALIMENT = {
    "ponte": "Aliment ponte",
    "demarrage": "Démarrage",
    "croissance": "Croissance",
    "complement": "Complément",
    "autre": "Autre",
}


def _redirect(path: str, ok: str | None = None, erreur: str | None = None):
    """Redirection 303 avec message — toute erreur revient sur l'écran d'origine."""
    if ok:
        path = f"{path}?ok={quote(ok)}"
    elif erreur:
        path = f"{path}?erreur={quote(erreur)}"
    return RedirectResponse(url=path, status_code=303)


# ============================================================
# TABLEAU DE BORD + SAISIE PONTE
# ============================================================

@router.get("", response_class=HTMLResponse)
async def elevage_index(request: Request, ok: str | None = None,
                        erreur: str | None = None):
    """Écran du quotidien : bandeau de chiffres, saisie ponte, alertes lots."""
    bandes = list_bandes(actives_only=True)

    # Une ligne par bande, enrichie de son effectif vivant et de son taux 7 j.
    lignes = []
    for b in bandes:
        bid = int(b["id"])
        t = taux_ponte(bid, jours=7)
        dernier = list_ponte(bande_id=bid)[:1]
        lignes.append({
            **b,
            "espece_label": LABELS_ESPECE.get(b["espece"], b["espece"]),
            "mode_label": LABELS_MODE.get(b["mode_elevage"], b["mode_elevage"]),
            "effectif_vivant": t["effectif_vivant"],
            "taux_ponte_pct": t["taux_ponte_pct"],
            "moyenne_jour": t["moyenne_jour"],
            "jours_releves": t["jours_releves"],
            "total_vendables": t["total_vendables"],
            "taux_vendable_pct": t["taux_vendable_pct"],
            "derniere_saisie": dernier[0]["date_ponte"] if dernier else None,
            "saisi_aujourdhui": bool(dernier) and dernier[0]["date_ponte"] == date.today().isoformat(),
        })

    return templates.TemplateResponse(
        "elevage/index.html",
        {
            "request": request,
            "version": __version__,
            "stats": stats_elevage(),
            "bandes": lignes,
            "alertes": lots_a_ecouler(),
            "today": date.today().isoformat(),
            "ok": ok,
            "erreur": erreur,
        },
    )


@router.post("/ponte")
async def elevage_ponte_post(request: Request):
    """Enregistre le relevé du jour. Re-saisir la même date **corrige** la valeur."""
    form = await request.form()

    try:
        bande_id = int(form.get("bande_id") or 0)
    except (TypeError, ValueError):
        return _redirect("/elevage", erreur="Bande invalide.")

    bande = get_bande(bande_id)
    if not bande:
        return _redirect("/elevage", erreur="Bande introuvable.")

    raw = (form.get("nb_oeufs") or "").strip()
    if not raw:
        return _redirect("/elevage", erreur="Indique le nombre d'œufs ramassés.")
    try:
        nb_oeufs = int(raw)
    except ValueError:
        return _redirect("/elevage", erreur="Nombre d'œufs invalide — chiffres uniquement.")

    try:
        nb_casses = int((form.get("nb_casses") or "0").strip() or 0)
    except ValueError:
        return _redirect("/elevage", erreur="Nombre de casses invalide.")

    try:
        nb_declasses = int((form.get("nb_declasses") or "0").strip() or 0)
    except ValueError:
        return _redirect("/elevage", erreur="Nombre de déclassés invalide.")

    date_ponte = (form.get("date_ponte") or "").strip() or date.today().isoformat()
    try:
        date.fromisoformat(date_ponte)
    except ValueError:
        return _redirect("/elevage", erreur="Date invalide — format attendu AAAA-MM-JJ.")

    try:
        save_ponte({
            "bande_id": bande_id, "date_ponte": date_ponte,
            "nb_oeufs": nb_oeufs, "nb_casses": nb_casses,
            "nb_declasses": nb_declasses,
            "notes": (form.get("notes") or "").strip() or None,
        })
    except ValueError as exc:
        return _redirect("/elevage", erreur=str(exc))

    # Une ponte supérieure à l'effectif n'est pas bloquée : elle peut être réelle
    # (ramassage groupé sur deux jours, oubli de la veille). On avertit, c'est tout.
    vivant = effectif_vivant(bande_id)
    if vivant and nb_oeufs > vivant:
        return _redirect(
            "/elevage",
            ok=f"{nb_oeufs} œufs enregistrés — plus que l'effectif ({vivant}). "
               "Vérifie s'il s'agit d'un ramassage groupé.",
        )
    return _redirect("/elevage", ok=f"{nb_oeufs} œufs enregistrés pour {bande['nom']}.")


# ============================================================
# BANDES ET MOUVEMENTS
# ============================================================

@router.get("/bandes", response_class=HTMLResponse)
async def elevage_bandes(request: Request, ok: str | None = None,
                         erreur: str | None = None, edit: int | None = None):
    """Cheptel : création de bande, effectifs, mortalités et réformes."""
    bandes = []
    for b in list_bandes(actives_only=False):
        bid = int(b["id"])
        vivant = effectif_vivant(bid)
        initial = int(b["effectif_initial"] or 0)
        bandes.append({
            **b,
            "espece_label": LABELS_ESPECE.get(b["espece"], b["espece"]),
            "mode_label": LABELS_MODE.get(b["mode_elevage"], b["mode_elevage"]),
            "effectif_vivant": vivant,
            "pertes": max(0, initial - vivant),
            "taux_perte_pct": round((initial - vivant) / initial * 100, 1) if initial else None,
        })

    mouvements = [
        {**m, "type_label": LABELS_MOUVEMENT.get(m["type_mouvement"], m["type_mouvement"])}
        for m in list_mouvements()[:40]
    ]

    return templates.TemplateResponse(
        "elevage/bandes.html",
        {
            "request": request,
            "version": __version__,
            "bandes": bandes,
            "mouvements": mouvements,
            "bande_edit": get_bande(edit) if edit else None,
            "especes": [(k, LABELS_ESPECE[k]) for k in VALID_ESPECES],
            "modes": [(k, LABELS_MODE[k]) for k in VALID_MODES_ELEVAGE],
            "types_mouvement": [(k, LABELS_MOUVEMENT[k]) for k in VALID_TYPES_MOUVEMENT],
            "today": date.today().isoformat(),
            "ok": ok,
            "erreur": erreur,
        },
    )


@router.post("/bandes")
async def elevage_bandes_post(request: Request):
    """Crée ou met à jour une bande."""
    form = await request.form()
    data = {
        "nom": (form.get("nom") or "").strip(),
        "espece": (form.get("espece") or "poule_pondeuse").strip(),
        "race": (form.get("race") or "").strip() or None,
        "effectif_initial": (form.get("effectif_initial") or "").strip(),
        "date_mise_en_place": (form.get("date_mise_en_place") or "").strip()
                              or date.today().isoformat(),
        "mode_elevage": (form.get("mode_elevage") or "plein_air").strip(),
        "statut": (form.get("statut") or "active").strip(),
        "notes": (form.get("notes") or "").strip() or None,
    }
    if form.get("id"):
        try:
            data["id"] = int(form["id"])
        except (TypeError, ValueError):
            return _redirect("/elevage/bandes", erreur="Identifiant de bande invalide.")

    try:
        date.fromisoformat(data["date_mise_en_place"])
    except ValueError:
        return _redirect("/elevage/bandes", erreur="Date de mise en place invalide.")

    try:
        bande = save_bande(data)
    except ValueError as exc:
        return _redirect("/elevage/bandes", erreur=str(exc))

    verbe = "mise à jour" if form.get("id") else "créée"
    return _redirect("/elevage/bandes", ok=f"Bande « {bande['nom']} » {verbe}.")


# ============================================================
# LOTS D'ŒUFS
# ============================================================

LABELS_STATUT_LOT = {"disponible": "Disponible", "vendu": "Vendu", "retire": "Retiré"}


@router.get("/lots", response_class=HTMLResponse)
async def elevage_lots(request: Request, ok: str | None = None, erreur: str | None = None,
                       bande_id: int | None = None, debut: str | None = None,
                       fin: str | None = None):
    """Lots d'œufs et suivi du délai réglementaire de 21 jours.

    Les paramètres `bande_id`, `debut` et `fin` servent au bouton « proposer
    depuis les relevés » : l'écran recalcule côté serveur ce qu'a donné la
    période et pré-remplit la quantité. Pas de JavaScript, même logique que le
    reste de l'application.
    """
    bandes = list_bandes(actives_only=True)

    suggestion = None
    if bande_id and debut and fin:
        try:
            date.fromisoformat(debut), date.fromisoformat(fin)
            if get_bande(bande_id):
                suggestion = {"bande_id": bande_id, "debut": debut, "fin": fin,
                              **oeufs_periode(bande_id, debut, fin)}
        except ValueError:
            suggestion = None

    lots = [
        {**l, "statut_label": LABELS_STATUT_LOT.get(l["statut"], l["statut"])}
        for l in list_lots()
    ]

    return templates.TemplateResponse(
        "elevage/lots.html",
        {
            "request": request,
            "version": __version__,
            "bandes": bandes,
            "lots": lots,
            "alertes": lots_a_ecouler(),
            "disponibles": [l for l in lots if l["statut"] == "disponible"],
            "suggestion": suggestion,
            "sessions_pos": _sessions_pos_ouvertes(),
            "produits_pos": _produits_pos(),
            "delai_jours": DELAI_VENTE_DIRECTE_JOURS,
            "today": date.today().isoformat(),
            "ok": ok,
            "erreur": erreur,
        },
    )


@router.post("/lots")
async def elevage_lots_post(request: Request):
    """Constitue un lot sur une période de ponte."""
    form = await request.form()

    try:
        bande_id = int(form.get("bande_id") or 0)
    except (TypeError, ValueError):
        return _redirect("/elevage/lots", erreur="Bande invalide.")

    debut = (form.get("date_ponte_debut") or "").strip()
    fin = (form.get("date_ponte_fin") or "").strip()

    # Bouton « proposer » : on repasse par le GET avec la période, qui calcule.
    if form.get("action") == "proposer":
        if not (debut and fin):
            return _redirect("/elevage/lots", erreur="Indique la période de ponte à analyser.")
        return RedirectResponse(
            url=f"/elevage/lots?bande_id={bande_id}&debut={quote(debut)}&fin={quote(fin)}",
            status_code=303,
        )

    raw = (form.get("nb_oeufs") or "").strip()
    if not raw:
        return _redirect("/elevage/lots", erreur="Indique le nombre d'œufs du lot.")
    try:
        nb_oeufs = int(raw)
    except ValueError:
        return _redirect("/elevage/lots", erreur="Nombre d'œufs invalide — chiffres uniquement.")

    try:
        lot = creer_lot({
            "bande_id": bande_id,
            "date_ponte_debut": debut, "date_ponte_fin": fin,
            "nb_oeufs": nb_oeufs,
            "destination": (form.get("destination") or "").strip() or None,
            "notes": (form.get("notes") or "").strip() or None,
        })
    except ValueError as exc:
        return _redirect("/elevage/lots", erreur=str(exc))

    return _redirect(
        "/elevage/lots",
        ok=f"Lot de {lot['nb_oeufs']} œufs créé — à écouler avant le {lot['date_limite']}.",
    )


def _sessions_pos_ouvertes() -> list[dict]:
    """Sessions de vente ouvertes — marché comme point de vente collectif.

    Import local et défensif : le module POS peut être désactivé, ou absent
    d'une install allégée. L'élevage doit continuer de fonctionner sans lui.
    """
    try:
        from self_pos.storage import list_sessions
    except ImportError:
        return []
    try:
        return [s for s in list_sessions(limit=30) if s.get("statut") == "ouverte"]
    except Exception:
        log.warning("Sessions POS illisibles — envoi en vente désactivé", exc_info=True)
        return []


def _produits_pos() -> list[dict]:
    try:
        from self_pos.storage import list_produits
    except ImportError:
        return []
    try:
        return list_produits(actifs_only=True)
    except Exception:
        return []


def _quantite_pour_unite(nb_oeufs: int, unite: str) -> float:
    """Convertit un nombre d'œufs dans l'unité de vente du produit.

    Les œufs se comptent à l'unité côté élevage mais se vendent souvent à la
    douzaine ou à la demi-douzaine. Sans cette conversion, on chargerait 181
    douzaines au lieu de 15.
    """
    u = (unite or "").lower()
    if "douzaine" in u and "demi" not in u:
        return round(nb_oeufs / 12, 2)
    if "demi-douzaine" in u or "6" == u:
        return round(nb_oeufs / 6, 2)
    return float(nb_oeufs)


@router.post("/lots/{lot_id}/vendre")
async def elevage_lot_vendre(request: Request, lot_id: int):
    """Envoie un lot vers une session de vente — marché ou point de vente collectif.

    L'orchestration vit ici, pas dans `self_elevage` : la verticale élevage
    n'a pas à connaître la caisse. Le couplage reste à la couche route.
    """
    form = await request.form()

    lot = get_lot(lot_id)
    if not lot:
        return _redirect("/elevage/lots", erreur="Lot introuvable.")
    if lot["statut"] != "disponible":
        return _redirect("/elevage/lots", erreur="Ce lot n'est plus disponible.")

    try:
        session_id = int(form.get("session_id") or 0)
        produit_id = int(form.get("produit_id") or 0)
    except (TypeError, ValueError):
        return _redirect("/elevage/lots", erreur="Session ou produit invalide.")

    session = next((s for s in _sessions_pos_ouvertes() if int(s["id"]) == session_id), None)
    if not session:
        return _redirect("/elevage/lots", erreur="Session de vente introuvable ou déjà clôturée.")

    produit = next((p for p in _produits_pos() if int(p["id"]) == produit_id), None)
    if not produit:
        return _redirect("/elevage/lots", erreur="Produit introuvable au catalogue de la caisse.")

    quantite = _quantite_pour_unite(int(lot["nb_oeufs"] or 0), produit.get("unite", ""))

    try:
        from self_pos.chargement import add_chargement_line
        add_chargement_line(
            session_id=session_id,
            produit_id=produit_id,
            produit_nom=produit["nom"],
            unite=produit.get("unite") or "pièce",
            quantite_chargee=quantite,
        )
    except (ImportError, ValueError) as exc:
        return _redirect("/elevage/lots", erreur=f"Chargement impossible : {exc}")

    try:
        update_lot_statut(lot_id, "vendu", destination=session.get("lieu"))
    except ValueError as exc:
        return _redirect("/elevage/lots", erreur=str(exc))

    unite = produit.get("unite") or "pièce"
    qte = f"{quantite:g}".replace(".", ",")      # séparateur décimal français
    return _redirect(
        "/elevage/lots",
        ok=f"{qte} {unite} de « {produit['nom']} » chargées pour "
           f"{session.get('lieu') or 'la vente'} — lot marqué vendu.",
    )


@router.post("/lots/{lot_id}/statut")
async def elevage_lot_statut(request: Request, lot_id: int):
    """Marque un lot vendu ou retiré. Un lot n'est jamais supprimé du registre."""
    form = await request.form()
    statut = (form.get("statut") or "").strip()
    if statut not in VALID_STATUTS_LOT:
        return _redirect("/elevage/lots", erreur="Statut inconnu.")

    try:
        lot = update_lot_statut(
            lot_id, statut,
            destination=(form.get("destination") or "").strip() or None,
        )
    except ValueError as exc:
        return _redirect("/elevage/lots", erreur=str(exc))

    label = LABELS_STATUT_LOT.get(statut, statut).lower()
    dest = f" ({lot['destination']})" if lot.get("destination") else ""
    return _redirect("/elevage/lots", ok=f"Lot de {lot['nb_oeufs']} œufs marqué {label}{dest}.")


# ============================================================
# REGISTRE D'ÉLEVAGE
# ============================================================

@router.get("/registre", response_class=HTMLResponse)
async def elevage_registre(request: Request, bande_id: int | None = None,
                           debut: str | None = None, fin: str | None = None,
                           erreur: str | None = None):
    """Registre d'élevage imprimable — arrêté du 5 juin 2000, conservation 5 ans.

    Par défaut : première bande active, année civile en cours. C'est le cadrage
    qu'on présente à un contrôle, et celui qu'on archive en fin d'exercice.
    """
    bandes = list_bandes(actives_only=False)
    if not bandes:
        return templates.TemplateResponse(
            "elevage/registre.html",
            {"request": request, "version": __version__, "bandes": [],
             "registre": None, "erreur": erreur,
             "debut": debut, "fin": fin, "today": date.today().isoformat()},
        )

    if bande_id is None or not get_bande(bande_id):
        bande_id = int(bandes[0]["id"])

    annee = date.today().year
    debut = debut or f"{annee}-01-01"
    fin = fin or f"{annee}-12-31"
    try:
        date.fromisoformat(debut)
        date.fromisoformat(fin)
    except ValueError:
        return _redirect("/elevage/registre", erreur="Dates invalides — format attendu AAAA-MM-JJ.")

    registre = registre_elevage(bande_id, debut=debut, fin=fin)
    registre["bande"] = {
        **registre["bande"],
        "espece_label": LABELS_ESPECE.get(registre["bande"]["espece"], registre["bande"]["espece"]),
        "mode_label": LABELS_MODE.get(registre["bande"]["mode_elevage"],
                                      registre["bande"]["mode_elevage"]),
    }
    registre["mouvements"] = [
        {**m, "type_label": LABELS_MOUVEMENT.get(m["type_mouvement"], m["type_mouvement"])}
        for m in registre["mouvements"]
    ]

    exploitation = get_exploitation() or {}

    return templates.TemplateResponse(
        "elevage/registre.html",
        {
            "request": request,
            "version": __version__,
            "bandes": bandes,
            "bande_id": bande_id,
            "registre": registre,
            "exploitation": exploitation,
            "debut": debut,
            "fin": fin,
            "edite_le": date.today().isoformat(),
            "today": date.today().isoformat(),
            "erreur": erreur,
        },
    )


# ============================================================
# ALIMENT
# ============================================================

@router.get("/aliment", response_class=HTMLResponse)
async def elevage_aliment(request: Request, ok: str | None = None,
                          erreur: str | None = None):
    """Livraisons d'aliment et coût alimentaire — le poste de charge principal.

    Écran occasionnel : on saisit à la livraison, bon de livraison en main.
    Volontairement séparé de la ponte, qui est quotidienne.
    """
    bandes = list_bandes(actives_only=True)

    ateliers = []
    for b in bandes:
        bid = int(b["id"])
        ateliers.append({
            **b,
            "effectif_vivant": effectif_vivant(bid),
            "stats": stats_aliment(bid),
        })

    livraisons = [
        {**l, "type_label": LABELS_ALIMENT.get(l["type_aliment"], l["type_aliment"])}
        for l in list_aliment()[:50]
    ]

    return templates.TemplateResponse(
        "elevage/aliment.html",
        {
            "request": request,
            "version": __version__,
            "bandes": bandes,
            "ateliers": ateliers,
            "livraisons": livraisons,
            "types_aliment": [(k, LABELS_ALIMENT[k]) for k in VALID_TYPES_ALIMENT],
            "today": date.today().isoformat(),
            "ok": ok,
            "erreur": erreur,
        },
    )


@router.post("/aliment")
async def elevage_aliment_post(request: Request):
    """Enregistre une livraison. Le prix reste facultatif."""
    form = await request.form()

    try:
        bande_id = int(form.get("bande_id") or 0)
    except (TypeError, ValueError):
        return _redirect("/elevage/aliment", erreur="Bande invalide.")

    if not (form.get("quantite_kg") or "").strip():
        return _redirect("/elevage/aliment", erreur="Indique la quantité livrée, en kilos.")

    date_liv = (form.get("date_livraison") or "").strip() or date.today().isoformat()
    try:
        date.fromisoformat(date_liv)
    except ValueError:
        return _redirect("/elevage/aliment", erreur="Date invalide — format attendu AAAA-MM-JJ.")

    try:
        liv = add_aliment({
            "bande_id": bande_id,
            "date_livraison": date_liv,
            "type_aliment": (form.get("type_aliment") or "ponte").strip(),
            "quantite_kg": (form.get("quantite_kg") or "").strip(),
            "prix_total_eur": (form.get("prix_total_eur") or "").strip(),
            "fournisseur": (form.get("fournisseur") or "").strip() or None,
            "notes": (form.get("notes") or "").strip() or None,
        })
    except ValueError as exc:
        return _redirect("/elevage/aliment", erreur=str(exc))

    # Séparateur décimal français — on ne montre pas « 12.5 kg » à un éleveur.
    qte = f"{liv['quantite_kg']:g}".replace(".", ",")
    detail = ""
    if liv["prix_total_eur"] is not None:
        detail = " — " + f"{liv['prix_total_eur']:.2f}".replace(".", ",") + " €"
    return _redirect("/elevage/aliment", ok=f"Livraison de {qte} kg enregistrée{detail}.")


@router.post("/mouvement")
async def elevage_mouvement_post(request: Request):
    """Déclare une mortalité, une réforme ou un ajout d'animaux."""
    form = await request.form()

    try:
        bande_id = int(form.get("bande_id") or 0)
    except (TypeError, ValueError):
        return _redirect("/elevage/bandes", erreur="Bande invalide.")

    type_mvt = (form.get("type_mouvement") or "").strip()
    raw = (form.get("nombre") or "").strip()
    if not raw:
        return _redirect("/elevage/bandes", erreur="Indique le nombre d'animaux concernés.")
    try:
        nombre = int(raw)
    except ValueError:
        return _redirect("/elevage/bandes", erreur="Nombre invalide — chiffres uniquement.")

    date_mvt = (form.get("date_mouvement") or "").strip() or date.today().isoformat()
    try:
        date.fromisoformat(date_mvt)
    except ValueError:
        return _redirect("/elevage/bandes", erreur="Date invalide — format attendu AAAA-MM-JJ.")

    try:
        add_mouvement({
            "bande_id": bande_id, "date_mouvement": date_mvt,
            "type_mouvement": type_mvt, "nombre": nombre,
            "motif": (form.get("motif") or "").strip() or None,
        })
    except ValueError as exc:
        return _redirect("/elevage/bandes", erreur=str(exc))

    label = LABELS_MOUVEMENT.get(type_mvt, type_mvt)
    animaux = "animaux" if nombre > 1 else "animal"
    return _redirect(
        "/elevage/bandes",
        ok=f"{label} de {nombre} {animaux} enregistrée — "
           f"effectif vivant : {effectif_vivant(bande_id)}.",
    )
