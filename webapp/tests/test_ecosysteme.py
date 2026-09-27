"""
scripts/ecosysteme.py — le contrôle rougit-il sur les dérives qu'il prétend attraper ?

Chaque test travaille sur une copie réduite du dépôt (déclarations, catalogue, README, et un
`__init__.py` vide par paquet) : planter un défaut ne touche jamais l'arbre réel. Le manifeste de
my-self est un fichier local lu en `file://` — aucun accès réseau.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location("ecosysteme", RACINE / "scripts" / "ecosysteme.py")
eco = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eco)


@pytest.fixture
def depot(tmp_path: Path) -> Path:
    for nom in ("modules.toml", "modules.json", "README.md", "VERSION", "webapp/modules_catalog.py"):
        (tmp_path / nom).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(RACINE / nom, tmp_path / nom)
    for paquet in (RACINE / "modules").glob("self_*/__init__.py"):
        (tmp_path / "modules" / paquet.parent.name).mkdir(parents=True)
        (tmp_path / "modules" / paquet.parent.name / "__init__.py").touch()
    (tmp_path / "webapp" / "routes").mkdir()
    (tmp_path / "webapp" / "routes" / "invoice.py").touch()
    return tmp_path


def test_copie_du_depot_verte(depot):
    assert eco.main(["manifeste"], racine=depot) == 0


def test_paquet_non_declare_rougit(depot):
    (depot / "modules" / "self_canari").mkdir()
    (depot / "modules" / "self_canari" / "__init__.py").touch()
    assert eco.main(["manifeste"], racine=depot) == 1


def test_dossier_declare_absent_rougit(depot):
    (depot / "webapp" / "routes" / "invoice.py").unlink()
    assert eco.main(["manifeste"], racine=depot) == 1


def test_tableau_readme_retouche_a_la_main_rougit_puis_se_repare(depot):
    readme = depot / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8").replace("| disponible |", "| ✅ live |", 1),
                      encoding="utf-8")
    assert eco.main(["manifeste"], racine=depot) == 1
    assert eco.main(["manifeste", "--ecrire"], racine=depot) == 0
    assert eco.main(["manifeste"], racine=depot) == 0


def test_statut_change_au_catalogue_rougit(depot):
    catalogue = depot / "webapp" / "modules_catalog.py"
    texte = catalogue.read_text(encoding="utf-8")
    catalogue.write_text(texte.replace('"banking", "Banque & rapprochement", "gestion", "bank", "soon"',
                                       '"banking", "Banque & rapprochement", "gestion", "bank", "live"'),
                         encoding="utf-8")
    assert catalogue.read_text(encoding="utf-8") != texte
    assert eco.main(["manifeste"], racine=depot) == 1


def test_bloc_readme_absent_rend_2(depot):
    readme = depot / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8").replace("<!-- modules:fin -->", ""),
                      encoding="utf-8")
    assert eco.main(["manifeste"], racine=depot) == 2


@pytest.fixture
def myself(depot, monkeypatch) -> Path:
    """Un modules.json de my-self local, qui déclare les modules cités par notre README."""
    ids = eco._declarations(depot)["ecosysteme"]["modules"]
    fichier = depot / "myself-modules.json"
    fichier.write_text(json.dumps({"depot": {"nom": "my-self", "version": None}, "modules": [
        {"id": i, "nom": i.capitalize(), "version": "1.0.0", "resume": {"fr": f"résumé {i}", "en": i}}
        for i in ids
    ]}), encoding="utf-8")
    monkeypatch.setenv("MYSELF_MODULES_URL", fichier.as_uri())
    assert eco.main(["ecosysteme", "--ecrire"], racine=depot) == 0
    return fichier


def _modifier(fichier: Path, changer) -> None:
    donnees = json.loads(fichier.read_text(encoding="utf-8"))
    changer(donnees["modules"])
    fichier.write_text(json.dumps(donnees), encoding="utf-8")


def test_ecosysteme_a_jour_vert(depot, myself):
    assert eco.main(["ecosysteme"], racine=depot) == 0


def test_version_publiee_par_myself_rougit(depot, myself):
    _modifier(myself, lambda modules: modules[0].update(version="1.0.1"))
    assert eco.main(["ecosysteme"], racine=depot) == 1


def test_module_retire_par_myself_rougit(depot, myself):
    _modifier(myself, lambda modules: modules.pop())
    assert eco.main(["ecosysteme"], racine=depot) == 1


def test_manifeste_myself_introuvable_rend_2(depot, myself, monkeypatch):
    monkeypatch.setenv("MYSELF_MODULES_URL", (depot / "absent.json").as_uri())
    assert eco.main(["ecosysteme"], racine=depot) == 2


def test_manifeste_myself_mal_forme_rend_2(depot, myself):
    myself.write_text("{ pas du json", encoding="utf-8")
    assert eco.main(["ecosysteme"], racine=depot) == 2
