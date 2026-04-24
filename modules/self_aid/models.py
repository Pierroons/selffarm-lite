"""
Modèles Pydantic pour la BDD d'aides publiques.

Une `Aide` = 1 dispositif public (ex: DNJA, CI-AB, exo MSA JA, AITA). Chaque
aide est sourcée à une source primaire officielle avec date MAJ vue,
conformément au référentiel `reference_sources_officielles_myself.md`.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class CategorieAide(StrEnum):
    INSTALLATION = "installation"
    INSTALLATION_ACCOMPAGNEMENT = "installation-accompagnement"
    REVENU = "revenu"
    REVENU_PAC = "revenu-pac"
    REVENU_PAC_COUPLEE = "revenu-pac-couplee"
    CONVERSION = "conversion"
    CREDIT_IMPOT = "credit_impot"
    FISCAL_DEDUCTION = "fiscal-deduction"
    COTISATION = "cotisation"
    DEPARTEMENTAL = "departemental"
    INVESTISSEMENT = "investissement"


class TypeMontant(StrEnum):
    FIXE = "fixe"
    VARIABLE = "variable"


class Montant(BaseModel):
    """Enveloppe financière d'une aide."""

    model_config = ConfigDict(extra="allow")  # tolère le champ `detail` arbitraire

    type: TypeMontant
    valeur_min: Decimal = Field(ge=0)
    valeur_max: Decimal = Field(ge=0)
    unite: str = Field(default="€", description="€, €/ha, €/an, €/ha/an…")
    detail: dict[str, Any] | None = None


class Conditions(BaseModel):
    """Conditions d'éligibilité pour une aide."""

    model_config = ConfigDict(extra="allow")

    age_max: int | None = None
    age_min: int | None = None
    zone: list[str] = Field(default_factory=list)
    formation: list[str] = Field(default_factory=list)
    autres: list[str] = Field(default_factory=list)


class Source(BaseModel):
    """Référence d'une source primaire officielle."""

    url: HttpUrl | str  # HttpUrl idéalement, str en fallback si format atypique
    autorite: str = Field(description="Domaine d'autorité (ex: legifrance.gouv.fr)")
    date_maj_vu: str = Field(description="Date ISO à laquelle Claude ou Pierroons ont vérifié la source")
    extrait_citation: str = Field(
        default="",
        description="Phrase officielle justifiant le montant/condition",
    )


class Aide(BaseModel):
    """Un dispositif d'aide publique structuré pour consultation par profil."""

    id: str = Field(description="Identifiant court unique (ex: dnja-2026)")
    nom: str
    categorie: CategorieAide
    montant: Montant
    conditions: Conditions
    zones_applicables: list[str] = Field(default_factory=list)
    cumul_possible_avec: list[str] = Field(default_factory=list)
    exclut: list[str] = Field(default_factory=list)
    statut_cible: list[str] = Field(default_factory=list)
    source: Source
    notes: str = ""


class BaseAides(BaseModel):
    """Conteneur YAML racine."""

    aides: list[Aide]


class FiltreRecherche(BaseModel):
    """Critères de filtre pour interroger la base."""

    model_config = ConfigDict(extra="forbid")

    statut: str | None = None
    categorie: CategorieAide | None = None
    zone: str | None = None
    departement: int | None = None
    bio: bool | None = None
    age: int | None = None
    mot_cle: str | None = None
