"""Ramène le venv qui l'exécute au verrou, puis vérifie ses métadonnées.

    <venv>/bin/python scripts/venv_suit_verrou.py requirements.txt [--verifier]

`pip install -r` installe et met à jour, mais ne retire rien : un paquet qui
sort du verrou reste dans le venv, avec ses failles. Lancé après
`pip install -r`, ce script :
1. refuse un verrou vide, ou qui n'est pas fait de lignes `nom==version` ;
2. refuse, sans rien désinstaller, un venv où un paquet du verrou manque ou n'a
   pas sa version, et un venv où le projet n'est pas installé ;
3. désinstalle un par un les paquets que le verrou ne nomme pas, et passe au
   suivant si l'un échoue ;
4. sort en erreur s'il reste un écart.
`--verifier` saute l'étape 3.

Jamais désinstallés : le projet que nomme le `pyproject.toml` voisin du verrou,
qu'il soit installé en mode éditable ou non ; les autres projets éditables ;
pip, setuptools et wheel, comparés quand le verrou les nomme.

Le contrôle porte sur les noms et les versions que déclarent les métadonnées,
pas sur le contenu des fichiers : ce n'est pas un contrôle d'intégrité.
Bibliothèque standard seule : il tourne avant que le venv soit conforme.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path

OUTILLAGE = frozenset({"pip", "setuptools", "wheel"})


def normaliser(nom: str) -> str:
    """Forme canonique d'un nom de paquet (PEP 503) : `pdfminer.six` = `pdfminer-six`."""
    return re.sub(r"[-_.]+", "-", nom.strip()).lower()


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
        cle = normaliser(m.group(1))
        if cle in verrou:
            raise ValueError(f"ligne {numero} du verrou : {cle} y figure deux fois")
        verrou[cle] = m.group(2)
    if not verrou:
        raise ValueError("verrou vide : aucune ligne nom==version")
    return verrou


def lire_projet(pyproject: Path) -> str:
    """Nom normalisé du projet que déclare `pyproject.toml`."""
    with pyproject.open("rb") as f:
        nom = tomllib.load(f).get("project", {}).get("name")
    if not nom:
        raise ValueError(f"{pyproject.name} ne déclare pas [project].name")
    return normaliser(nom)


def _editable(dist: metadata.Distribution) -> bool:
    brut = dist.read_text("direct_url.json")
    if not brut:
        return False
    try:
        return bool(json.loads(brut).get("dir_info", {}).get("editable"))
    except (ValueError, AttributeError):
        return False


@dataclass
class Venv:
    versions: dict[str, str] = field(default_factory=dict)
    """Nom → version, sans les éditables ; pour un nom vu deux fois, la première
    distribution trouvée sur le `sys.path`, celle que Python importe."""
    editables: set[str] = field(default_factory=set)
    """Un nom est éditable dès qu'une de ses distributions l'est : `pip install -e`
    laisse aussi un `*.egg-info` dans les sources, visible par le `sys.path`."""
    residus: list[str] = field(default_factory=list)
    """`~…dist-info` qu'un `pip uninstall` interrompu laisse : pip ne les tient
    plus pour installés, ils se retirent à la main."""


def inventaire() -> Venv:
    venv = Venv()
    for dist in metadata.distributions():
        # Le chemin d'un `.dist-info` n'a pas d'accès public.
        chemin = getattr(dist, "_path", None)
        if chemin is not None and Path(chemin).name.startswith("~"):
            venv.residus.append(str(chemin))
            continue
        nom = dist.metadata.get("Name")
        if not nom:
            continue
        cle = normaliser(nom)
        if _editable(dist):
            venv.editables.add(cle)
        venv.versions.setdefault(cle, dist.version)
    for cle in venv.editables:
        venv.versions.pop(cle, None)
    return venv


def en_trop(verrou: dict[str, str], porte: dict[str, str],
            proteges: frozenset[str] | set[str] = frozenset()) -> list[str]:
    return sorted(set(porte) - set(verrou) - OUTILLAGE - set(proteges))


def manques(verrou: dict[str, str], porte: dict[str, str]) -> list[str]:
    """Ce que le verrou exige et que le venv n'a pas, ou pas à cette version."""
    lignes = [f"absent : {nom}=={version}"
              for nom, version in sorted(verrou.items()) if nom not in porte]
    lignes += [f"version : {nom} {porte[nom]} au lieu de {version}"
               for nom, version in sorted(verrou.items())
               if nom in porte and porte[nom] != version]
    return lignes


def ecarts(verrou: dict[str, str], porte: dict[str, str],
           proteges: frozenset[str] | set[str] = frozenset()) -> list[str]:
    """Chaque différence entre le venv et le verrou, lisible telle quelle."""
    return manques(verrou, porte) + [f"hors verrou : {nom}=={porte[nom]}"
                                     for nom in en_trop(verrou, porte, proteges)]


def _refus(titre: str, lignes: list[str]) -> int:
    print(f"❌ {titre}", file=sys.stderr)
    for ligne in lignes:
        print(f"   {ligne}", file=sys.stderr)
    return 1


def _refus_avant_retrait(verrou: dict[str, str], projet: str, venv: Venv, nom_verrou: str) -> int:
    """Le verrou et le projet doivent être installés avant qu'on retire quoi que ce soit."""
    lignes = manques(verrou, venv.versions)
    if projet not in venv.versions and projet not in venv.editables:
        lignes.append(f"absent : {projet} (le projet lui-même)")
    if lignes:
        return _refus(f"{nom_verrou} n'est pas installé, rien n'est désinstallé :", lignes)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("verrou", type=Path)
    parser.add_argument("--verifier", action="store_true",
                        help="vérifier sans rien désinstaller")
    args = parser.parse_args(argv)

    try:
        verrou = lire_verrou(args.verrou.read_text(encoding="utf-8"))
        projet = lire_projet(args.verrou.parent / "pyproject.toml")
    except (OSError, ValueError, tomllib.TOMLDecodeError) as e:
        return _refus("Verrou ou projet illisible, rien n'est désinstallé :", [str(e)])

    venv = inventaire()
    avant = _refus_avant_retrait(verrou, projet, venv, args.verrou.name)
    if avant:
        return avant

    if not args.verifier:
        retirer = en_trop(verrou, venv.versions, venv.editables | {projet})
        for nom in retirer:
            subprocess.run([sys.executable, "-m", "pip", "uninstall", "--yes", "--quiet", nom],
                           check=False)
        venv = inventaire()
        partis = [nom for nom in retirer if nom not in venv.versions]
        if partis:
            print(f"Hors verrou, désinstallés : {' '.join(partis)}")

    for residu in venv.residus:
        print(f"⚠ Résidu d'une désinstallation interrompue, à retirer à la main : {residu}",
              file=sys.stderr)
    reste = ecarts(verrou, venv.versions, venv.editables | {projet})
    if reste:
        return _refus(f"Le venv ne suit pas {args.verrou.name} :", reste)
    print(f"✓ Métadonnées du venv conformes à {args.verrou.name} : "
          f"{len(verrou)} paquets, aucun en trop.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
