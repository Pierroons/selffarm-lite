"""Ramène le venv qui l'exécute exactement au verrou, puis le vérifie.

    <venv>/bin/python scripts/venv_suit_verrou.py requirements.txt [--verifier]

`pip install -r` installe et met à jour, mais ne retire rien : un paquet qui
sort du verrou reste dans le venv, avec ses failles. Ce script désinstalle
tout ce que le verrou ne nomme pas, puis sort en erreur si une version
installée diffère de celle du verrou. `--verifier` ne fait que la vérification.

Jamais désinstallés : pip, setuptools et wheel (comparés quand le verrou les
nomme), et les projets installés en mode éditable (le dépôt, `pip install -e`).
Bibliothèque standard seule : il tourne avant que le venv soit conforme.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from importlib import metadata
from pathlib import Path

OUTILLAGE = frozenset({"pip", "setuptools", "wheel"})


def normaliser(nom: str) -> str:
    """Forme canonique d'un nom de paquet (PEP 503) : `pdfminer.six` = `pdfminer-six`."""
    return re.sub(r"[-_.]+", "-", nom).lower()


def lire_verrou(texte: str) -> dict[str, str]:
    """`nom==version` par ligne, tel que pip-compile l'écrit ; le reste est refusé."""
    verrou: dict[str, str] = {}
    for numero, ligne in enumerate(texte.splitlines(), 1):
        ligne = ligne.split("#", 1)[0].strip()
        if not ligne:
            continue
        m = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;]+)", ligne)
        if not m:
            raise ValueError(f"ligne {numero} du verrou non reconnue : {ligne!r}")
        verrou[normaliser(m.group(1))] = m.group(2)
    return verrou


def _editable(dist: metadata.Distribution) -> bool:
    brut = dist.read_text("direct_url.json")
    if not brut:
        return False
    try:
        return bool(json.loads(brut).get("dir_info", {}).get("editable"))
    except (ValueError, AttributeError):
        return False


def installes() -> dict[str, str]:
    """Ce que le venv porte, nom → version, sans les projets éditables.

    Un même nom peut paraître deux fois : `pip install -e` laisse aussi un
    `*.egg-info` dans les sources, que le `sys.path` rend visible. Le nom est
    éditable dès qu'une de ses distributions l'est ; sa version est la première
    trouvée, celle que Python importe.
    """
    porte: dict[str, str] = {}
    editables: set[str] = set()
    for dist in metadata.distributions():
        nom = dist.metadata["Name"]
        if not nom:
            continue
        cle = normaliser(nom)
        if _editable(dist):
            editables.add(cle)
        porte.setdefault(cle, dist.version)
    return {cle: version for cle, version in porte.items() if cle not in editables}


def en_trop(verrou: dict[str, str], porte: dict[str, str]) -> list[str]:
    return sorted(set(porte) - set(verrou) - OUTILLAGE)


def ecarts(verrou: dict[str, str], porte: dict[str, str]) -> list[str]:
    """Chaque différence entre le venv et le verrou, lisible telle quelle."""
    lignes = [f"absent : {nom}=={version}"
              for nom, version in sorted(verrou.items()) if nom not in porte]
    lignes += [f"version : {nom} {porte[nom]} au lieu de {version}"
               for nom, version in sorted(verrou.items())
               if nom in porte and porte[nom] != version]
    lignes += [f"hors verrou : {nom}=={porte[nom]}" for nom in en_trop(verrou, porte)]
    return lignes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("verrou", type=Path)
    parser.add_argument("--verifier", action="store_true",
                        help="vérifier sans rien désinstaller")
    args = parser.parse_args(argv)

    verrou = lire_verrou(args.verrou.read_text(encoding="utf-8"))
    if not args.verifier:
        retirer = en_trop(verrou, installes())
        if retirer:
            print(f"Hors verrou, désinstallés : {' '.join(retirer)}")
            subprocess.run([sys.executable, "-m", "pip", "uninstall", "--yes",
                            "--quiet", *retirer], check=True)

    reste = ecarts(verrou, installes())
    if reste:
        print(f"❌ Le venv ne suit pas {args.verrou.name} :", file=sys.stderr)
        for ligne in reste:
            print(f"   {ligne}", file=sys.stderr)
        return 1
    print(f"✓ Venv conforme à {args.verrou.name} : {len(verrou)} paquets, aucun en trop.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
