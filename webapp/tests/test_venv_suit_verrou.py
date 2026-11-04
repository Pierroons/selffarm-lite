"""`scripts/venv_suit_verrou.py`, que `deploy.sh` lance sur le venv de prod :
il retire ce que le verrou ne nomme pas et refuse un venv qui en diffère.
Les cas de bout en bout tournent dans un vrai venv, hors ligne, où des paquets
factices sont posés à la main : c'est `pip uninstall` qui les retire, comme en
prod."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
SCRIPT = RACINE / "scripts" / "venv_suit_verrou.py"

_spec = importlib.util.spec_from_file_location("venv_suit_verrou", SCRIPT)
vsv = importlib.util.module_from_spec(_spec)
# @dataclass lit le module de sa classe dans sys.modules.
sys.modules[_spec.name] = vsv
_spec.loader.exec_module(vsv)


def test_normalisation_pep503():
    assert vsv.normaliser("pdfminer.six") == "pdfminer-six"
    assert vsv.normaliser("Python_Dateutil") == "python-dateutil"
    assert vsv.normaliser("attendu ") == "attendu"


@pytest.mark.parametrize("nom", ["requirements.txt", "requirements-dev.txt"])
def test_le_verrou_du_depot_se_lit_en_entier(nom):
    texte = (RACINE / nom).read_text(encoding="utf-8")
    attendus = [ligne for ligne in texte.splitlines() if "==" in ligne and not ligne.startswith("#")]
    assert len(vsv.lire_verrou(texte)) == len(attendus) > 0


def test_le_projet_du_depot_se_lit():
    assert vsv.lire_projet(RACINE / "pyproject.toml") == "selffarm-lite"


@pytest.mark.parametrize("texte", [
    "pillow>=13",
    "-e .",
    "brotli==1.2.1 ; python_version < '3.14'",
    "",
    "#    pip-compile --allow-unsafe\n\n",
    "attendu==1.0\nAttendu==2.0",
])
def test_un_verrou_hors_format_vide_ou_double_est_refuse(texte):
    with pytest.raises(ValueError):
        vsv.lire_verrou(texte)


def test_ecarts_nomme_chaque_difference():
    verrou = {"attendu": "2.0", "manquant": "1.0"}
    porte = {"attendu": "1.9", "orphelin": "0.1", "projet": "0.4"}
    assert vsv.ecarts(verrou, porte, {"projet"}) == [
        "absent : manquant==1.0",
        "version : attendu 1.9 au lieu de 2.0",
        "hors verrou : orphelin==0.1",
    ]


# --- De bout en bout, dans un vrai venv -------------------------------------

PROJET = "projet-local"
FACTICES = ("attendu", "en-trop", "a-sans-record", PROJET, "autre-editable", "-rcible.txt")
SOURCES_PTH = "zz_sources_du_projet.pth"
EDITABLE = {"direct_url.json": '{"url": "file:///opt/projet", "dir_info": {"editable": true}}'}


@pytest.fixture(scope="module")
def venv(tmp_path_factory):
    racine = tmp_path_factory.mktemp("venv")
    subprocess.run([sys.executable, "-m", "venv", str(racine)], check=True)
    python = racine / "bin" / "python"
    purelib = subprocess.run(
        [str(python), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return python, Path(purelib)


def _poser(purelib: Path, nom: str, version: str, *, record: bool = True,
           prefixe: str = "", **fichiers: str) -> Path:
    """Un paquet installé tel que pip le laisse, chaque fichier inscrit au RECORD.
    Rend son METADATA : c'est par lui que pip et importlib le voient installé."""
    module = nom.replace("-", "_")
    info = purelib / f"{prefixe}{module}-{version}.dist-info"
    info.mkdir()
    (purelib / f"{module}.py").write_text("")
    contenu = {
        "METADATA": f"Metadata-Version: 2.1\nName: {nom}\nVersion: {version}\n",
        "INSTALLER": "pip\n",
        **fichiers,
    }
    for fichier, texte in contenu.items():
        (info / fichier).write_text(texte)
    if record:
        chemins = [f"{module}.py", *(f"{info.name}/{f}" for f in [*contenu, "RECORD"])]
        (info / "RECORD").write_text("".join(f"{chemin},,\n" for chemin in chemins))
    return info / "METADATA"


@pytest.fixture
def site(venv):
    """Le venv du module, vidé des paquets factices, avec le projet installé."""
    python, purelib = venv
    for nom in FACTICES:
        module = nom.replace("-", "_")
        for info in [*purelib.glob(f"{module}-*.dist-info"), *purelib.glob(f"~{module}-*.dist-info")]:
            shutil.rmtree(info)
        (purelib / f"{module}.py").unlink(missing_ok=True)
    (purelib / SOURCES_PTH).unlink(missing_ok=True)
    _poser(purelib, PROJET, "0.4.12")
    return python, purelib


def _verrou(dossier: Path, texte: str) -> Path:
    """Un verrou et, à côté, le pyproject.toml qui nomme le projet."""
    (dossier / "pyproject.toml").write_text(f'[project]\nname = "{PROJET}"\n')
    verrou = dossier / "requirements.txt"
    verrou.write_text(texte)
    return verrou


def _lancer(python: Path, verrou: Path, *options: str) -> subprocess.CompletedProcess:
    """Lancé depuis le dossier du verrou : pip y lirait un `-r<fichier>` relatif."""
    return subprocess.run([str(python), str(SCRIPT), str(verrou), *options],
                          capture_output=True, text=True, check=False, cwd=verrou.parent)


def _version_de_pip(python: Path) -> str:
    return subprocess.run(
        [str(python), "-c", "from importlib.metadata import version; print(version('pip'))"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def test_le_paquet_hors_verrou_est_desinstalle(site, tmp_path):
    python, purelib = site
    _poser(purelib, "attendu", "2.0")
    trop = _poser(purelib, "en-trop", "1.0")

    r = _lancer(python, _verrou(tmp_path, "attendu==2.0\n    # via selffarm-lite\n"))

    assert r.returncode == 0, r.stderr
    assert "désinstallés : en-trop\n" in r.stdout
    assert not trop.exists()
    assert not (purelib / "en_trop.py").exists()


def test_le_projet_installe_sans_mode_editable_reste(site, tmp_path):
    python, purelib = site
    _poser(purelib, "attendu", "2.0")

    r = _lancer(python, _verrou(tmp_path, "attendu==2.0\n"))

    assert r.returncode == 0, r.stderr
    assert (purelib / "projet_local-0.4.12.dist-info" / "METADATA").exists()


def test_un_projet_absent_fait_refuser_avant_tout_retrait(site, tmp_path):
    python, purelib = site
    shutil.rmtree(purelib / "projet_local-0.4.12.dist-info")
    _poser(purelib, "attendu", "2.0")
    trop = _poser(purelib, "en-trop", "1.0")

    r = _lancer(python, _verrou(tmp_path, "attendu==2.0\n"))

    assert r.returncode == 1
    assert "absent : projet-local (le projet lui-même)" in r.stderr
    assert trop.exists()


@pytest.mark.parametrize("texte", ["", "#    pip-compile --allow-unsafe\n"])
def test_un_verrou_vide_ne_desinstalle_rien(site, tmp_path, texte):
    python, purelib = site
    _poser(purelib, "attendu", "2.0")

    r = _lancer(python, _verrou(tmp_path, texte))

    assert r.returncode == 1
    assert "verrou vide" in r.stderr
    assert (purelib / "attendu-2.0.dist-info" / "METADATA").exists()


def test_une_version_differente_fait_refuser_avant_tout_retrait(site, tmp_path):
    python, purelib = site
    _poser(purelib, "attendu", "1.0")
    trop = _poser(purelib, "en-trop", "1.0")

    r = _lancer(python, _verrou(tmp_path, "attendu==2.0\n"))

    assert r.returncode == 1
    assert "rien n'est désinstallé" in r.stderr
    assert "version : attendu 1.0 au lieu de 2.0" in r.stderr
    assert trop.exists()


def test_un_retrait_qui_echoue_n_arrete_pas_les_suivants(site, tmp_path):
    """Sans RECORD, pip refuse de désinstaller ; le paquet suivant part quand même."""
    python, purelib = site
    _poser(purelib, "attendu", "2.0")
    bloque = _poser(purelib, "a-sans-record", "1.0", record=False)
    trop = _poser(purelib, "en-trop", "1.0")

    r = _lancer(python, _verrou(tmp_path, "attendu==2.0\n"))

    assert r.returncode == 1
    assert not trop.exists()
    assert bloque.exists()
    assert "désinstallés : en-trop\n" in r.stdout
    assert "hors verrou : a-sans-record==1.0" in r.stderr


def test_le_residu_d_une_desinstallation_interrompue_est_signale_sans_bloquer(site, tmp_path):
    python, purelib = site
    _poser(purelib, "attendu", "2.0")
    _poser(purelib, "en-trop", "1.0", prefixe="~")

    r = _lancer(python, _verrou(tmp_path, "attendu==2.0\n"))

    assert r.returncode == 0, r.stderr
    assert "Résidu d'une désinstallation interrompue" in r.stderr
    assert "~en_trop-1.0.dist-info" in r.stderr


def test_un_nom_qui_ressemble_a_une_option_n_est_pas_lu_par_pip(site, tmp_path):
    """Sans `--`, pip lirait `-rcible-txt` comme « désinstalle ce que liste
    cible-txt », et retirerait un paquet du verrou."""
    python, purelib = site
    attendu = _poser(purelib, "attendu", "2.0")
    _poser(purelib, "-rcible.txt", "1.0")
    verrou = _verrou(tmp_path, "attendu==2.0\n")
    (tmp_path / "cible-txt").write_text("attendu\n")

    r = _lancer(python, verrou)

    assert attendu.exists()
    assert r.returncode == 1
    assert "hors verrou : -rcible-txt==1.0" in r.stderr


def test_un_autre_projet_editable_reste(site, tmp_path):
    python, purelib = site
    _poser(purelib, "attendu", "2.0")
    autre = _poser(purelib, "autre-editable", "1.0", **EDITABLE)

    r = _lancer(python, _verrou(tmp_path, "attendu==2.0\n"))

    assert r.returncode == 0, r.stderr
    assert autre.exists()


def test_l_egg_info_laisse_dans_les_sources_ne_masque_pas_l_editable(site, tmp_path):
    """`pip install -e .` laisse `<sources>/<projet>.egg-info`, sans
    direct_url.json, visible par le sys.path après la vraie installation."""
    python, purelib = site
    _poser(purelib, "attendu", "2.0")
    autre = _poser(purelib, "autre-editable", "1.0", **EDITABLE)
    sources = tmp_path / "sources"
    (sources / "autre_editable.egg-info").mkdir(parents=True)
    (sources / "autre_editable.egg-info" / "PKG-INFO").write_text(
        "Metadata-Version: 2.1\nName: autre-editable\nVersion: 1.0\n"
    )
    (purelib / SOURCES_PTH).write_text(f"{sources}\n")

    r = _lancer(python, _verrou(tmp_path, "attendu==2.0\n"))

    assert r.returncode == 0, r.stderr
    assert autre.exists()


def test_un_doublon_plus_loin_sur_le_sys_path_ne_compte_pas(site, tmp_path):
    """Deux distributions du même nom : Python importe la première trouvée."""
    python, purelib = site
    _poser(purelib, "attendu", "2.0")
    sources = tmp_path / "sources"
    (sources / "attendu.egg-info").mkdir(parents=True)
    (sources / "attendu.egg-info" / "PKG-INFO").write_text(
        "Metadata-Version: 2.1\nName: attendu\nVersion: 1.0\n"
    )
    (purelib / SOURCES_PTH).write_text(f"{sources}\n")

    assert _lancer(python, _verrou(tmp_path, "attendu==2.0\n"), "--verifier").returncode == 0


def test_l_outillage_nomme_par_le_verrou_est_compare(site, tmp_path):
    """`pip-compile --allow-unsafe` fige pip, setuptools et wheel dans le verrou."""
    python, purelib = site
    _poser(purelib, "attendu", "2.0")
    verrou = _verrou(tmp_path, f"attendu==2.0\npip=={_version_de_pip(python)}\n")
    assert _lancer(python, verrou, "--verifier").returncode == 0

    verrou.write_text("attendu==2.0\npip==0.1\n")
    r = _lancer(python, verrou)
    assert r.returncode == 1
    assert "version : pip " in r.stderr
    assert _version_de_pip(python) != "0.1"


def test_verifier_ne_desinstalle_rien(site, tmp_path):
    python, purelib = site
    _poser(purelib, "attendu", "2.0")
    trop = _poser(purelib, "en-trop", "1.0")

    r = _lancer(python, _verrou(tmp_path, "attendu==2.0\n"), "--verifier")

    assert r.returncode == 1
    assert "hors verrou : en-trop==1.0" in r.stderr
    assert trop.exists()
