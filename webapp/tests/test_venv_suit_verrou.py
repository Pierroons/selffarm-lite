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
_spec.loader.exec_module(vsv)


def test_normalisation_pep503():
    assert vsv.normaliser("pdfminer.six") == "pdfminer-six"
    assert vsv.normaliser("Python_Dateutil") == "python-dateutil"


@pytest.mark.parametrize("nom", ["requirements.txt", "requirements-dev.txt"])
def test_le_verrou_du_depot_se_lit_en_entier(nom):
    texte = (RACINE / nom).read_text(encoding="utf-8")
    attendus = [ligne for ligne in texte.splitlines() if "==" in ligne and not ligne.startswith("#")]
    assert len(vsv.lire_verrou(texte)) == len(attendus) > 0


@pytest.mark.parametrize("ligne", [
    "pillow>=13",
    "-e .",
    "brotli==1.2.1 ; python_version < '3.14'",
])
def test_une_ligne_hors_format_est_refusee(ligne):
    with pytest.raises(ValueError):
        vsv.lire_verrou(ligne)


def test_ecarts_nomme_chaque_difference():
    verrou = {"attendu": "2.0", "manquant": "1.0"}
    porte = {"attendu": "1.9", "orphelin": "0.1"}
    assert vsv.ecarts(verrou, porte) == [
        "absent : manquant==1.0",
        "version : attendu 1.9 au lieu de 2.0",
        "hors verrou : orphelin==0.1",
    ]


# --- De bout en bout, dans un vrai venv -------------------------------------

FACTICES = ("attendu", "en-trop", "projet-local")


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


def _poser(purelib: Path, nom: str, version: str, **fichiers: str) -> Path:
    """Un paquet installé tel que pip le laisse, chaque fichier inscrit au RECORD.
    Rend son METADATA : c'est par lui que pip et importlib le voient installé."""
    module = nom.replace("-", "_")
    info = purelib / f"{module}-{version}.dist-info"
    info.mkdir()
    (purelib / f"{module}.py").write_text("")
    contenu = {
        "METADATA": f"Metadata-Version: 2.1\nName: {nom}\nVersion: {version}\n",
        "INSTALLER": "pip\n",
        **fichiers,
    }
    for fichier, texte in contenu.items():
        (info / fichier).write_text(texte)
    record = [f"{module}.py", *(f"{info.name}/{f}" for f in [*contenu, "RECORD"])]
    (info / "RECORD").write_text("".join(f"{chemin},,\n" for chemin in record))
    return info / "METADATA"


@pytest.fixture
def site(venv):
    python, purelib = venv
    for nom in FACTICES:
        module = nom.replace("-", "_")
        for info in purelib.glob(f"{module}-*.dist-info"):
            shutil.rmtree(info)
        (purelib / f"{module}.py").unlink(missing_ok=True)
    (purelib / SOURCES_PTH).unlink(missing_ok=True)
    return python, purelib


SOURCES_PTH = "zz_sources_du_projet.pth"


def _version_de_pip(python: Path) -> str:
    return subprocess.run(
        [str(python), "-c", "from importlib.metadata import version; print(version('pip'))"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def _lancer(python: Path, verrou: Path, *options: str) -> subprocess.CompletedProcess:
    return subprocess.run([str(python), str(SCRIPT), str(verrou), *options],
                          capture_output=True, text=True, check=False)


def test_le_paquet_hors_verrou_est_desinstalle(site, tmp_path):
    python, purelib = site
    _poser(purelib, "attendu", "2.0")
    trop = _poser(purelib, "en-trop", "1.0")
    verrou = tmp_path / "requirements.txt"
    verrou.write_text("attendu==2.0\n    # via selffarm-lite\n")

    r = _lancer(python, verrou)

    assert r.returncode == 0, r.stderr
    assert "désinstallés : en-trop\n" in r.stdout
    assert not trop.exists()
    assert not (purelib / "en_trop.py").exists()


def test_une_version_differente_fait_echouer(site, tmp_path):
    python, purelib = site
    _poser(purelib, "attendu", "1.0")
    verrou = tmp_path / "requirements.txt"
    verrou.write_text("attendu==2.0\n")

    r = _lancer(python, verrou)

    assert r.returncode == 1
    assert "version : attendu 1.0 au lieu de 2.0" in r.stderr


def test_le_projet_installe_en_editable_reste(site, tmp_path):
    python, purelib = site
    _poser(purelib, "attendu", "2.0")
    projet = _poser(purelib, "projet-local", "0.4.12", **{
        "direct_url.json": '{"url": "file:///opt/projet", "dir_info": {"editable": true}}',
    })
    verrou = tmp_path / "requirements.txt"
    verrou.write_text("attendu==2.0\n")

    r = _lancer(python, verrou)

    assert r.returncode == 0, r.stderr
    assert projet.exists()


def test_l_egg_info_laisse_dans_les_sources_ne_masque_pas_l_editable(site, tmp_path):
    """`pip install -e .` laisse `<sources>/selffarm_lite.egg-info`, sans
    direct_url.json, visible par le sys.path après la vraie installation."""
    python, purelib = site
    _poser(purelib, "attendu", "2.0")
    projet = _poser(purelib, "projet-local", "0.4.12", **{
        "direct_url.json": '{"url": "file:///opt/projet", "dir_info": {"editable": true}}',
    })
    sources = tmp_path / "sources"
    (sources / "projet_local.egg-info").mkdir(parents=True)
    (sources / "projet_local.egg-info" / "PKG-INFO").write_text(
        "Metadata-Version: 2.1\nName: projet-local\nVersion: 0.4.12\n"
    )
    (purelib / SOURCES_PTH).write_text(f"{sources}\n")
    verrou = tmp_path / "requirements.txt"
    verrou.write_text("attendu==2.0\n")

    r = _lancer(python, verrou)

    assert r.returncode == 0, r.stderr
    assert projet.exists()


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
    verrou = tmp_path / "requirements.txt"
    verrou.write_text("attendu==2.0\n")

    assert _lancer(python, verrou, "--verifier").returncode == 0


def test_l_outillage_nomme_par_le_verrou_est_compare(site, tmp_path):
    """`pip-compile --allow-unsafe` fige pip, setuptools et wheel dans le verrou."""
    python, purelib = site
    _poser(purelib, "attendu", "2.0")
    verrou = tmp_path / "requirements.txt"
    verrou.write_text(f"attendu==2.0\npip=={_version_de_pip(python)}\n")
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
    verrou = tmp_path / "requirements.txt"
    verrou.write_text("attendu==2.0\n")

    r = _lancer(python, verrou, "--verifier")

    assert r.returncode == 1
    assert "hors verrou : en-trop==1.0" in r.stderr
    assert trop.exists()
