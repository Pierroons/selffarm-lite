#!/usr/bin/env python3
"""
Manifeste des modules, et ce que ce dépôt dit de my-self.

🔑 **Pourquoi ce script existe.** my-self et selffarm-lite se décrivaient l'un l'autre en prose
recopiée, et la prose dérivait : au 27/09/2026, notre README présentait les modules de my-self tels
qu'en juin, et l'accueil my-self.fr affichait nos modules en « v0.3 » quand nous étions en 0.4.1.
Chaque dépôt fait désormais foi pour ses propres modules et publie un `modules.json` ; l'autre le
LIT au lieu de le recopier.

Deux commandes :

    python3 scripts/ecosysteme.py manifeste [--ecrire]
        `modules.json` et le tableau « Modules publiés » du README suivent-ils le code ?
        Sources : `modules.toml`, `VERSION`, `webapp/modules_catalog.py`. Aucun accès réseau.

    python3 scripts/ecosysteme.py ecosysteme [--ecrire]
        Le bloc « Intégration écosystème » du README suit-il le modules.json de my-self ?
        Source : `MYSELF_MODULES_URL`, par défaut celle déclarée dans `modules.toml`.

`--ecrire` régénère au lieu de comparer.
Sortie : 0 à jour, 1 écart ou déclaration incohérente, 2 source injoignable, illisible ou bloc absent.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent

STATUTS = {
    "live": {"fr": "disponible", "en": "available"},
    "soon": {"fr": "en préparation", "en": "in preparation"},
}

LISEZ_MOI = (
    "Généré par scripts/ecosysteme.py depuis modules.toml, VERSION et webapp/modules_catalog.py : "
    "ne pas l'éditer à la main. Les modules sortent avec le dépôt : leur version de sortie est depot.version. "
    "Les autres dépôts de l'écosystème lisent ce fichier au lieu de recopier nos modules."
)

BLOC_MODULES = "modules"
BLOC_ECOSYSTEME = "ecosysteme:my-self"


class Injoignable(Exception):
    """Source absente ou illisible — code de sortie 2."""


def _declarations(racine: Path) -> dict:
    return tomllib.loads((racine / "modules.toml").read_text(encoding="utf-8"))


def _statuts_catalogue(racine: Path) -> dict[str, str]:
    # Chargé comme fichier isolé : importer `webapp` exécuterait tout le paquet, dépendances comprises.
    chemin = racine / "webapp" / "modules_catalog.py"
    spec = importlib.util.spec_from_file_location("_catalogue_ecosysteme", chemin)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses résout les annotations par sys.modules
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules[spec.name]
    return {m.id: m.status for m in module.CATALOG}


def construire_manifeste(racine: Path) -> tuple[dict, list[str]]:
    """Le manifeste, et la liste des incohérences entre `modules.toml` et le code."""
    declarations = _declarations(racine)
    catalogue = _statuts_catalogue(racine)
    erreurs = []

    declares = {m["id"] for m in declarations["module"]}
    paquets = {
        d.name
        for d in (racine / "modules").iterdir()
        if d.is_dir() and d.name.startswith("self_") and (d / "__init__.py").exists()
    }
    for oublie in sorted(paquets - declares):
        erreurs.append(f"modules/{oublie} n'est pas déclaré dans modules.toml")

    modules = []
    for m in declarations["module"]:
        if not (racine / m["dossier"]).exists():
            erreurs.append(f"{m['id']} : dossier « {m['dossier']} » absent")
        if "statut" in m:
            statut = m["statut"]
        elif m.get("catalogue") not in catalogue:
            erreurs.append(f"{m['id']} : « {m.get('catalogue')} » absent de modules_catalog.py")
            continue
        elif catalogue[m["catalogue"]] not in STATUTS:
            erreurs.append(f"{m['id']} : statut « {catalogue[m['catalogue']]} » sans traduction")
            continue
        else:
            statut = STATUTS[catalogue[m["catalogue"]]]
        modules.append({
            "id": m["id"],
            "nom": m["nom"],
            "dossier": m["dossier"],
            "version": None,
            "resume": m["resume"],
            "statut": statut,
            "porteurs": ["README.md"],
        })

    version = (racine / "VERSION").read_text(encoding="utf-8").strip()
    manifeste = {
        "depot": {"nom": "selffarm-lite", "version": version},
        "lisez_moi": LISEZ_MOI,
        "modules": modules,
    }
    return manifeste, erreurs


def tableau_modules(manifeste: dict) -> str:
    lignes = ["| Module | Objet | État |", "|---|---|:---:|"]
    for m in manifeste["modules"]:
        lignes.append(
            f"| [`{m['nom']}`]({m['dossier']}) | {m['resume']['fr']} | {m['statut']['fr']} |"
        )
    return "\n".join(lignes)


def lire_myself(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=20) as reponse:
            donnees = json.load(reponse)
        return {m["id"]: m for m in donnees["modules"]}
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError) as exc:
        raise Injoignable(f"modules.json de my-self illisible ({url}) : {exc}") from exc


def liste_ecosysteme(racine: Path, url: str) -> tuple[str, list[str]]:
    publies = lire_myself(url)
    erreurs, lignes = [], []
    for ident in _declarations(racine)["ecosysteme"]["modules"]:
        if ident not in publies:
            erreurs.append(f"« {ident} » n'est plus publié par my-self")
            continue
        m = publies[ident]
        version = f" {m['version']}" if m.get("version") else ""
        lignes.append(f"- **{m['nom']}**{version} — {m['resume']['fr']}")
    return "\n".join(lignes), erreurs


def remplacer_bloc(texte: str, balise: str, contenu: str) -> str:
    """Remplace ce qui se trouve entre les deux balises. Bloc absent : Injoignable."""
    debut, fin = f"<!-- {balise}:debut", f"<!-- {balise}:fin -->"
    i, j = texte.find(debut), texte.find(fin)
    if i < 0 or j < i:
        raise Injoignable(f"bloc « {balise} » absent du README")
    i = texte.index("\n", i) + 1
    # Lignes vides autour du contenu : une liste ou un tableau collé à une balise HTML est
    # mal délimité pour les lecteurs Markdown stricts (MD032).
    return texte[:i] + "\n" + contenu + "\n\n" + texte[j:]


def _comparer(chemin: Path, attendu: str, ecrire: bool, commande: str) -> bool:
    actuel = chemin.read_text(encoding="utf-8") if chemin.exists() else ""
    if actuel == attendu:
        return True
    if ecrire:
        chemin.write_text(attendu, encoding="utf-8")
        print(f"  ✎ {chemin.name} régénéré")
        return True
    print(f"  ✗ {chemin.name} ne suit plus sa source — python3 scripts/ecosysteme.py {commande} --ecrire")
    return False


def manifeste(racine: Path, ecrire: bool) -> int:
    print("▸ Manifeste — modules.json et le tableau du README suivent le code")
    donnees, erreurs = construire_manifeste(racine)
    for e in erreurs:
        print(f"  ✗ {e}")
    if erreurs:
        return 1
    readme = racine / "README.md"
    texte = remplacer_bloc(readme.read_text(encoding="utf-8"), BLOC_MODULES, tableau_modules(donnees))
    json_attendu = json.dumps(donnees, ensure_ascii=False, indent=2) + "\n"
    ok = _comparer(racine / "modules.json", json_attendu, ecrire, "manifeste")
    ok = _comparer(readme, texte, ecrire, "manifeste") and ok
    if ok:
        print(f"  ✓ {len(donnees['modules'])} modules, version du dépôt {donnees['depot']['version']}")
    return 0 if ok else 1


def ecosysteme(racine: Path, ecrire: bool) -> int:
    url = os.environ.get("MYSELF_MODULES_URL") or _declarations(racine)["ecosysteme"]["source"]
    print(f"▸ Écosystème — le README suit le modules.json de my-self ({url})")
    liste, erreurs = liste_ecosysteme(racine, url)
    for e in erreurs:
        print(f"  ✗ {e}")
    readme = racine / "README.md"
    texte = remplacer_bloc(readme.read_text(encoding="utf-8"), BLOC_ECOSYSTEME, liste)
    ok = _comparer(readme, texte, ecrire, "ecosysteme") and not erreurs
    if ok:
        print(f"  ✓ {len(liste.splitlines())} modules de my-self à jour")
    return 0 if ok else 1


def main(argv: list[str] | None = None, racine: Path = RACINE) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    parser.add_argument("commande", choices=("manifeste", "ecosysteme"))
    parser.add_argument("--ecrire", action="store_true", help="régénère au lieu de comparer")
    args = parser.parse_args(argv)
    commande = manifeste if args.commande == "manifeste" else ecosysteme
    try:
        return commande(racine, args.ecrire)
    except Injoignable as exc:
        print(f"  ✗ {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
