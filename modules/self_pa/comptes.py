"""
Comptes de charge proposés à l'imputation.

La source est `self_agri_book/data/pcg-agricole-2026.yaml` — le plan comptable
agricole canonique du dépôt, construit sur le règlement ANC 2014-03 modifié et le
PCGA. Recopier une liste de comptes ici en ferait une seconde source, qui
divergerait au premier ajout.

Seule la classe 6 est exposée : c'est celle des charges, et une facture
fournisseur ne s'impute pas ailleurs. Le compte de contrepartie (401) et la TVA
déductible (44566) sont fixés par le schéma d'achat, pas choisis.
"""

from __future__ import annotations

import functools
import logging
from pathlib import Path

import yaml

log = logging.getLogger("selffarm.self_pa.comptes")

CHEMIN_PCG = (
    Path(__file__).resolve().parent.parent
    / "self_agri_book" / "data" / "pcg-agricole-2026.yaml"
)

CLASSE_CHARGES = "6"


@functools.lru_cache(maxsize=1)
def groupes_de_charge() -> list[tuple[str, str, tuple[tuple[str, str, bool], ...]]]:
    """Les comptes de charge, groupés par compte à deux chiffres.

    Rend `[(code_groupe, nom_groupe, ((code, nom, agri_specifique), …)), …]` —
    la forme qu'attend un `<select>` à `<optgroup>`. Une centaine de comptes à
    plat serait illisible ; regroupés, ils se parcourent.
    """
    if not CHEMIN_PCG.exists():
        log.warning("PCG introuvable (%s) — aucun compte proposé", CHEMIN_PCG)
        return []

    donnees = yaml.safe_load(CHEMIN_PCG.read_text(encoding="utf-8"))
    groupes = []
    for classe in donnees.get("classes", []):
        if str(classe.get("code")) != CLASSE_CHARGES:
            continue
        for compte in classe.get("comptes", []):
            sous = tuple(
                (str(s["code"]), s["nom"], bool(s.get("agri_specifique")))
                for s in compte.get("sous_comptes", [])
                if s.get("code") and s.get("nom")
            )
            if sous:
                groupes.append((str(compte["code"]), compte.get("nom", ""), sous))
    log.debug("PCG : %d groupe(s) de charge chargé(s)", len(groupes))
    return groupes


@functools.lru_cache(maxsize=1)
def _libelles() -> dict[str, str]:
    return {
        code: nom
        for _, _, sous in groupes_de_charge()
        for code, nom, _ in sous
    }


def libelle(code: str) -> str:
    """Nom du compte, ou le code lui-même s'il est inconnu du plan.

    Un code absent n'est pas une erreur : le plan livré ne couvre pas les
    subdivisions qu'une exploitation peut créer.
    """
    return _libelles().get(code, code)


def est_compte_de_charge(code: str) -> bool:
    """Vrai si le code appartient à la classe 6.

    Vérifié sur le préfixe et non sur l'appartenance au plan, pour la même
    raison : une subdivision maison comme `60611` reste une charge.
    """
    return bool(code) and code.startswith(CLASSE_CHARGES)
