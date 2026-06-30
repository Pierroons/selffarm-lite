"""Tests du schéma d'intake guidé (intake_schema.yaml) du module dnja.

Vérifie que le schéma est bien formé, couvre les sections attendues, et respecte
les principes de neutralité MySelf (zéro marque/produit nommé).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

SCHEMA_PATH = Path(__file__).parent.parent / "intake_schema.yaml"


@pytest.fixture(scope="module")
def schema() -> dict:
    return yaml.safe_load(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_schema_se_charge_et_cles_top_level(schema):
    for cle in ("version", "garde_fou", "referentiels", "sections",
                "llm_rules", "checklists_completude", "sortie"):
        assert cle in schema, f"Clé top-level manquante : {cle}"


def test_sections_attendues_et_bien_formees(schema):
    ids = [s["id"] for s in schema["sections"]]
    for attendu in ("profil", "productions", "charges", "investissements",
                    "aides", "social", "financement", "accompagnement"):
        assert attendu in ids, f"Section manquante : {attendu}"
    # Chaque section a un id, un titre et des champs.
    for s in schema["sections"]:
        assert s.get("id") and s.get("titre") and s.get("champs")


def test_garde_fou_plancher_2000(schema):
    assert schema["garde_fou"]["plancher_marge_ebe_uth"] == 2000


def test_referentiels_indispensables(schema):
    r = schema["referentiels"]
    assert r["seuil_ebe_uth_dnja_na_2026"] == 17717
    assert r["dnja_decoupage_national"]["acompte_pct"] == 80
    assert "faconnage_cbd_indicatif" in r
    assert len(r["msa_exoneration_ja_pct"]) >= 4


def test_checklists_completude_par_profil(schema):
    cl = schema["checklists_completude"]
    for profil in ("maraichage", "chanvre_cbd", "elevage", "arboriculture"):
        assert profil in cl and len(cl[profil]) >= 5


def test_neutralite_zero_marque(schema):
    """Principe MySelf : aucune marque/produit nommé dans un livrable user-facing."""
    blob = json.dumps(schema, ensure_ascii=False).lower()
    for marque in ("green exchange", "crédit agricole", "credit agricole",
                   "ecocert", "genscore", "kompolti"):
        assert marque not in blob, f"Fuite de marque dans le schéma : {marque}"
