"""
Chargement et filtrage de la BDD d'aides depuis les YAML `data/*.yaml`.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from self_aid.models import Aide, BaseAides, FiltreRecherche

log = logging.getLogger("self-aid")

DATA_DIR = Path(__file__).parent / "data"

# Les aides départementales dépendent du territoire : les versionner
# reviendrait à publier où l'on est installé. Elles vivent donc ici, hors
# dépôt (voir .gitignore), et s'ajoutent aux aides nationales quand le
# dossier existe. Un dépôt fraîchement cloné fonctionne sans.
LOCAL_DIR = DATA_DIR / "local"


def load_all(data_dir: Path | None = None) -> list[Aide]:
    """Charge les aides nationales, plus les aides locales si elles existent.

    Un `data_dir` explicite court-circuite les deux — c'est ce dont les tests
    ont besoin pour travailler sur un jeu maîtrisé.
    """
    if data_dir is not None:
        sources = [data_dir]
    else:
        sources = [DATA_DIR]
        if LOCAL_DIR.is_dir():
            sources.append(LOCAL_DIR)

    aides: list[Aide] = []
    for yaml_file in sorted(f for d in sources for f in d.glob("*.yaml")):
        with yaml_file.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        bundle = BaseAides.model_validate(raw)
        aides.extend(bundle.aides)
        log.info("Chargé %d aides depuis %s", len(bundle.aides), yaml_file.name)
    return aides


def filter_aides(aides: list[Aide], f: FiltreRecherche) -> list[Aide]:
    """Filtre la liste selon les critères fournis."""
    out = aides
    if f.statut:
        out = [a for a in out if f.statut in a.statut_cible]
    if f.categorie:
        out = [a for a in out if a.categorie == f.categorie]
    if f.zone:
        z = f.zone.lower()
        out = [a for a in out if any(z in zone.lower() for zone in a.zones_applicables)]
    if f.bio is True:
        out = [a for a in out if any("bio" in s for s in a.statut_cible) or
               any("bio" in (a.nom or "").lower() for _ in [0])]
    if f.mot_cle:
        mc = f.mot_cle.lower()
        out = [a for a in out if mc in a.nom.lower() or mc in a.id.lower() or mc in a.notes.lower()]
    return out


def total_enveloppe(aides: list[Aide]) -> tuple[float, float]:
    """Retourne (min, max) du total cumulé possible (approximatif)."""
    mn = sum(float(a.montant.valeur_min) for a in aides)
    mx = sum(float(a.montant.valeur_max) for a in aides)
    return mn, mx
