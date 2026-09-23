"""Tests de l'écran de validation des factures fournisseurs."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from self_pa import storage
from self_pa.imputation import analyser
from self_pa.models import CanalReception, FactureRecue, PartieFacture


@pytest.fixture
def client(tmp_path, monkeypatch):
    """App réelle sur une base neuve à chaque test.

    `SELFFARM_COMPTA_DB` est relu à chaque accès (contrairement à
    `SELFFARM_DATA_DIR`, figé à l'import — cf. conftest.py), donc l'isolation
    par test fonctionne ici. Mais une base neuve n'a pas de profil
    d'exploitation, et un middleware renvoie alors tout vers le wizard
    d'onboarding avec un 200 trompeur : il faut le recréer dans CETTE base.
    """
    monkeypatch.setenv("SELFFARM_COMPTA_DB", str(tmp_path / "test_compta.db"))
    from self_agri_book.exploitation import (
        is_onboarding_done,
        mark_onboarding_done,
        save_exploitation,
    )

    if not is_onboarding_done():
        save_exploitation({
            "nom": "Ferme de test",
            "statut": "JA",
            "commune": "Sainte-Foy",
            "saison_courante": 2026,
        })
        mark_onboarding_done()

    from webapp.main import app

    with TestClient(app) as c:
        yield c


def deposer(numero="FA-2026-0142", ttc="1200.00", hash_pdf="a" * 64) -> str:
    f = FactureRecue(
        numero=numero,
        date_facture=date(2026, 9, 3),
        emetteur=PartieFacture(nom="Outillage Pro Distribution", siren="552100554"),
        total_ht=Decimal("1000.00"),
        total_tva=Decimal("200.00"),
        total_ttc=Decimal(ttc),
    )
    cle, _ = storage.enregistrer(
        f, analyser(f), canal=CanalReception.PLATEFORME,
        provider_invoice_id=1, hash_fichier=hash_pdf,
    )
    return cle


# ---------------- affichage ----------------

def test_page_vide_repond_200(client):
    r = client.get("/achats")

    assert r.status_code == 200
    assert "Aucune facture en attente" in r.text


def test_facture_en_attente_est_affichee(client):
    deposer()
    r = client.get("/achats")

    assert r.status_code == 200
    assert "Outillage Pro Distribution" in r.text
    assert "FA-2026-0142" in r.text
    assert "1200.00" in r.text


def test_le_choix_de_compte_vient_du_plan_comptable(client):
    """Les comptes proposés sortent du PCG agricole du dépôt, pas d'une liste
    recopiée dans le template."""
    deposer()
    r = client.get("/achats")

    assert "6063" in r.text
    assert "Fournitures d&#39;entretien et de petit équipement" in r.text or \
           "Fournitures d'entretien et de petit équipement" in r.text
    # Aucun compte présélectionné : le choix est explicite.
    assert "— à choisir —" in r.text


def test_facture_bloquee_affiche_son_anomalie(client):
    deposer(ttc="9999.00")
    r = client.get("/achats")

    assert "À vérifier" in r.text
    assert "HT + TVA ≠ TTC" in r.text


# ---------------- validation ----------------

def test_valider_cree_lecriture_et_redirige(client):
    from self_agri_book.storage import _conn

    cle = deposer()
    r = client.post(
        "/achats/valider",
        data={"cle_metier": cle, "compte_charge": "6063"},
        follow_redirects=False,
    )

    assert r.status_code == 303
    with _conn() as c:
        ligne = c.execute("SELECT * FROM ecritures_comptables").fetchone()
    assert ligne["compte_debit"] == "6063"
    assert ligne["compte_credit"] == "401"
    assert ligne["journal"] == "ACH"
    assert storage.obtenir(cle)["statut"] == "validee"


def test_un_compte_hors_classe_6_est_refuse(client):
    """Le compte vient d'un formulaire : rien ne garantit que c'est une charge.
    Imputer un achat sur un 411 fausserait le bilan sans rien casser de visible."""
    from self_agri_book.storage import _conn

    cle = deposer()
    r = client.post(
        "/achats/valider",
        data={"cle_metier": cle, "compte_charge": "411"},
        follow_redirects=True,
    )

    assert "n&#39;est pas un compte de charge" in r.text or \
           "n'est pas un compte de charge" in r.text
    with _conn() as c:
        n = c.execute("SELECT count(*) AS n FROM ecritures_comptables").fetchone()["n"]
    assert n == 0
    assert storage.obtenir(cle)["statut"] == "proposee"


def test_double_validation_ne_cree_quune_ecriture(client):
    """Le rafraîchissement du navigateur, version réelle du double clic."""
    from self_agri_book.storage import _conn

    cle = deposer()
    donnees = {"cle_metier": cle, "compte_charge": "6063"}
    client.post("/achats/valider", data=donnees, follow_redirects=True)
    r = client.post("/achats/valider", data=donnees, follow_redirects=True)

    assert "déjà comptabilisée" in r.text
    with _conn() as c:
        n = c.execute("SELECT count(*) AS n FROM ecritures_comptables").fetchone()["n"]
    assert n == 1


def test_valider_une_facture_bloquee_est_refuse(client):
    from self_agri_book.storage import _conn

    cle = deposer(ttc="9999.00")
    client.post(
        "/achats/valider",
        data={"cle_metier": cle, "compte_charge": "6063"},
        follow_redirects=True,
    )

    with _conn() as c:
        n = c.execute("SELECT count(*) AS n FROM ecritures_comptables").fetchone()["n"]
    assert n == 0


# ---------------- écarter ----------------

def test_ecarter_conserve_la_facture(client):
    cle = deposer()
    r = client.post(
        "/achats/ecarter",
        data={"cle_metier": cle, "motif": "Déjà réglée en direct"},
        follow_redirects=True,
    )

    assert r.status_code == 200
    stockee = storage.obtenir(cle)
    assert stockee["statut"] == "ecartee"
    assert "Déjà réglée en direct" in stockee["anomalies_json"]


def test_ecarter_puis_valider_est_possible(client):
    """Écarter n'est pas définitif : une facture écartée par erreur se rattrape."""
    cle = deposer()
    client.post("/achats/ecarter", data={"cle_metier": cle, "motif": ""},
                follow_redirects=True)
    client.post("/achats/valider", data={"cle_metier": cle, "compte_charge": "6063"},
                follow_redirects=True)

    assert storage.obtenir(cle)["statut"] == "validee"


# ---------------- récupération ----------------

def test_sans_identifiants_le_message_ne_parle_pas_de_panne(client, monkeypatch):
    """Sans identifiants la plateforme n'est pas appelée : « injoignable » ferait
    chercher une panne réseau là où il manque une ligne dans le .env."""
    monkeypatch.delenv("SUPERPDP_CLIENT_ID", raising=False)
    monkeypatch.delenv("SUPERPDP_CLIENT_SECRET", raising=False)
    r = client.post("/achats/recuperer", follow_redirects=True)

    assert "Plateforme non configurée" in r.text
    assert "injoignable" not in r.text
