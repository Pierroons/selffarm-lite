"""
Chargement et filtrage du catalogue de variétés depuis `data/*.yaml`.

Le catalogue est une **donnée statique** versionnée dans le repo. Les
utilisateur·rices peuvent ajouter leurs propres variétés via la table SQL
`varietes_user` (cf. storage.py), mais le catalogue de référence reste la
source de vérité agronomique partagée.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from self_culture.models import (
    CatalogueVarietes,
    CategorieVariete,
    FamilleBotanique,
    Saison,
    Variete,
)

log = logging.getLogger("self-culture")

DATA_DIR = Path(__file__).parent / "data"


def load_catalog(data_dir: Path | None = None) -> list[Variete]:
    """Charge toutes les variétés depuis les YAML du dossier data/.

    Concatène plusieurs fichiers si plusieurs `*.yaml` sont présents.
    """
    directory = data_dir or DATA_DIR
    varietes: list[Variete] = []
    for yaml_file in sorted(directory.glob("*.yaml")):
        with yaml_file.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        bundle = CatalogueVarietes.model_validate(raw)
        varietes.extend(bundle.varietes)
        log.info("Chargé %d variétés depuis %s", len(bundle.varietes), yaml_file.name)
    return varietes


def filter_varietes(
    varietes: list[Variete],
    famille: FamilleBotanique | None = None,
    categorie: CategorieVariete | None = None,
    saison: Saison | None = None,
    mot_cle: str | None = None,
    sous_abri: bool | None = None,
) -> list[Variete]:
    """Filtre une liste de variétés selon des critères optionnels.

    Tous les filtres sont optionnels et combinables (AND).
    """
    out = varietes
    if famille is not None:
        out = [v for v in out if v.famille == famille]
    if categorie is not None:
        out = [v for v in out if v.categorie == categorie]
    if saison is not None:
        out = [v for v in out if saison in v.saisons_principales]
    if sous_abri is not None:
        out = [v for v in out if v.calendrier.sous_abri == sous_abri]
    if mot_cle:
        mc = mot_cle.lower()
        out = [
            v
            for v in out
            if mc in v.nom_commun.lower()
            or mc in v.nom_botanique.lower()
            or mc in v.id.lower()
            or mc in v.notes.lower()
        ]
    return out


def find_by_id(varietes: list[Variete], variete_id: str) -> Variete | None:
    """Retrouve une variété par son slug, ou None si absent."""
    for v in varietes:
        if v.id == variete_id:
            return v
    return None


def familles_presentes(varietes: list[Variete]) -> list[FamilleBotanique]:
    """Retourne les familles botaniques distinctes du catalogue."""
    return sorted(set(v.famille for v in varietes), key=lambda f: f.value)


def categories_presentes(varietes: list[Variete]) -> list[CategorieVariete]:
    """Retourne les catégories distinctes du catalogue."""
    return sorted(set(v.categorie for v in varietes), key=lambda c: c.value)
