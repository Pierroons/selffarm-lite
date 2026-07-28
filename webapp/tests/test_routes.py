"""Tests smoke des routes webapp SelfFarm-Lite.

La fixture `client`, l'isolation de la base et l'onboarding sont dans
conftest.py. Ces tests s'appuient sur le seul scénario d'exemple versionné :
les scénarios nominatifs ne sortent pas du poste de leur auteur.
"""

from __future__ import annotations

from webapp.tests.conftest import SCENARIO_DEMO

# ---------- Home ----------

def test_home_200(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "SelfFarm-Lite" in r.text
    assert "Tableau de bord" in r.text


def test_home_mentions_aides_count(client):
    """Le tableau de bord expose le compteur d'aides éligibles."""
    r = client.get("/")
    assert "aides éligibles" in r.text


# ---------- DNJA ----------

def test_dnja_index_200(client):
    r = client.get("/dnja")
    assert r.status_code == 200
    assert "SelfDNJA" in r.text
    assert "Simulateur prévisionnel" in r.text


def test_dnja_index_contient_scenarios(client):
    """Le scénario public est listé — les nominatifs sont filtrés hors machine perso."""
    r = client.get("/dnja")
    assert "Démo publique" in r.text or SCENARIO_DEMO in r.text


def test_dnja_calcul_chambre(client):
    r = client.get(f"/dnja/calcul?example={SCENARIO_DEMO}")
    assert r.status_code == 200
    assert "EBE/UTH" in r.text
    assert "Télécharger PDF" in r.text
    # Contient un résultat chiffré
    assert "€" in r.text


def test_dnja_calcul_scenario_inconnu_404(client):
    r = client.get("/dnja/calcul?example=inexistant")
    assert r.status_code == 404


def test_dnja_pdf(client):
    r = client.get(f"/dnja/pdf?example={SCENARIO_DEMO}")
    assert r.status_code == 200
    assert r.headers.get("content-type") == "application/pdf"
    assert len(r.content) > 10000  # PDF non vide


def test_dnja_compare_index(client):
    r = client.get("/dnja/compare")
    assert r.status_code == 200
    assert "Comparaison de scénarios" in r.text


def test_dnja_compare_run(client):
    """Smoke test du rendu comparatif — un seul scénario versionné, comparé à lui-même."""
    r = client.get(
        "/dnja/compare/run",
        params={"a": SCENARIO_DEMO, "b": SCENARIO_DEMO},
    )
    assert r.status_code == 200
    assert "Scénario A" in r.text
    assert "Scénario B" in r.text


def test_dnja_editor_index(client):
    r = client.get("/dnja/editor")
    assert r.status_code == 200
    assert "Éditeur" in r.text


def test_dnja_editor_load(client):
    r = client.get(
        "/dnja/editor/load",
        params={"slug": SCENARIO_DEMO},
    )
    assert r.status_code == 200
    assert "Activités" in r.text


# ---------- Aides ----------

def test_aides_index_200(client):
    r = client.get("/aides")
    assert r.status_code == 200
    assert "Catalogue des aides" in r.text


def test_aides_filter_mot_cle(client):
    r = client.get("/aides/filter?mot_cle=chanvre")
    assert r.status_code == 200
    # Au moins aide couplée chanvre matche
    assert "chanvre" in r.text.lower()


def test_aides_filter_statut(client):
    r = client.get("/aides/filter?statut=ja-installation")
    assert r.status_code == 200
    assert "aide(s) trouvée" in r.text


def test_aides_detail_dnja(client):
    r = client.get("/aides/dnja-2026")
    assert r.status_code == 200
    assert "Dotation" in r.text


def test_aides_detail_inconnu_404(client):
    r = client.get("/aides/aide-qui-nexiste-pas")
    assert r.status_code == 404


# ---------- Parcelles ----------

def test_parcelles_index(client):
    r = client.get("/parcelles")
    assert r.status_code == 200
    assert "Tes parcelles" in r.text


def test_parcelles_carto(client):
    r = client.get("/parcelles/carto")
    assert r.status_code == 200
    assert "Carte parcellaire IGN" in r.text
