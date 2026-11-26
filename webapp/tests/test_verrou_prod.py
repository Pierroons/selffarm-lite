"""`scripts/verrou_prod.sh`, que `deploy.sh` envoie à la prod après l'étape 4 : il dit
si le code est reverrouillé, et ne rend jamais un vert sur une mesure incomplète.
Un faux `lsattr`, en tête du PATH, répond selon le nom de chaque entrée."""

from __future__ import annotations

import os
import re
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
    # prod, webapp, main.py, scripts, deploy.sh, requirements.txt, modules, self_aid,
    # puis .venv, .venv/bin et .venv/bin/python : un venv est du code, il est compté
    # depuis le 24/11/2026.
    assert (r.returncode, r.stdout.strip()) == (
        0, "11 entrées de code figées (hors dossiers de données)")


def test_une_entree_modifiable_fait_sortir_1_et_se_nomme(prod):
    racine, outils = prod
    r = _mesurer(racine, outils, MODIFIABLES="main.py")
    assert r.returncode == 1
    assert "1 entrée(s) de code modifiable(s) sur 11" in r.stdout
    assert "webapp/main.py" in r.stdout


def test_les_dossiers_de_donnees_ne_comptent_pas(prod):
    racine, outils = prod
    r = _mesurer(racine, outils, MODIFIABLES="aides.yaml compta.db")
    assert r.returncode == 0, r.stdout


def test_une_entree_du_venv_non_figee_fait_sortir_1(prod):
    """Le venv est du code : une seule de ses entrées modifiable suffit à rougir.
    C'était le trou exact d'avant le 24/11 — il n'était pas mesuré du tout."""
    racine, outils = prod
    r = _mesurer(racine, outils, MODIFIABLES="python")
    assert r.returncode == 1
    assert ".venv/bin/python" in r.stdout


def test_un_dossier_data_sous_le_venv_reste_exclu(prod):
    """Le script est le miroir du gel : prod-immutable.sh élague « data » à toute
    profondeur, venv compris. Compter ce qu'il n'a pas figé rendrait un rouge
    permanent et faux — mesuré sur la prod, un paquet y range ses licences."""
    racine, outils = prod
    licences = racine / ".venv" / "lib" / "paquet.dist-info" / "licenses" / "data"
    licences.mkdir(parents=True)
    (licences / "LICENSE.txt").write_text("")
    r = _mesurer(racine, outils, MODIFIABLES="LICENSE.txt")
    assert r.returncode == 0, r.stdout
    # lib et paquet.dist-info et licenses comptent, pas ce qu'il y a sous data/
    assert "14 entrées de code figées" in r.stdout


def test_une_entree_illisible_rend_la_mesure_impossible(prod):
    racine, outils = prod
    r = _mesurer(racine, outils, ILLISIBLES="deploy.sh")
    assert r.returncode == 2
    assert "10 attribut(s) lu(s) pour 11 entrée(s)" in r.stdout


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


def test_un_lien_dans_un_dossier_MODIFIABLE_fait_sortir_1(prod, tmp_path):
    """Un lien ne porte pas d'attribut : il ne se fige pas. Dans un dossier qu'on
    peut encore écrire, il se remplace — donc ce qui est servi change."""
    racine, outils = prod
    ailleurs = tmp_path / "ailleurs.py"
    ailleurs.write_text("")
    (racine / "webapp" / "lien.py").symlink_to(ailleurs)
    r = _mesurer(racine, outils, MODIFIABLES="webapp")
    assert r.returncode == 1
    assert "lien(s) symbolique(s) que le gel ne protège pas" in r.stdout
    assert "webapp/lien.py" in r.stdout


def test_un_lien_vers_une_cible_FIGEE_est_tenu_pour_sur(prod, tmp_path):
    """Sans quoi le script rendrait 1 à chaque déploiement : un venv Python pose
    quatre liens vers son interpréteur. Un dossier figé n'accepte ni création ni
    suppression d'entrée, le lien ne peut donc pas y être remplacé ; et sa cible
    étant figée, elle ne peut pas être réécrite. C'est le cas du lien `lib64`,
    mesuré sur la cible le 25/11/2026."""
    racine, outils = prod
    ailleurs = tmp_path / "python3.13"
    ailleurs.write_text("")
    (racine / ".venv" / "bin" / "python3").symlink_to(ailleurs)
    r = _mesurer(racine, outils)
    assert r.returncode == 0, r.stdout


def test_un_lien_vers_une_cible_REECRIVABLE_fait_sortir_1(prod, tmp_path):
    """Le trou que la relecture du 25/11/2026 a trouvé, et que ce banc scellait.

    Le gel protège le lien, jamais ce qu'il désigne. Un lien posé pendant la
    fenêtre d'un déploiement, pointant vers un dossier de données, donne du code
    exécuté et réécrivable à volonté — et l'ancienne règle le comptait « figé »
    parce que son dossier parent l'était. Parent figé ne suffit pas.
    """
    racine, outils = prod
    cible = racine / "data" / "charge_utile.py"      # dans un dossier élagué du gel
    cible.write_text("")
    (racine / "webapp" / "greffon.py").symlink_to(cible)
    r = _mesurer(racine, outils, MODIFIABLES="charge_utile.py")
    assert r.returncode == 1, r.stdout
    assert "cible réécrivable" in r.stdout
    assert "webapp/greffon.py" in r.stdout


def test_un_lien_vers_une_cible_ABSENTE_fait_sortir_1(prod):
    """Une cible absente aujourd'hui est une cible que le compte de service crée
    demain, dans un dossier que le gel ne couvre pas."""
    racine, outils = prod
    (racine / "webapp" / "casse.py").symlink_to(racine / "data" / "jamais-ecrit.py")
    r = _mesurer(racine, outils)
    assert r.returncode == 1, r.stdout
    assert "cible absente" in r.stdout


def test_sans_argument_la_mesure_est_impossible(prod):
    """Le code 1 dit « au moins une entrée modifiable » : son lecteur affiche alors
    « PROD NON REVERROUILLÉE ». Une erreur d'appel n'est pas un défaut de gel."""
    _, outils = prod                  # l'arbre importe peu : le script n'y arrive pas
    environ = {**os.environ, "PATH": f"{outils}:{os.environ['PATH']}"}
    for args in ([], [""]):
        r = subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True,
                           env=environ, check=False)
        assert r.returncode == 2, f"args={args!r} → {r.returncode} : {r.stdout}{r.stderr}"
        assert "mesure impossible" in r.stdout


def test_la_liste_des_dossiers_elagues_est_celle_du_gel():
    """Un nom ajouté à EXCLUS aveugle la mesure en silence, et tous les tests
    restent verts : ils ne mesurent que ce qu'ils ont planté. La liste se déclare
    donc ici, et elle doit rester le miroir de celle du script d'immutabilité de
    la machine — qui, lui, n'est pas dans ce dépôt. Un ajout fait rougir, et c'est
    voulu : il se justifie des deux côtés ou pas du tout.
    """
    attendus = {"data", "uploads", "logs", "cache", "tmp", "sessions", "node_modules"}
    source = SCRIPT.read_text(encoding="utf-8")   # le script seul : pas d'arbre à monter
    debut = source.index("EXCLUS=(")
    bloc = source[debut:source.index(")", source.index("-prune", debut))]
    trouves = set(re.findall(r"-name (\S+)", bloc))
    assert trouves == attendus, (
        f"la liste élaguée a changé : en trop {trouves - attendus}, "
        f"manquants {attendus - trouves}. Le script de la machine dit-il la même chose ?")
