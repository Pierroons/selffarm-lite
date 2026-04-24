"""Route SelfInvoice — démo preview facture Factur-X + générateur dynamique."""

from __future__ import annotations

import io
import json
import random
import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from webapp import __version__

# Hub compta self_agri_book — auto-écritures depuis factures
try:
    from self_agri_book.storage import save_ecriture as compta_save_ecriture
except ImportError:
    compta_save_ecriture = None

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
    return templates.TemplateResponse(
        "invoice/index.html",
        {"request": request, "version": __version__},
    )


def _hook_compta_vente(data: dict) -> tuple[int | None, bool]:
    """Enregistre l'auto-écriture de vente dans le hub compta self_agri_book.

    Pour une facture émise :
        Débit 411 Clients
        Crédit 701 Ventes produits finis (+ 44571 TVA collectée si applicable)

    Retourne (ecriture_id, created) :
        - created=True  → nouvelle écriture
        - created=False → écriture déjà existante (dédup)
        - (None, False) si hub indisponible
    """
    if compta_save_ecriture is None:
        return None, False
    try:
        regime_slug = data["regime"]["slug"]
        libelle = f"Vente — {data['client']['nom']} ({data['vendeur']['nom_commercial']})"
        eid, created = compta_save_ecriture(
            date_operation=date.today(),
            journal="VEN",
            numero_piece=data["facture"]["numero"],
            libelle=libelle,
            compte_debit="411",       # Clients
            compte_credit="701",      # Ventes produits finis
            montant_ttc=data["totaux"]["total_ttc"],
            montant_ht=data["totaux"]["total_ht"],
            montant_tva=data["totaux"]["total_tva"],
            source_module="self_invoice",
            source_id=data["facture"]["numero"],
            metadata_json=json.dumps({
                "regime": regime_slug,
                "facturx_profile": data["facture"]["facturx_profile"],
                "nb_lignes": len(data["lignes"]),
                "client": data["client"]["nom"],
            }),
        )
        return eid, created
    except Exception as e:  # pragma: no cover
        import logging
        logging.getLogger("selffarm-webapp").warning("Hook compta vente KO : %s", e)
        return None, False


@router.get("/generer-demo")
async def invoice_generer_demo(regime: str | None = None):
    """Génère une facture Factur-X fictive + PDF + auto-écriture compta.

    ?regime=franchise|micro-ba|reel (sinon aléatoire)
    """
    from weasyprint import HTML

    data = _generer_facture_data(regime)

    tmpl = templates.get_template("invoice/facture.html.j2")
    html_str = tmpl.render(**data)

    pdf_bytes = HTML(string=html_str).write_pdf()

    # Hook compta : auto-écriture 411/701 dans le hub self_agri_book
    ecriture_id, ecriture_created = _hook_compta_vente(data)

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
