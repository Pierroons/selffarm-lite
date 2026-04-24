"""Tests smoke pour les routes webapp SelfFarm-Lite."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Setup PYTHONPATH
BASE = Path(__file__).parent.parent.parent
sys.path.insert(0, str(BASE / "modules"))
sys.path.insert(0, str(BASE))

from webapp.main import app  # noqa: E402


@pytest.fixture
def client():
    return TestClient(app)


# ---------- Home ----------

def test_home_200(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "SelfFarm-Lite" in r.text
    assert "Tableau de bord" in r.text


def test_home_mentions_aides_count(client):
    r = client.get("/")
    # Doit afficher le compteur d'aides dans la tuile
    assert "aides agricoles 2026" in r.text


# ---------- DNJA ----------

def test_dnja_index_200(client):
    r = client.get("/dnja")
    assert r.status_code == 200
    assert "Simulateur DNJA" in r.text
    assert "Scénarios disponibles" in r.text


def test_dnja_index_contient_scenarios(client):
    r = client.get("/dnja")
    assert "CHAMBRE" in r.text or "chambre" in r.text.lower()
    assert "PERSO" in r.text or "perso" in r.text.lower()


def test_dnja_calcul_chambre(client):
    r = client.get("/dnja/calcul?example=hypotheses-pierroons-chambre")
    assert r.status_code == 200
    assert "EBE/UTH" in r.text
    assert "Télécharger PDF" in r.text
    # Contient un résultat chiffré
    assert "€" in r.text


def test_dnja_calcul_scenario_inconnu_404(client):
    r = client.get("/dnja/calcul?example=inexistant")
    assert r.status_code == 404


def test_dnja_pdf(client):
    r = client.get("/dnja/pdf?example=hypotheses-pierroons-chambre")
    assert r.status_code == 200
    assert r.headers.get("content-type") == "application/pdf"
    assert len(r.content) > 10000  # PDF non vide


def test_dnja_compare_index(client):
    r = client.get("/dnja/compare")
    assert r.status_code == 200
    assert "Comparaison de scénarios" in r.text


def test_dnja_compare_run(client):
    r = client.get(
        "/dnja/compare/run",
        params={"a": "hypotheses-pierroons-chambre", "b": "hypotheses-pierroons-perso"},
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
        params={"slug": "hypotheses-pierroons-chambre"},
    )
    assert r.status_code == 200
    assert "Activités" in r.text


# ---------- Aides ----------

def test_aides_index_200(client):
    r = client.get("/aides")
    assert r.status_code == 200
    assert "Catalogue d'aides" in r.text or "aides agricoles 2026" in r.text


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
    assert "Parcellaire IGN" in r.text


def test_parcelles_carto(client):
    r = client.get("/parcelles/carto")
    assert r.status_code == 200
    assert "Leaflet" in r.text or "leaflet" in r.text.lower()
