"""`scripts/verrou_prod.sh`, que `deploy.sh` envoie à la prod après l'étape 4 : il dit
si le code est reverrouillé, et ne rend jamais un vert sur une mesure incomplète.
Un faux `lsattr`, en tête du PATH, répond selon le nom de chaque entrée."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verrou_prod.sh"

FAUX_LSATTR = """#!/usr/bin/env bash
shift
for p in "$@"; do
  b=$(basename "$p")
  case " ${ILLISIBLES:-} " in *" $b "*) echo "lsattr: refus sur $p" >&2; continue;; esac
  case " ${MODIFIABLES:-} " in *" $b "*) echo "--------------e------- $p"; continue;; esac
  echo "----i---------e------- $p"
done
"""


@pytest.fixture
def prod(tmp_path):
    """Un code de prod en miniature, avec les dossiers que le gel laisse inscriptibles."""
    racine = tmp_path / "prod"
    for chemin in ["webapp/main.py", "scripts/deploy.sh", "requirements.txt",
                   "modules/self_aid/data/aides.yaml", "data/compta.db", ".venv/bin/python"]:
        (racine / chemin).parent.mkdir(parents=True, exist_ok=True)
        (racine / chemin).write_text("")
    outils = tmp_path / "outils"
    outils.mkdir()
    (outils / "lsattr").write_text(FAUX_LSATTR)
    (outils / "lsattr").chmod(0o755)
    return racine, outils


def _mesurer(racine: Path, outils: Path, **env: str) -> subprocess.CompletedProcess:
    environ = {**os.environ, "PATH": f"{outils}:{os.environ['PATH']}", **env}
    return subprocess.run(["bash", str(SCRIPT), str(racine)], capture_output=True, text=True,
                          env=environ, check=False)


def test_tout_le_code_fige(prod):
    racine, outils = prod
    r = _mesurer(racine, outils)
    # prod, webapp, main.py, scripts, deploy.sh, requirements.txt, modules, self_aid
    assert (r.returncode, r.stdout.strip()) == (
        0, "8 entrées de code figées (hors .venv et dossiers de données)")


def test_une_entree_modifiable_fait_sortir_1_et_se_nomme(prod):
    racine, outils = prod
    r = _mesurer(racine, outils, MODIFIABLES="main.py")
    assert r.returncode == 1
    assert "1 entrée(s) de code modifiable(s) sur 8" in r.stdout
    assert "webapp/main.py" in r.stdout


def test_les_dossiers_de_donnees_ne_comptent_pas(prod):
    racine, outils = prod
    r = _mesurer(racine, outils, MODIFIABLES="aides.yaml compta.db python")
    assert r.returncode == 0, r.stdout


def test_une_entree_illisible_rend_la_mesure_impossible(prod):
    racine, outils = prod
    r = _mesurer(racine, outils, ILLISIBLES="deploy.sh")
    assert r.returncode == 2
    assert "7 attribut(s) lu(s) pour 8 entrée(s)" in r.stdout


def test_une_racine_absente_rend_la_mesure_impossible(prod):
    racine, outils = prod
    r = _mesurer(racine / "absente", outils)
    assert r.returncode == 2


@pytest.mark.parametrize("illisible", ["", "deploy.sh"])
def test_un_nom_a_retour_a_la_ligne_rend_la_mesure_impossible(prod, illisible):
    """Le faux vert des deux relectures : la seconde ligne d'un nom forgé imite un
    attribut figé et compense la ligne qu'une entrée illisible n'a pas rendue."""
    racine, outils = prod
    (racine / "webapp" / "x\n----i---------e------- y.py").write_text("")
    r = _mesurer(racine, outils, ILLISIBLES=illisible)
    assert r.returncode == 2
    assert "caractère de contrôle" in r.stdout


def test_un_dossier_que_find_ne_lit_pas_rend_la_mesure_impossible(prod):
    racine, outils = prod
    cache = racine / "webapp" / "prive"
    cache.mkdir()
    (cache / "module.py").write_text("")
    cache.chmod(0o000)
    try:
        r = _mesurer(racine, outils)
    finally:
        cache.chmod(0o755)
    assert r.returncode == 2


def test_un_lien_symbolique_dans_le_code_fait_sortir_1(prod, tmp_path):
    racine, outils = prod
    ailleurs = tmp_path / "ailleurs.py"
    ailleurs.write_text("")
    (racine / "webapp" / "lien.py").symlink_to(ailleurs)
    r = _mesurer(racine, outils)
    assert r.returncode == 1
    assert "lien(s) symbolique(s)" in r.stdout
    assert "webapp/lien.py" in r.stdout
