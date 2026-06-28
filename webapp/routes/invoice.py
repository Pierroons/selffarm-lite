"""Route SelfInvoice — démo preview facture Factur-X + générateur dynamique."""

from __future__ import annotations

import io
import json
import os
import random
import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates


def _demo_only():
    if os.environ.get("SELFFARM_ENV", "prod") != "demo":
        raise HTTPException(
            status_code=404,
            detail="Génération de facture aléatoire désactivée hors démo publique. "
                   "Utilise le formulaire de saisie facture (V1 sprint).",
        )

from webapp import __version__

# Hub compta self_agri_book — auto-écritures depuis factures
try:
    from self_agri_book.storage import save_ecriture as compta_save_ecriture
except ImportError:
    compta_save_ecriture = None

# Barème TVA agricole — source de vérité unique : self_factur_x_agri.models
# (dé-doublonnage : plus de taux codés en dur dans le formulaire).
try:
    from self_factur_x_agri.models import (
        TVA_BRUTS_55,
        TVA_TRANSFORMES_10,
        TVA_STANDARD_20,
        LIBELLES_UOM_AGRI,
        NATURES_VENTE_AGRI,
    )
    TAUX_TVA = [
        {"pct": str(t.taux_pct), "libelle": t.libelle, "article_cgi": t.article_cgi}
        for t in (TVA_BRUTS_55, TVA_TRANSFORMES_10, TVA_STANDARD_20)
    ]
    # Unités UN/ECE Rec. 20 sourcées du module agri (code, libellé long dropdown, symbole court PDF).
    UNITES_AGRI = [
        {"code": str(uom), "libelle": long, "symbole": court}
        for uom, (long, court) in LIBELLES_UOM_AGRI.items()
    ]
    # Natures de vente → ventilation comptable PCG (7011 végétal / 7012 animal / 7013 service).
    NATURES_VENTE = [
        {"code": str(n), "libelle": lib, "compte_pcg": cpt}
        for n, (lib, cpt) in NATURES_VENTE_AGRI.items()
    ]
except ImportError:  # fallback si le module agri n'est pas disponible
    TAUX_TVA = [
        {"pct": "5.5", "libelle": "Produits agricoles bruts et denrées alimentaires", "article_cgi": "278-0 bis CGI"},
        {"pct": "10", "libelle": "Produits transformés / usage professionnel", "article_cgi": "278 bis CGI"},
        {"pct": "20", "libelle": "TVA normale (services, intrants hors chaîne alim.)", "article_cgi": "278 CGI"},
    ]
    UNITES_AGRI = [
        {"code": "C62", "libelle": "Unité", "symbole": "u"},
        {"code": "KGM", "libelle": "Kilogramme", "symbole": "kg"},
        {"code": "TNE", "libelle": "Tonne", "symbole": "t"},
        {"code": "LTR", "libelle": "Litre", "symbole": "L"},
        {"code": "HAR", "libelle": "Hectare", "symbole": "ha"},
        {"code": "MTK", "libelle": "Mètre carré", "symbole": "m²"},
        {"code": "BX", "libelle": "Botte / box", "symbole": "botte"},
        {"code": "HEA", "libelle": "Tête (animal)", "symbole": "tête"},
        {"code": "NAR", "libelle": "Nombre d'animaux", "symbole": "u"},
    ]
    NATURES_VENTE = [
        {"code": "vegetal", "libelle": "Produits végétaux (récoltes)", "compte_pcg": "7011"},
        {"code": "animal", "libelle": "Produits animaux / animaux", "compte_pcg": "7012"},
        {"code": "service", "libelle": "Prestations de services", "compte_pcg": "7013"},
    ]

# Maps code → valeur, réutilisés par les routes creer/démo + le hook compta.
SYMBOLE_UOM = {u["code"]: u["symbole"] for u in UNITES_AGRI}
COMPTE_PCG_PAR_NATURE = {n["code"]: n["compte_pcg"] for n in NATURES_VENTE}

router = APIRouter(prefix="/invoice", tags=["invoice"])

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# ---------- Pool fixtures démo (PPAM / maraîchage) ----------

VENDEURS = [
    {
        "nom": "Marie DUPONT",
        "nom_commercial": "Herbaria Démo",
        "forme": "Entreprise individuelle",
        "activite": "PPAM bio — Maraîchage & tisanes artisanales",
        "adresse": "12 Chemin des Mésanges",
        "cp": "24000",
        "ville": "Bourg-de-Démonstration",
        "siret": "000 000 000 00000",
        "tva": "FR 00 000000000",
        "ape": "0128Z — Culture plantes à parfum",
    },
    {
        "nom": "Julien LEROY",
        "nom_commercial": "La Ferme des Tilleuls",
        "forme": "Entreprise individuelle",
        "activite": "Maraîchage bio — Vente directe & AMAP",
        "adresse": "1 rue de la Mairie",
        "cp": "33220",
        "ville": "Sainte-Foy",
        "siret": "000 000 000 00000",
        "tva": "FR 00 000000000",
        "ape": "0113Z — Culture de légumes",
    },
]

CLIENTS = [
    {
        "nom": "SARL Herboristerie des Tilleuls",
        "adresse": "8 rue des Lilas",
        "cp": "75011",
        "ville": "Paris",
        "siret": "000 000 000 00000",
        "tva": "FR 00 000000000",
        "email": "commandes@exemple.test",
    },
    {
        "nom": "AMAP du Verger Démo",
        "adresse": "12 place du Marché",
        "cp": "33000",
        "ville": "Bordeaux-Test",
        "siret": "000 000 000 00000",
        "tva": "FR 00 000000000",
        "email": "contact@amap-exemple.test",
    },
    {
        "nom": "Biocoop Les Quatre Saisons",
        "adresse": "3 avenue de la République",
        "cp": "69007",
        "ville": "Lyon-Démo",
        "siret": "000 000 000 00000",
        "tva": "FR 00 000000000",
        "email": "achats@biocoop-exemple.test",
    },
]

PRODUITS = [
    {"nom": "Tisane lavande-mélisse bio", "detail": "Sachet 50 g, séchage naturel",
     "pu_ht": Decimal("38.00"), "tva_pct": Decimal("5.5"), "unite": "sachet"},
    {"nom": "Huile essentielle lavande fine bio", "detail": "Distillation vapeur, 10 ml flacon verre ambré",
     "pu_ht": Decimal("42.50"), "tva_pct": Decimal("20.0"), "unite": "flacon"},
    {"nom": "Eau florale de mélisse bio", "detail": "Hydrolat artisanal, spray 100 ml",
     "pu_ht": Decimal("18.00"), "tva_pct": Decimal("20.0"), "unite": "flacon"},
    {"nom": "Tomates anciennes bio (mélange)", "detail": "Cagette 3 kg — 6-8 variétés",
     "pu_ht": Decimal("14.50"), "tva_pct": Decimal("5.5"), "unite": "cagette"},
    {"nom": "Pommes de terre bio Charlotte", "detail": "Sac 5 kg — récolte automne 2026",
     "pu_ht": Decimal("12.00"), "tva_pct": Decimal("5.5"), "unite": "sac"},
    {"nom": "Panier maraîchage bio de saison", "detail": "Panier 5 kg — AMAP hebdomadaire",
     "pu_ht": Decimal("18.00"), "tva_pct": Decimal("5.5"), "unite": "panier"},
    {"nom": "Bouquet d'herbes aromatiques bio", "detail": "Mélange thym, romarin, laurier — 100 g",
     "pu_ht": Decimal("6.50"), "tva_pct": Decimal("5.5"), "unite": "bouquet"},
    {"nom": "Miel bio de tilleul", "detail": "Pot 500 g — récolte été 2026",
     "pu_ht": Decimal("14.00"), "tva_pct": Decimal("5.5"), "unite": "pot"},
]

REGIMES = {
    "franchise": {
        "slug": "franchise",
        "label": "Franchise en base de TVA (Art. 293 B CGI)",
        "badge": "Franchise TVA · CA < 85 800 €",
        "abattement_73b": False,
        "force_tva_pct": Decimal("0"),
    },
    "micro-ba": {
        "slug": "micro-ba",
        "label": "Régime micro-BA",
        "badge": "Micro-BA · CA ≤ 120 000 €",
        "abattement_73b": False,
        "force_tva_pct": None,  # TVA normale gardée
    },
    "298-bis-agri": {
        "slug": "298-bis-agri",
        "label": "Régime forfaitaire agricole (Art. 298 bis CGI)",
        "badge": "Forfaitaire agricole · non-assujetti TVA",
        "abattement_73b": False,
        "force_tva_pct": Decimal("0"),  # non-assujetti → TVA non applicable
        "mention_tva": "TVA non applicable — régime forfaitaire agricole, art. 298 bis du CGI",
    },
    "reel": {
        "slug": "reel",
        "label": "Régime réel (simplifié ou normal)",
        "badge": "Réel · TVA standard",
        "abattement_73b": False,  # Informatif, pas obligatoire sur la facture
        "force_tva_pct": None,
    },
}


def _generer_facture_data(regime_key: str | None = None) -> dict:
    """Construit un dict complet pour la facture démo."""
    regime_key = regime_key if regime_key in REGIMES else random.choice(list(REGIMES.keys()))
    regime = REGIMES[regime_key]

    vendeur = random.choice(VENDEURS)
    client = random.choice(CLIENTS)

    nb_lignes = random.randint(2, 4)
    produits_choisis = random.sample(PRODUITS, nb_lignes)

    lignes = []
    for p in produits_choisis:
        qte = random.randint(3, 15)
        tva_pct = regime["force_tva_pct"] if regime["force_tva_pct"] is not None else p["tva_pct"]
        total_ht = (p["pu_ht"] * qte).quantize(Decimal("0.01"))
        lignes.append({
            "nom": p["nom"],
            "detail": p["detail"],
            "qte": qte,
            "unite_symbole": p.get("unite", ""),
            "nature": p.get("nature", "vegetal"),
            "compte_pcg": COMPTE_PCG_PAR_NATURE.get(p.get("nature", "vegetal"), "701"),
            "pu_ht": p["pu_ht"],
            "tva_pct": tva_pct,
            "total_ht": total_ht,
        })

    total_ht = sum(l["total_ht"] for l in lignes)
    tva_par_taux = {}
    for l in lignes:
        taux = f'{l["tva_pct"]:.1f}'
        tva_par_taux.setdefault(taux, Decimal("0"))
        tva_par_taux[taux] += (l["total_ht"] * l["tva_pct"] / Decimal("100")).quantize(Decimal("0.01"))
    total_tva = sum(tva_par_taux.values()) if regime["slug"] != "franchise" else Decimal("0")
    total_ttc = (total_ht + total_tva).quantize(Decimal("0.01"))

    today = date.today()
    echeance = today + timedelta(days=30)
    num_facture = f"F-{today.year}-{random.randint(1, 9999):04d}"

    # Profil Factur-X selon régime : BASIC (franchise minimaliste), EN16931 (norme UE standard B2B)
    profile = "BASIC" if regime_key == "franchise" else "EN16931"

    return {
        "facture": {
            "numero": num_facture,
            "date_emission_fr": today.strftime("%d %B %Y").replace("January", "janvier").replace("February", "février").replace("March", "mars").replace("April", "avril").replace("May", "mai").replace("June", "juin").replace("July", "juillet").replace("August", "août").replace("September", "septembre").replace("October", "octobre").replace("November", "novembre").replace("December", "décembre"),
            "date_prestation_fr": (today - timedelta(days=3)).strftime("%d/%m/%Y"),
            "date_echeance_fr": echeance.strftime("%d/%m/%Y"),
            "facturx_profile": profile,
        },
        "regime": regime,
        "vendeur": vendeur,
        "client": client,
        "lignes": lignes,
        "totaux": {
            "total_ht": total_ht,
            "tva_par_taux": tva_par_taux,
            "total_tva": total_tva,
            "total_ttc": total_ttc,
        },
    }


# ---------- Routes ----------

@router.get("", response_class=HTMLResponse)
async def invoice_index(request: Request):
    # Récupère les factures émises depuis le hub compta (source_module='self_invoice')
    factures: list[dict] = []
    try:
        from self_agri_book.storage import list_ecritures
        rows = list_ecritures(source_module="self_invoice", limit=50)
        for r in rows:
            meta = {}
            if r.get("metadata_json"):
                try:
                    meta = json.loads(r["metadata_json"])
                except Exception:
                    meta = {}
            factures.append({
                "numero": r["numero_piece"],
                "client": meta.get("client", "—"),
                "date": r["date_operation"],
                "montant_ttc": r["montant_ttc"],
                "regime": meta.get("regime", ""),
                "facturx_profile": meta.get("facturx_profile", ""),
            })
    except Exception:
        factures = []

    return templates.TemplateResponse(
        "invoice/index.html",
        {"request": request, "version": __version__, "factures": factures},
    )


def _hook_compta_vente(data: dict, pdf_bytes: bytes | None = None) -> tuple[int | None, bool]:
    """Enregistre l'auto-écriture de vente dans le hub compta self_agri_book.

    Pour une facture émise :
        Débit 411 Clients
        Crédit 701 Ventes produits finis (+ 44571 TVA collectée si applicable)

    L'écriture est verrouillée immédiatement (locked=1) et signée par
    hash_pdf (SHA256 du PDF Factur-X émis). Conformité PAF CGI art. 289-VII.

    Retourne (ecriture_id, created) :
        - created=True  → nouvelle écriture
        - created=False → écriture déjà existante (dédup)
        - (None, False) si hub indisponible
    """
    if compta_save_ecriture is None:
        return None, False
    try:
        import hashlib
        regime_slug = data["regime"]["slug"]
        numero = data["facture"]["numero"]
        client_nom = data["client"]["nom"]
        nom_commercial = data["vendeur"]["nom_commercial"]
        hash_pdf = hashlib.sha256(pdf_bytes).hexdigest() if pdf_bytes else None

        # Archivage du PDF émis (conformité conservation 10 ans + inclus au backup).
        # Ne JAMAIS écraser un PDF déjà archivé → préserve le document original signé.
        if pdf_bytes and numero:
            try:
                import os
                from pathlib import Path
                data_dir = os.environ.get("SELFFARM_DATA_DIR", str(Path.home() / ".selffarm"))
                fdir = Path(data_dir) / "factures"
                fdir.mkdir(parents=True, exist_ok=True)
                safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in str(numero))
                fpath = fdir / f"{safe}.pdf"
                if not fpath.exists():
                    fpath.write_bytes(pdf_bytes)
            except Exception:
                import logging
                logging.getLogger("selffarm.invoice").warning(
                    "Archivage PDF facture %s échoué — non bloquant", numero, exc_info=True
                )

        # Ventilation par nature de vente : un compte PCG produit par groupe
        # (7011 végétal / 7012 animal / 7013 service). self_agri_book stocke une
        # écriture mono-compte → une écriture par compte crédit, source_id suffixé
        # du compte pour préserver la dédup (CGI art. 289-VII).
        groupes: dict[str, dict] = {}
        for l in data["lignes"]:
            compte = l.get("compte_pcg", "701")
            g = groupes.setdefault(compte, {"ht": Decimal("0"), "tva": Decimal("0")})
            g["ht"] += l["total_ht"]
            g["tva"] += (l["total_ht"] * l["tva_pct"] / Decimal("100")).quantize(Decimal("0.01"))

        first_eid: int | None = None
        created_any = False
        for compte, g in groupes.items():
            ht = g["ht"]
            tva = g["tva"] if regime_slug != "franchise" else Decimal("0")
            ttc = (ht + tva).quantize(Decimal("0.01"))
            libelle = f"Vente {compte} — {client_nom} ({nom_commercial})"
            eid, created = compta_save_ecriture(
                date_operation=date.today(),
                journal="VEN",
                numero_piece=numero,
                libelle=libelle,
                compte_debit="411",       # Clients
                compte_credit=compte,     # 7011/7012/7013 selon la nature
                montant_ttc=ttc,
                montant_ht=ht,
                montant_tva=tva,
                source_module="self_invoice",
                source_id=f"{numero}#{compte}",
                hash_pdf=hash_pdf,
                locked=True,  # Conformité PAF : facture émise = immédiatement verrouillée
                metadata_json=json.dumps({
                    "regime": regime_slug,
                    "facturx_profile": data["facture"]["facturx_profile"],
                    "compte_pcg": compte,
                    "client": client_nom,
                }),
            )
            if first_eid is None:
                first_eid = eid
            created_any = created_any or created
        return first_eid, created_any
    except Exception as e:  # pragma: no cover
        import logging
        logging.getLogger("selffarm-webapp").warning("Hook compta vente KO : %s", e)
        return None, False


@router.get("/nouvelle", response_class=HTMLResponse)
async def invoice_nouvelle_form(request: Request):
    """Formulaire de saisie d'une nouvelle facture (V1).

    Le numéro est calculé via le compteur séquentiel DB (peek seul, pas
    d'incrément à l'affichage — l'incrément se fait au POST /creer).
    """
    today = date.today()
    try:
        from self_agri_book.storage import peek_numero_facture
        next_numero = peek_numero_facture(today.year, "F")
    except Exception:
        next_numero = f"F-{today.year}-0001"
    return templates.TemplateResponse(
        "invoice/form.html",
        {
            "request": request,
            "today": today.isoformat(),
            "echeance_default": (today + timedelta(days=30)).isoformat(),
            "regimes": REGIMES,
            "taux_tva": TAUX_TVA,
            "unites_agri": UNITES_AGRI,
            "natures_vente": NATURES_VENTE,
            "next_numero": next_numero,
        },
    )


@router.post("/creer")
async def invoice_creer(request: Request):
    """Crée une facture depuis le formulaire utilisateur."""
    from weasyprint import HTML

    form = await request.form()

    # --- VENDEUR (V1 : hardcodé, à terme stocké en config exploitation) ---
    vendeur = {
        "nom": form.get("vendeur_nom", "Mon exploitation"),
        "nom_commercial": form.get("vendeur_nom", "Mon exploitation"),
        "forme": "Entreprise individuelle",
        "activite": form.get("vendeur_activite", "Exploitation agricole"),
        "adresse": form.get("vendeur_adresse", ""),
        "cp": form.get("vendeur_cp", ""),
        "ville": form.get("vendeur_ville", ""),
        "siret": form.get("vendeur_siret", ""),
        "tva": form.get("vendeur_tva", ""),
        "ape": form.get("vendeur_ape", ""),
    }

    # --- CLIENT ---
    client = {
        "nom": form.get("client_nom", "Client"),
        "adresse": form.get("client_adresse", ""),
        "cp": form.get("client_cp", ""),
        "ville": form.get("client_ville", ""),
        "siret": form.get("client_siret", ""),
        "tva": form.get("client_tva", ""),
        "email": form.get("client_email", ""),
    }

    # --- LIGNES (jusqu'à 10) ---
    regime_key = form.get("regime", "reel")
    regime = REGIMES.get(regime_key, REGIMES["reel"])

    lignes: list[dict] = []
    for i in range(10):
        nom = (form.get(f"ligne_{i}_nom", "") or "").strip()
        if not nom:
            continue
        try:
            qte = int(form.get(f"ligne_{i}_qte", "1") or "1")
            pu_ht = Decimal(str(form.get(f"ligne_{i}_pu_ht", "0") or "0"))
            tva_pct_raw = form.get(f"ligne_{i}_tva_pct", "20")
            tva_pct = Decimal(str(tva_pct_raw or "20"))
        except Exception:
            continue
        if regime["force_tva_pct"] is not None:
            tva_pct = regime["force_tva_pct"]
        total_ht = (pu_ht * qte).quantize(Decimal("0.01"))
        unite_code = (form.get(f"ligne_{i}_unite", "C62") or "C62").strip()
        nature = (form.get(f"ligne_{i}_nature", "vegetal") or "vegetal").strip()
        lignes.append({
            "nom": nom,
            "detail": form.get(f"ligne_{i}_detail", "") or "",
            "qte": qte,
            "unite_code": unite_code,
            "unite_symbole": SYMBOLE_UOM.get(unite_code, ""),
            "nature": nature,
            "compte_pcg": COMPTE_PCG_PAR_NATURE.get(nature, "701"),
            "pu_ht": pu_ht,
            "tva_pct": tva_pct,
            "total_ht": total_ht,
        })

    if not lignes:
        from fastapi.responses import HTMLResponse as _H
        return _H("<p style='color:red;padding:20px'>Aucune ligne saisie. <a href='/invoice/nouvelle'>retour</a></p>", status_code=400)

    # --- TOTAUX ---
    total_ht = sum(l["total_ht"] for l in lignes)
    tva_par_taux: dict[str, Decimal] = {}
    for l in lignes:
        taux = f'{l["tva_pct"]:.1f}'
        tva_par_taux.setdefault(taux, Decimal("0"))
        tva_par_taux[taux] += (l["total_ht"] * l["tva_pct"] / Decimal("100")).quantize(Decimal("0.01"))
    total_tva = sum(tva_par_taux.values()) if regime["slug"] != "franchise" else Decimal("0")
    total_ttc = (total_ht + total_tva).quantize(Decimal("0.01"))

    # --- DATES & NUMÉRO ---
    today = date.today()
    try:
        date_echeance = date.fromisoformat(form.get("date_echeance", "") or (today + timedelta(days=30)).isoformat())
    except Exception:
        date_echeance = today + timedelta(days=30)

    # Numéro séquentiel DB-driven : on IGNORE la valeur du form (confiance zéro
    # côté client). Le compteur garantit la non-corruption + la non-duplication.
    # Conformité CGI art. 289-II : numérotation continue sans saut.
    try:
        from self_agri_book.storage import next_numero_facture
        numero = next_numero_facture(today.year, "F")
    except Exception:
        numero = (form.get("numero", "") or f"F-{today.year}-{random.randint(1, 9999):04d}").strip()

    profile = "BASIC" if regime_key == "franchise" else "EN16931"

    mois_fr = ["janvier","février","mars","avril","mai","juin","juillet","août","septembre","octobre","novembre","décembre"]
    data = {
        "facture": {
            "numero": numero,
            "date_emission_fr": f"{today.day} {mois_fr[today.month - 1]} {today.year}",
            "date_prestation_fr": today.strftime("%d/%m/%Y"),
            "date_echeance_fr": date_echeance.strftime("%d/%m/%Y"),
            "facturx_profile": profile,
        },
        "regime": regime,
        "vendeur": vendeur,
        "client": client,
        "lignes": lignes,
        "totaux": {
            "total_ht": total_ht,
            "tva_par_taux": tva_par_taux,
            "total_tva": total_tva,
            "total_ttc": total_ttc,
        },
    }

    tmpl = templates.get_template("invoice/facture.html.j2")
    html_str = tmpl.render(**data)
    pdf_bytes = HTML(string=html_str).write_pdf()

    ecriture_id, ecriture_created = _hook_compta_vente(data, pdf_bytes=pdf_bytes)

    filename = f"{numero}_{regime_key}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "X-Selfinvoice-Profile": profile,
            "X-Selfinvoice-Regime": regime_key,
            "X-Selfagribook-Ecriture-Id": str(ecriture_id) if ecriture_id else "",
            "X-Selfagribook-Ecriture-Created": "true" if ecriture_created else "false",
        },
    )


@router.get("/generer-demo")
async def invoice_generer_demo(regime: str | None = None):
    _demo_only()
    """Génère une facture Factur-X fictive + PDF + auto-écriture compta.

    ?regime=franchise|micro-ba|reel (sinon aléatoire)
    """
    from weasyprint import HTML

    data = _generer_facture_data(regime)

    tmpl = templates.get_template("invoice/facture.html.j2")
    html_str = tmpl.render(**data)

    pdf_bytes = HTML(string=html_str).write_pdf()

    # Hook compta : auto-écriture 411/701 dans le hub self_agri_book
    ecriture_id, ecriture_created = _hook_compta_vente(data, pdf_bytes=pdf_bytes)

    filename = f"{data['facture']['numero']}_{data['regime']['slug']}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "X-Selfinvoice-Profile": data["facture"]["facturx_profile"],
            "X-Selfinvoice-Regime": data["regime"]["slug"],
            "X-Selfagribook-Ecriture-Id": str(ecriture_id) if ecriture_id else "",
            "X-Selfagribook-Ecriture-Created": "true" if ecriture_created else "false",
        },
    )
