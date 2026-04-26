"""Route /compta — dashboard hub comptable self_agri_book + démos interactives."""

from __future__ import annotations

import json
import os
import random
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from webapp import __version__


def _demo_only():
    """Lève 404 si l'instance n'est pas en mode démo publique.

    Contrôle d'accès aux endpoints de génération de fixtures :
    - SELFFARM_ENV=demo → autorisé (instance publique selffarm.my-self.fr)
    - SELFFARM_ENV=dev / prod / perso → 404 (vraies données utilisateur)
    """
    if os.environ.get("SELFFARM_ENV", "prod") != "demo":
        raise HTTPException(
            status_code=404,
            detail="Endpoint démo désactivé en environnement de production. "
                   "Utilise les formulaires de saisie manuelle (V1 sprint).",
        )

try:
    from self_agri_book.storage import (
        list_ecritures,
        balance_par_compte,
        stats_globales,
        save_ecriture,
        find_ecriture_by_source,
        reset_demo,
        bilan_data,
        resultat_data,
        export_fec,
    )
    STORAGE_OK = True
except ImportError:
    STORAGE_OK = False

# Pool de fixtures de ventes rapides (saisie manuelle compta — sans PDF).
#
# Distinction importante :
#   - facturable=True  (B2B) : client identifié avec SIRET → peut alimenter une facture Factur-X
#   - facturable=False (B2C) : vente directe anonyme (marché, AMAP, livraison cash) →
#                              écriture comptable seule, PAS facturable
VENTES_FIXTURES = [
    # --- Ventes B2B facturables (client identifié avec SIRET) ---
    # Chaque fixture définit :
    #   - libelle_compta : ce qui apparaît dans le JOURNAL comptable
    #   - article_nom    : ce qui apparaît comme LIGNE DE FACTURE (produit vendu)
    #   - article_qte + article_unite + article_pu_ht : détail ligne facture
    {"libelle_compta": "Vente gros huile essentielle lavande",
     "article_nom": "Huile essentielle Lavande fine bio", "article_detail": "Distillation vapeur, flacon 10 ml verre ambré",
     "article_qte": 30, "article_unite": "flacon", "article_pu_ht": Decimal("13.60"),
     "client": "SARL Herboristerie des Tilleuls", "adresse": "8 rue des Lilas", "cp": "75011", "ville": "Paris",
     "siret": "111 222 333 44444", "tva": "FR 11 111222333", "email": "commandes@exemple.test",
     "tva_pct": Decimal("20"), "facturable": True},
    {"libelle_compta": "Vente gros miel tilleul bio",
     "article_nom": "Miel de Tilleul Bio 500 g", "article_detail": "Récolte été 2026, palette 24 pots verre",
     "article_qte": 24, "article_unite": "pot", "article_pu_ht": Decimal("17.50"),
     "client": "Biocoop Les Quatre Saisons", "adresse": "3 avenue de la République", "cp": "69007", "ville": "Lyon-Démo",
     "siret": "222 333 444 55555", "tva": "FR 22 222333444", "email": "achats@biocoop-exemple.test",
     "tva_pct": Decimal("5.5"), "facturable": True},
    {"libelle_compta": "Vente eau florale mélisse (lot revendeur)",
     "article_nom": "Eau florale Mélisse bio 100 ml", "article_detail": "Hydrolat artisanal, spray verre ambré",
     "article_qte": 12, "article_unite": "flacon", "article_pu_ht": Decimal("15.00"),
     "client": "Savonnerie Artisanale du Coin", "adresse": "14 rue de la Rivière", "cp": "26000", "ville": "Valence",
     "siret": "333 444 555 66666", "tva": "FR 33 333444555", "email": "contact@savon-exemple.test",
     "tva_pct": Decimal("20"), "facturable": True},
    {"libelle_compta": "Vente plants aromatiques bio printemps",
     "article_nom": "Plants Thym vulgaire bio", "article_detail": "Godet 9 cm — 18 semaines culture",
     "article_qte": 25, "article_unite": "plant", "article_pu_ht": Decimal("3.80"),
     "client": "Jardinerie Collobrières", "adresse": "5 route du Moulin", "cp": "83610", "ville": "Collobrières",
     "siret": "444 555 666 77777", "tva": "FR 44 444555666", "email": "commandes@jardin-exemple.test",
     "tva_pct": Decimal("5.5"), "facturable": True},
    {"libelle_compta": "Vente tisanes bio gamme (revendeur)",
     "article_nom": "Tisane Lavande-Mélisse bio", "article_detail": "Sachet 50 g, mélange séchage naturel",
     "article_qte": 40, "article_unite": "sachet", "article_pu_ht": Decimal("6.50"),
     "client": "SARL Les 4 Saisons Bio", "adresse": "22 chemin des Peupliers", "cp": "33000", "ville": "Bordeaux-Test",
     "siret": "555 666 777 88888", "tva": "FR 55 555666777", "email": "pro@4saisons-exemple.test",
     "tva_pct": Decimal("5.5"), "facturable": True},
    {"libelle_compta": "Vente huile CBD 10% gros herboristerie",
     "article_nom": "Huile CBD 10 % bio 10 ml", "article_detail": "Extraction CO₂ supercritique, flacon verre ambré pipette",
     "article_qte": 20, "article_unite": "flacon", "article_pu_ht": Decimal("21.00"),
     "client": "Herboristerie Le Chanvre Sage", "adresse": "7 place de la Fontaine", "cp": "34000", "ville": "Montpellier",
     "siret": "666 777 888 99999", "tva": "FR 66 666777888", "email": "pro@herbochanvre-exemple.test",
     "tva_pct": Decimal("20"), "facturable": True},
    # --- Ventes B2C non-facturables (vente directe anonyme) ---
    {"libelle_compta": "Vente directe marché (tisanes + légumes)",
     "client": "Divers clients marché hebdo", "siret": None, "montant_ht": Decimal("240.00"),
     "tva_pct": Decimal("5.5"), "facturable": False},
    {"libelle_compta": "Vente paniers maraîchage AMAP (livraison hebdo)",
     "client": "Adhérents AMAP du Verger Démo", "siret": None, "montant_ht": Decimal("180.00"),
     "tva_pct": Decimal("5.5"), "facturable": False},
    {"libelle_compta": "Vente panier bio livraison domicile (abonnés)",
     "client": "Livraisons abonnés particuliers", "siret": None, "montant_ht": Decimal("68.00"),
     "tva_pct": Decimal("5.5"), "facturable": False},
    {"libelle_compta": "Vente boutique producteurs (dépôt-vente)",
     "client": "Boutique de producteurs (dépôt-vente)", "siret": None, "montant_ht": Decimal("145.00"),
     "tva_pct": Decimal("5.5"), "facturable": False},
]


def _vente_montant_ht(v: dict) -> Decimal:
    """Calcule le montant HT : soit qte × pu_ht (B2B), soit montant_ht (B2C)."""
    if "article_qte" in v and "article_pu_ht" in v:
        return (Decimal(v["article_qte"]) * v["article_pu_ht"]).quantize(Decimal("0.01"))
    return v["montant_ht"]

# Pool de fixtures d'achats fictifs (PPAM / maraîchage — cohérent avec les factures)
ACHATS_FIXTURES = [
    {"libelle": "Achat compost bio Herbex", "compte_debit": "6011", "montant_ht": Decimal("120.00"), "tva_pct": Decimal("20"), "fourn": "Herbex SAS"},
    {"libelle": "Achat semences maraîchage bio", "compte_debit": "6011", "montant_ht": Decimal("85.00"), "tva_pct": Decimal("5.5"), "fourn": "Semaforma"},
    {"libelle": "Achat plants PPAM (lavande, thym)", "compte_debit": "6011", "montant_ht": Decimal("210.00"), "tva_pct": Decimal("5.5"), "fourn": "Pépinières Val de Loire"},
    {"libelle": "Achat emballages tisanes (sachets kraft)", "compte_debit": "6061", "montant_ht": Decimal("45.00"), "tva_pct": Decimal("20"), "fourn": "Embalpack"},
    {"libelle": "Achat flacons verre ambré 10 ml", "compte_debit": "6061", "montant_ht": Decimal("78.00"), "tva_pct": Decimal("20"), "fourn": "Cogefra"},
    {"libelle": "Abonnement VIVEA formation (2e tranche)", "compte_debit": "6281", "montant_ht": Decimal("150.00"), "tva_pct": Decimal("20"), "fourn": "VIVEA"},
    {"libelle": "Location parcelle 1 ha (trimestre)", "compte_debit": "613", "montant_ht": Decimal("250.00"), "tva_pct": Decimal("0"), "fourn": "M. Dupuis Bail rural"},
    {"libelle": "Carburant tracteur (gasoil non routier)", "compte_debit": "6062", "montant_ht": Decimal("180.00"), "tva_pct": Decimal("20"), "fourn": "TotalEnergies"},
    {"libelle": "Entretien tracteur (révision 100h)", "compte_debit": "615", "montant_ht": Decimal("320.00"), "tva_pct": Decimal("20"), "fourn": "Garage Delpech"},
    {"libelle": "Certification bio Ecocert (annuelle)", "compte_debit": "622", "montant_ht": Decimal("550.00"), "tva_pct": Decimal("20"), "fourn": "Ecocert France"},
]

router = APIRouter(prefix="/compta", tags=["compta"])

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# Labels PCG minimaux pour affichage lisible (hub démo)
COMPTES_LABELS = {
    "411": "411 — Clients",
    "401": "401 — Fournisseurs",
    "512": "512 — Banque",
    "530": "530 — Caisse",
    "701": "701 — Ventes produits finis",
    "707": "707 — Ventes de marchandises",
    "6011": "6011 — Semences",
    "6012": "6012 — Engrais",
    "6013": "6013 — Produits phyto",
    "6014": "6014 — Aliments bétail",
    "6064": "6064 — Fournitures administratives",
    "613": "613 — Locations",
    "615": "615 — Entretien et réparations",
    "616": "616 — Primes d'assurance",
    "622": "622 — Rémunérations d'intermédiaires",
    "6451": "6451 — Cotisations MSA",
    "74": "74 — Subventions d'exploitation",
    "44571": "44571 — TVA collectée",
    "44566": "44566 — TVA déductible sur ABS",
    "2154": "2154 — Matériel agricole",
    "2184": "2184 — Mobilier",
    "164": "164 — Emprunts auprès des établissements de crédit",
}


def _enrich_libelle_compte(code: str) -> str:
    return COMPTES_LABELS.get(code, code)


@router.get("", response_class=HTMLResponse)
async def compta_index(request: Request):
    if not STORAGE_OK:
        return HTMLResponse(
            "<h1>Module self_agri_book indisponible</h1>",
            status_code=503,
        )
    ecritures = list_ecritures(limit=100)
    # Enrichissement lisible côté template
    for e in ecritures:
        e["compte_debit_label"] = _enrich_libelle_compte(e["compte_debit"])
        e["compte_credit_label"] = _enrich_libelle_compte(e["compte_credit"])
        if e.get("metadata_json"):
            try:
                e["metadata"] = json.loads(e["metadata_json"])
            except Exception:
                e["metadata"] = {}
        else:
            e["metadata"] = {}

    balance = balance_par_compte(limit=50)
    for b in balance:
        b["compte_label"] = _enrich_libelle_compte(b["compte"])
        b["solde"] = (b["total_debit"] or 0) - (b["total_credit"] or 0)

    stats = stats_globales()

    return templates.TemplateResponse(
        "compta/index.html",
        {
            "request": request,
            "version": __version__,
            "ecritures": ecritures,
            "balance": balance,
            "stats": stats,
        },
    )


# --- Routes démo interactives ---

def _compte_label(code: str) -> str:
    return COMPTES_LABELS.get(code, code)


# Pool de fixtures de prélèvements bancaires récurrents
PRELEVEMENTS_FIXTURES = [
    {"libelle": "Prélèvement MSA cotisations (mensuel)", "compte_debit": "6451", "montant_ht": Decimal("350.00"), "tva_pct": Decimal("0"), "benef": "MSA"},
    {"libelle": "Facture EDF électricité transformation", "compte_debit": "6061", "montant_ht": Decimal("85.00"), "tva_pct": Decimal("20"), "benef": "EDF Entreprises"},
    {"libelle": "Prime assurance exploitation (trimestre)", "compte_debit": "616", "montant_ht": Decimal("100.00"), "tva_pct": Decimal("20"), "benef": "Groupama"},
    {"libelle": "Abonnement téléphone + internet pro", "compte_debit": "6262", "montant_ht": Decimal("35.00"), "tva_pct": Decimal("20"), "benef": "Orange Pro"},
    {"libelle": "Fermage trimestriel (foncier agricole)", "compte_debit": "6132", "montant_ht": Decimal("62.50"), "tva_pct": Decimal("0"), "benef": "M. Dupuis bail rural"},
]

# Frais bancaires récurrents
FRAIS_BANQUE_FIXTURES = [
    {"libelle": "Frais tenue de compte mensuels", "compte_debit": "6271", "montant_ht": Decimal("4.50"), "tva_pct": Decimal("0")},
    {"libelle": "Cotisation carte CB pro (annuelle /12)", "compte_debit": "6271", "montant_ht": Decimal("8.00"), "tva_pct": Decimal("0")},
    {"libelle": "Commission virement européen SEPA", "compte_debit": "6271", "montant_ht": Decimal("1.20"), "tva_pct": Decimal("0")},
]


@router.post("/generer-vente")
async def compta_generer_vente(request: Request):
    _demo_only()
    """Génère une vente rapide (411/701) — saisie manuelle compta, sans PDF.

    Cas d'usage : vente directe au marché, AMAP, livraison cash, etc.
    Pas de PDF Factur-X généré, juste une ligne de journal. Pour une vraie
    facture avec PDF + XML, passer par /invoice.
    """
    if not STORAGE_OK:
        return JSONResponse({"error": "storage KO"}, status_code=503)

    vente = random.choice(VENTES_FIXTURES)
    montant_ht = _vente_montant_ht(vente)
    tva = (montant_ht * vente["tva_pct"] / Decimal("100")).quantize(Decimal("0.01"))
    ttc = (montant_ht + tva).quantize(Decimal("0.01"))
    today = date.today()
    # Préfixe V = B2B facturable, D = vente directe non-facturable
    prefix = "V" if vente["facturable"] else "D"
    numero = f"{prefix}-{today.year}-{random.randint(1, 9999):04d}"
    source_id = f"{'vente' if vente['facturable'] else 'direct'}-{random.randint(100000, 999999)}"

    # Metadata complète pour permettre la consolidation en facture Factur-X
    meta = {
        "client": vente["client"],
        "facturable": vente["facturable"],
        "categorie": "b2b_facturable" if vente["facturable"] else "vente_directe_b2c",
    }
    if vente["facturable"]:
        meta.update({
            "client_adresse": vente.get("adresse", ""),
            "client_cp": vente.get("cp", ""),
            "client_ville": vente.get("ville", ""),
            "client_siret": vente.get("siret", ""),
            "client_tva": vente.get("tva", ""),
            "client_email": vente.get("email", ""),
            # Infos ligne facture : nom article + qte + unité + pu_ht
            "article_nom": vente.get("article_nom", vente["libelle_compta"]),
            "article_detail": vente.get("article_detail", ""),
            "article_qte": vente.get("article_qte", 1),
            "article_unite": vente.get("article_unite", "unité"),
            "article_pu_ht": str(vente.get("article_pu_ht", montant_ht)),
        })

    eid, created = save_ecriture(
        date_operation=today,
        journal="VEN",
        numero_piece=numero,
        libelle=f"{vente['libelle_compta']} — {vente['client']}",
        compte_debit="411",    # Clients
        compte_credit="701",   # Ventes produits finis
        montant_ttc=ttc,
        montant_ht=montant_ht,
        montant_tva=tva,
        source_module="self_compta_manuel",
        source_id=source_id,
        metadata_json=json.dumps(meta),
    )

    return _json_or_redirect(request, {
        "ok": True,
        "action": "vente_créée",
        "ecriture_id": eid,
        "created": created,
        "numero_piece": numero,
        "libelle": vente["libelle_compta"],
        "client": vente["client"],
        "facturable": vente["facturable"],
        "article_nom": vente.get("article_nom", "") if vente["facturable"] else "",
        "montant_ttc": str(ttc),
    })


@router.post("/generer-achat")
async def compta_generer_achat(request: Request):
    _demo_only()
    """Génère un achat fictif (6011/401 par défaut). Ne crée PAS de facture associée.

    Démonstration : une écriture d'achat est distincte d'une facture de vente.
    """
    if not STORAGE_OK:
        return JSONResponse({"error": "storage KO"}, status_code=503)

    achat = random.choice(ACHATS_FIXTURES)
    tva = (achat["montant_ht"] * achat["tva_pct"] / Decimal("100")).quantize(Decimal("0.01"))
    ttc = (achat["montant_ht"] + tva).quantize(Decimal("0.01"))
    today = date.today()
    numero = f"A-{today.year}-{random.randint(1, 9999):04d}"
    source_id = f"achat-{random.randint(100000, 999999)}"

    eid, created = save_ecriture(
        date_operation=today,
        journal="ACH",
        numero_piece=numero,
        libelle=f"{achat['libelle']} ({achat['fourn']})",
        compte_debit=achat["compte_debit"],    # charge (6011/6061/613/...)
        compte_credit="401",                    # Fournisseurs
        montant_ttc=ttc,
        montant_ht=achat["montant_ht"],
        montant_tva=tva,
        source_module="self_achats",
        source_id=source_id,
        metadata_json=json.dumps({"fourn": achat["fourn"], "categorie_compte": achat["compte_debit"]}),
    )

    return _json_or_redirect(request, {
        "ok": True,
        "action": "achat_créé",
        "ecriture_id": eid,
        "created": created,
        "numero_piece": numero,
        "libelle": achat["libelle"],
        "compte_debit": achat["compte_debit"],
        "compte_debit_label": _compte_label(achat["compte_debit"]),
        "compte_credit": "401",
        "compte_credit_label": _compte_label("401"),
        "montant_ttc": str(ttc),
    })


@router.post("/rejouer-derniere-vente")
async def compta_rejouer_derniere_vente(request: Request):
    _demo_only()
    """Démo dédup : retente la dernière facture générée.

    Si l'écriture existe déjà (même source_id), le hub retourne l'id existant
    sans créer de doublon — démonstration de l'idempotence.
    """
    if not STORAGE_OK:
        return JSONResponse({"error": "storage KO"}, status_code=503)

    # Cherche la dernière écriture self_invoice
    last_invoice = [e for e in list_ecritures(limit=20) if e["source_module"] == "self_invoice"]
    if not last_invoice:
        return _json_or_redirect(request, {
            "ok": False,
            "action": "aucune_facture",
            "message": "Aucune facture self_invoice en base. Va d'abord sur /invoice pour en générer une.",
        })

    last = last_invoice[0]
    try:
        meta = json.loads(last.get("metadata_json") or "{}")
    except Exception:
        meta = {}

    eid, created = save_ecriture(
        date_operation=date.fromisoformat(last["date_operation"]),
        journal=last["journal"],
        numero_piece=last["numero_piece"],
        libelle=last["libelle"],
        compte_debit=last["compte_debit"],
        compte_credit=last["compte_credit"],
        montant_ttc=Decimal(last["montant_ttc"]),
        montant_ht=Decimal(last["montant_ht"]) if last.get("montant_ht") else None,
        montant_tva=Decimal(last["montant_tva"]) if last.get("montant_tva") else None,
        source_module=last["source_module"],
        source_id=last["source_id"],
        metadata_json=last.get("metadata_json"),
    )

    return _json_or_redirect(request, {
        "ok": True,
        "action": "dedup_active" if not created else "créée_nouvelle",
        "ecriture_id": eid,
        "created": created,
        "numero_piece": last["numero_piece"],
        "message": (
            f"♻️ Dédup appliquée — l'écriture #{eid} existait déjà pour {last['numero_piece']} "
            "(même source_module + source_id). Aucun doublon créé."
            if not created else
            f"Nouvelle écriture #{eid} créée (cas rare : l'ancienne écriture avait été supprimée)."
        ),
    })


def _determiner_client_facture(ventes: list, clients_distincts: set) -> dict:
    """Choisit les infos client pour la facture consolidée.

    - 1 seul client → infos complètes de ce client (depuis metadata de la 1re vente)
    - N clients distincts → facture "consolidée multi-clients" avec mention explicite
    """
    if len(clients_distincts) == 1 and ventes:
        # Un seul client — on prend ses infos depuis la première vente
        _, meta = ventes[0]
        return {
            "nom": meta.get("client", list(clients_distincts)[0]),
            "adresse": meta.get("client_adresse", "—"),
            "cp": meta.get("client_cp", "—"),
            "ville": meta.get("client_ville", "—"),
            "siret": meta.get("client_siret", "000 000 000 00000"),
            "tva": meta.get("client_tva", "FR 00 000000000"),
            "email": meta.get("client_email", "—"),
        }
    # Plusieurs clients → facture multi-client (cas de consolidation de période)
    noms = ", ".join(sorted(clients_distincts)[:3])
    if len(clients_distincts) > 3:
        noms += f" (+{len(clients_distincts) - 3} autres)"
    return {
        "nom": f"Facture multi-clients — {noms}",
        "adresse": "Consolidation journal — ventilation par client en annexe",
        "cp": "—",
        "ville": "—",
        "siret": "—",
        "tva": "—",
        "email": "—",
    }


@router.get("/resultat", response_class=HTMLResponse)
async def compta_resultat(request: Request):
    """Compte de résultat simplifié — charges vs produits → résultat net."""
    if not STORAGE_OK:
        raise HTTPException(503, "storage KO")
    data = resultat_data()
    # Enrichir labels lisibles
    for p in data["produits"]:
        p["label"] = _enrich_libelle_compte(p["compte"])
    for c in data["charges"]:
        c["label"] = _enrich_libelle_compte(c["compte"])
    return templates.TemplateResponse(
        "compta/resultat.html",
        {"request": request, "version": __version__, "data": data},
    )


@router.get("/bilan", response_class=HTMLResponse)
async def compta_bilan(request: Request):
    """Bilan simplifié — actif ↔ passif à partir du hub compta."""
    if not STORAGE_OK:
        raise HTTPException(503, "storage KO")
    data = bilan_data()
    for groupe, lignes in data["actif"].items():
        for l in lignes:
            l["label"] = _enrich_libelle_compte(l["compte"])
    for groupe, lignes in data["passif"].items():
        for l in lignes:
            l["label"] = _enrich_libelle_compte(l["compte"])
    return templates.TemplateResponse(
        "compta/bilan.html",
        {"request": request, "version": __version__, "data": data},
    )


@router.get("/integrite", response_class=HTMLResponse)
async def compta_integrite(request: Request):
    """Page de vérification d'intégrité PAF — chaîne de hash + audit log + verrous.

    Conformité CGI art. 289-VII : un contrôleur DGFIP peut auditer ici
    l'intégrité complète du hub compta en 30 secondes.
    """
    if not STORAGE_OK:
        raise HTTPException(503, "storage KO")
    from self_agri_book.storage import verify_chain, list_audit_log, list_ecritures
    chain = verify_chain()
    audit_entries = list_audit_log(limit=50)
    # Pour chaque entrée audit, parse details_json si présent
    for e in audit_entries:
        if e.get("details_json"):
            try:
                e["details"] = json.loads(e["details_json"])
            except Exception:
                e["details"] = {}
        else:
            e["details"] = {}
    # Stats verrouillage
    all_ecritures = list_ecritures(limit=1000)
    nb_total = len(all_ecritures)
    nb_locked = sum(1 for e in all_ecritures if e.get("locked"))
    nb_with_hash = sum(1 for e in all_ecritures if e.get("hash_data"))
    nb_with_pdf_hash = sum(1 for e in all_ecritures if e.get("hash_pdf"))
    return templates.TemplateResponse(
        "compta/integrite.html",
        {
            "request": request,
            "version": __version__,
            "chain": chain,
            "audit_entries": audit_entries,
            "stats": {
                "nb_total": nb_total,
                "nb_locked": nb_locked,
                "nb_with_hash": nb_with_hash,
                "nb_with_pdf_hash": nb_with_pdf_hash,
            },
        },
    )


@router.get("/export-fec")
async def compta_export_fec(siren: str = "000000000"):
    """Export FEC DGFIP conforme (art. L47 A-I LPF + BOI-CF-IOR-60-40-10).

    Fichier texte tab-separated UTF-8, 18 colonnes obligatoires.
    Nom : <siren>FEC<AAAAMMJJ>.txt
    """
    if not STORAGE_OK:
        raise HTTPException(503, "storage KO")
    filename, contenu = export_fec(siren=siren)
    return Response(
        content=contenu,
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Selfagribook-Export": "fec-dgfip",
        },
    )


@router.get("/facture-du-journal")
async def compta_facture_du_journal(limit: int = 8):
    """Génère une facture Factur-X **à partir des ventes du journal compta**.

    Prend les N dernières écritures de vente (compte_debit=411 ET compte_credit=701)
    et les consolide en une seule facture PDF/A-3. Les lignes de la facture = écritures
    du journal. Plus de lignes random : la source de vérité est le hub compta.
    """
    if not STORAGE_OK:
        raise HTTPException(503, "storage KO")

    # Récupère plus d'écritures pour avoir de la marge après filtre B2B
    ventes_brutes = list_ecritures(limit=max(limit * 3, 30), compte="411")
    ventes_brutes = [e for e in ventes_brutes if e["compte_debit"] == "411" and e["compte_credit"] == "701"]

    # Filtre : seules les ventes FACTURABLES (B2B avec SIRET identifié) alimentent la facture.
    # Les ventes directes B2C anonymes (marché, AMAP, livraison) sont exclues — pas de client à facturer.
    ventes = []
    for e in ventes_brutes:
        try:
            meta = json.loads(e.get("metadata_json") or "{}")
        except Exception:
            meta = {}
        # Invoice (pool démo) et compta_manuel avec facturable=True sont retenus
        if e.get("source_module") == "self_invoice":
            ventes.append((e, meta))
        elif meta.get("facturable") is True:
            ventes.append((e, meta))
        if len(ventes) >= limit:
            break

    if not ventes:
        return HTMLResponse(
            """
            <html><head><title>Aucune vente facturable</title>
            <style>body{font-family:system-ui;background:#0f172a;color:#e8eaed;padding:40px;max-width:700px;margin:0 auto;line-height:1.6}
            a{color:#16a34a}h1{color:#f59e0b}code{background:#1e293b;padding:2px 6px;border-radius:3px}
            .warn{background:#422006;border-left:3px solid #f59e0b;padding:10px 14px;border-radius:3px;margin:16px 0}</style></head><body>
            <h1>🗂️ Aucune vente <strong>facturable</strong> au journal</h1>
            <div class="warn">
              <strong>Rappel métier :</strong> une vente directe anonyme (marché, AMAP, livraison cash à des particuliers)
              n'est <strong>pas facturable</strong> — il n'y a pas de client identifié avec SIRET à qui adresser une facture.
              Elle reste dans le journal comptable mais ne remonte pas dans la facture Factur-X consolidée.
            </div>
            <p>Pour alimenter une facture, ajoute au moins :</p>
            <ul>
              <li><a href="/compta">/compta</a> — "💰 Ajouter une vente rapide" plusieurs fois jusqu'à tirer une vente
              <strong>B2B</strong> (Herboristerie, Biocoop, Savonnerie, Jardinerie, SARL...)</li>
              <li><a href="/invoice">/invoice</a> — génère une facture Factur-X (B2B avec SIRET client)</li>
            </ul>
            <p>Puis reviens ici : <a href="/compta/facture-du-journal">/compta/facture-du-journal</a></p>
            </body></html>
            """,
            status_code=404,
        )

    # Construction des lignes à partir des écritures
    from weasyprint import HTML

    today = date.today()
    lignes = []
    total_ht = Decimal("0")
    total_tva = Decimal("0")
    total_ttc = Decimal("0")

    # Collecte client unique si toutes les ventes sont pour le même, sinon "Clients divers"
    clients_distincts = set()

    for e, meta in ventes:
        ht = Decimal(e["montant_ht"]) if e.get("montant_ht") else Decimal(e["montant_ttc"])
        tva = Decimal(e["montant_tva"]) if e.get("montant_tva") else Decimal("0")
        ttc = Decimal(e["montant_ttc"])
        tva_pct = (tva / ht * Decimal("100")).quantize(Decimal("0.1")) if ht > 0 else Decimal("0")

        # Infos article depuis metadata (ligne de facture = produit, pas écriture)
        article_nom = meta.get("article_nom")
        article_detail = meta.get("article_detail", "")
        article_qte = meta.get("article_qte", 1)
        article_unite = meta.get("article_unite", "unité")
        article_pu_ht = Decimal(meta["article_pu_ht"]) if meta.get("article_pu_ht") else ht

        # Fallback si pas de metadata article (vieilles écritures self_invoice) :
        # on extrait depuis le libellé (avant le " — " qui sépare du client)
        if not article_nom:
            libelle = e["libelle"] or ""
            article_nom = libelle.split(" — ")[0] if " — " in libelle else libelle
            article_qte = 1
            article_unite = ""
            article_pu_ht = ht

        detail_parts = []
        if article_detail:
            detail_parts.append(article_detail)
        detail_parts.append(f"Réf. pièce {e['numero_piece']} · {e['date_operation']}")
        detail_full = " — ".join(detail_parts)

        lignes.append({
            "nom": article_nom,
            "detail": detail_full,
            "qte": f"{article_qte} {article_unite}".strip(),
            "pu_ht": article_pu_ht,
            "tva_pct": tva_pct,
            "total_ht": ht,
        })
        total_ht += ht
        total_tva += tva
        total_ttc += ttc
        client_nom = meta.get("client") or meta.get("client_nom")
        if client_nom:
            clients_distincts.add(client_nom)

    # Groupement TVA par taux
    tva_par_taux: dict[str, Decimal] = {}
    for l in lignes:
        taux = f'{l["tva_pct"]:.1f}'
        tva_par_taux.setdefault(taux, Decimal("0"))
        tva_par_taux[taux] += (l["total_ht"] * l["tva_pct"] / Decimal("100")).quantize(Decimal("0.01"))

    numero = f"FJ-{today.year}-{today.strftime('%m%d-%H%M')}"
    echeance = today + timedelta(days=30)

    data = {
        "facture": {
            "numero": numero,
            "date_emission_fr": today.strftime("%d/%m/%Y"),
            "date_prestation_fr": ventes[-1][0]["date_operation"],
            "date_echeance_fr": echeance.strftime("%d/%m/%Y"),
            "facturx_profile": "EN16931",
        },
        "regime": {
            "slug": "reel",
            "label": "Consolidation du journal compta",
            "badge": f"Journal · {len(ventes)} vente(s) consolidée(s)",
            "abattement_73b": False,
        },
        "vendeur": {
            "nom": "Marie DUPONT",
            "nom_commercial": "Herbaria Démo",
            "forme": "Entreprise individuelle",
            "activite": "PPAM bio — Maraîchage & tisanes (consolidation journal)",
            "adresse": "12 Chemin des Mésanges",
            "cp": "24000",
            "ville": "Bourg-de-Démonstration",
            "siret": "000 000 000 00000",
            "tva": "FR 00 000000000",
            "ape": "0128Z — Culture plantes à parfum",
        },
        "client": _determiner_client_facture(ventes, clients_distincts),
        "lignes": lignes,
        "totaux": {
            "total_ht": total_ht.quantize(Decimal("0.01")),
            "tva_par_taux": tva_par_taux,
            "total_tva": total_tva.quantize(Decimal("0.01")),
            "total_ttc": total_ttc.quantize(Decimal("0.01")),
        },
    }

    tmpl = templates.get_template("invoice/facture.html.j2")
    html_str = tmpl.render(**data)
    pdf_bytes = HTML(string=html_str).write_pdf()

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="facture-journal-{numero}.pdf"',
            "X-Selfagribook-Source": "journal-compta",
            "X-Selfagribook-Ventes-Consolidees": str(len(ventes)),
        },
    )


@router.post("/importer-releve")
async def compta_importer_releve(request: Request):
    _demo_only()
    """Simule l'import d'un relevé bancaire (self_banking).

    Démonstration du 3e flux du hub compta :
    1. Réconciliation auto des factures 411 non-apurées → virement reçu 512/411
    2. Prélèvements récurrents (MSA, EDF, assurance, internet, fermage) → charges/401
    3. Frais bancaires mensuels → 6271/512

    Chaque écriture a source_module=self_banking, source_id unique, et metadata
    indiquant la référence à la facture d'origine si applicable (lettrage).
    """
    if not STORAGE_OK:
        return JSONResponse({"error": "storage KO"}, status_code=503)

    today = date.today()
    numero_releve = f"BQ-{today.strftime('%Y-%m')}-01"
    n_reconciliations = 0
    n_prelevements = 0
    n_frais = 0

    # 1. Réconciliation — lettrage automatique des factures 411 non-encaissées
    # Cherche toutes les écritures 411 au débit (factures clients) sans contrepartie
    # 512 déjà existante. source_id réconciliation = "lettrage-{numero_piece}"
    ventes = list_ecritures(limit=50, compte="411")
    for e in ventes:
        if e["compte_debit"] != "411" or e["compte_credit"] != "701":
            continue
        # Check si cette facture a déjà été lettrée (écriture 512/411 avec ref)
        lettrage_source_id = f"lettrage-{e['numero_piece']}"
        if find_ecriture_by_source("self_banking", lettrage_source_id):
            continue  # Déjà lettré
        # Crée le virement reçu (client paye) : 512 Banque / 411 Clients
        save_ecriture(
            date_operation=today,
            journal="BQ",
            numero_piece=f"VIR-{e['numero_piece']}",
            libelle=f"Virement reçu — lettrage {e['numero_piece']} ({e['libelle'][:40]}…)",
            compte_debit="512",
            compte_credit="411",
            montant_ttc=Decimal(e["montant_ttc"]),
            montant_ht=Decimal(e["montant_ttc"]),  # Banking : pas de TVA
            montant_tva=Decimal("0"),
            source_module="self_banking",
            source_id=lettrage_source_id,
            metadata_json=json.dumps({
                "type": "lettrage_vente",
                "facture_piece": e["numero_piece"],
                "facture_ecriture_id": e["id"],
            }),
        )
        n_reconciliations += 1

    # 2. Prélèvements récurrents (2-3 prélèvements aléatoires)
    prelevements_sample = random.sample(PRELEVEMENTS_FIXTURES, min(3, len(PRELEVEMENTS_FIXTURES)))
    for p in prelevements_sample:
        tva = (p["montant_ht"] * p["tva_pct"] / Decimal("100")).quantize(Decimal("0.01"))
        ttc = (p["montant_ht"] + tva).quantize(Decimal("0.01"))
        source_id = f"prlv-{random.randint(100000, 999999)}"
        save_ecriture(
            date_operation=today,
            journal="BQ",
            numero_piece=f"PRLV-{today.strftime('%Y%m')}-{random.randint(10, 99)}",
            libelle=f"{p['libelle']} — {p['benef']}",
            compte_debit=p["compte_debit"],  # charge (6451 MSA, 6061 EDF, 616 assurance...)
            compte_credit="512",              # Banque
            montant_ttc=ttc,
            montant_ht=p["montant_ht"],
            montant_tva=tva,
            source_module="self_banking",
            source_id=source_id,
            metadata_json=json.dumps({"type": "prelevement_recurrent", "beneficiaire": p["benef"]}),
        )
        n_prelevements += 1

    # 3. Frais bancaires mensuels (1-2 lignes)
    frais_sample = random.sample(FRAIS_BANQUE_FIXTURES, min(2, len(FRAIS_BANQUE_FIXTURES)))
    for f in frais_sample:
        source_id = f"frais-{random.randint(100000, 999999)}"
        save_ecriture(
            date_operation=today,
            journal="BQ",
            numero_piece=f"FB-{today.strftime('%Y%m')}-{random.randint(10, 99)}",
            libelle=f["libelle"],
            compte_debit=f["compte_debit"],
            compte_credit="512",
            montant_ttc=f["montant_ht"],
            montant_ht=f["montant_ht"],
            montant_tva=Decimal("0"),
            source_module="self_banking",
            source_id=source_id,
            metadata_json=json.dumps({"type": "frais_bancaire"}),
        )
        n_frais += 1

    return _json_or_redirect(request, {
        "ok": True,
        "action": "releve_importe",
        "numero_releve": numero_releve,
        "n_reconciliations": n_reconciliations,
        "n_prelevements": n_prelevements,
        "n_frais": n_frais,
        "total_ecritures": n_reconciliations + n_prelevements + n_frais,
    })


@router.post("/reset-demo")
async def compta_reset_demo(request: Request):
    _demo_only()
    """Purge toutes les écritures — reset démo (utile si trop de monde clique)."""
    if not STORAGE_OK:
        return JSONResponse({"error": "storage KO"}, status_code=503)
    reset_demo()
    return _json_or_redirect(request, {
        "ok": True,
        "action": "reset",
        "message": "🧹 Toutes les écritures ont été purgées. Hub compta remis à zéro.",
    })


def _json_or_redirect(request: Request, payload: dict):
    """Si requête htmx (HX-Request) → JSON/HTML fragment, sinon → redirect vers /compta."""
    is_htmx = request.headers.get("HX-Request") == "true"
    if is_htmx:
        # Retour HTML fragment pour banner/flash notification
        status = "🟢" if payload.get("ok") else "🔴"
        msg = payload.get("message") or f"{payload.get('action', 'op')} → écriture #{payload.get('ecriture_id', '?')}"
        if payload.get("action") == "vente_créée":
            if payload.get("facturable"):
                msg = (
                    f"✅ Vente <strong>B2B facturable</strong> — <strong>Écriture #{payload['ecriture_id']}</strong> "
                    f"<code class='text-green-400'>411</code>/<code class='text-green-400'>701</code> — "
                    f"{payload['montant_ttc']} € — <em>{payload['libelle']}</em> "
                    f"(client : <strong>{payload['client']}</strong>) — alimentera la facture Factur-X du journal."
                )
            else:
                msg = (
                    f"ℹ️ Vente directe <strong>B2C (non-facturable)</strong> — <strong>Écriture #{payload['ecriture_id']}</strong> "
                    f"<code class='text-green-400'>411</code>/<code class='text-green-400'>701</code> — "
                    f"{payload['montant_ttc']} € — <em>{payload['libelle']}</em>. "
                    f"<strong>N'alimentera PAS</strong> la facture Factur-X (pas de client identifié)."
                )
        elif payload.get("action") == "achat_créé":
            msg = (
                f"✅ Achat enregistré — <strong>Écriture #{payload['ecriture_id']}</strong> "
                f"<code class='text-green-400'>{payload['compte_debit']}</code> Débit / "
                f"<code class='text-green-400'>{payload['compte_credit']}</code> Crédit — "
                f"{payload['montant_ttc']} € — <em>{payload['libelle']}</em>"
                f"{' (nouvelle)' if payload['created'] else ' (déjà présente)'}"
            )
        elif payload.get("action") == "dedup_active":
            msg = (
                f"♻️ <strong>Dédup appliquée</strong> — facture {payload['numero_piece']} "
                f"déjà rattachée à l'écriture #{payload['ecriture_id']}. "
                f"<strong>Aucun doublon créé</strong> (idempotence OK)."
            )
        elif payload.get("action") == "releve_importe":
            msg = (
                f"🏦 <strong>Relevé bancaire importé</strong> — {payload['total_ecritures']} "
                f"nouvelles écritures (source <code class='text-green-400'>self_banking</code>) :<br>"
                f"&nbsp;&nbsp;✅ <strong>{payload['n_reconciliations']}</strong> virement(s) reçu(s) "
                f"<em>lettrés automatiquement</em> sur factures 411 existantes (512/411)<br>"
                f"&nbsp;&nbsp;💸 <strong>{payload['n_prelevements']}</strong> prélèvement(s) récurrent(s) "
                f"(MSA/EDF/assurance/...) → charges/401<br>"
                f"&nbsp;&nbsp;🏛️ <strong>{payload['n_frais']}</strong> frais bancaire(s) → 6271/512"
                + (
                    "<br><em class='text-amber-300'>💡 Aucune facture à lettrer — ajoute des ventes B2B ou B2C d'abord pour voir la réconciliation auto.</em>"
                    if payload['n_reconciliations'] == 0 else ""
                )
            )
        elif payload.get("action") == "reset":
            msg = "🧹 <strong>Reset démo effectué</strong> — toutes les écritures purgées."
        if payload.get("action") == "vente_créée":
            color = "sky" if payload.get("facturable") else "slate"
        else:
            color = {
                "achat_créé": "emerald",
                "dedup_active": "amber",
                "créée_nouvelle": "sky",
                "reset": "rose",
                "aucune_facture": "slate",
                "releve_importe": "purple",
            }.get(payload.get("action"), "slate")
        return HTMLResponse(
            f'<div class="p-3 rounded border bg-{color}-900/30 border-{color}-700 text-{color}-200 text-sm">{status} {msg}</div>'
        )
    return RedirectResponse(url="/compta", status_code=303)
