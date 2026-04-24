"""
Modèles de base pour la comptabilité agricole simplifiée.

Partie minimale nécessaire pour : un journal, une écriture, une ligne d'écriture,
un compte PCG, un exercice. L'export FEC sera piloté par ces modèles.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TypeJournal(StrEnum):
    ACHAT = "ACH"
    VENTE = "VEN"
    BANQUE = "BQ"
    CAISSE = "CA"
    OPERATIONS_DIVERSES = "OD"
    A_NOUVEAUX = "AN"


class SensEcriture(StrEnum):
    DEBIT = "D"
    CREDIT = "C"


class Compte(BaseModel):
    """Un compte du PCG agricole (chargé depuis le YAML)."""

    code: str = Field(pattern=r"^\d{1,6}$")
    nom: str
    classe: int = Field(ge=1, le=9)
    agri_specifique: bool = False
    parent_code: str | None = None


class LigneEcriture(BaseModel):
    """Une ligne débit OU crédit dans une écriture."""

    compte: str = Field(description="Code compte PCG (ex: '6011', '411001')")
    libelle: str
    debit: Decimal = Field(default=Decimal("0"), ge=0)
    credit: Decimal = Field(default=Decimal("0"), ge=0)
    piece_justificative: str | None = Field(
        default=None,
        description="Référence facture/ticket/bon",
    )

    @model_validator(mode="after")
    def _exactement_un_sens(self):
        if (self.debit > 0) == (self.credit > 0):
            raise ValueError(
                f"Ligne '{self.compte}' : exactement un des champs debit/credit doit être > 0."
            )
        return self


class Ecriture(BaseModel):
    """Une écriture comptable = un ensemble équilibré de lignes D/C."""

    journal: TypeJournal
    date_operation: date
    numero_piece: str = Field(description="Ex: FAC2026-001")
    libelle: str
    lignes: list[LigneEcriture] = Field(min_length=2)

    @model_validator(mode="after")
    def _equilibre_debit_credit(self):
        tot_d = sum(l.debit for l in self.lignes)
        tot_c = sum(l.credit for l in self.lignes)
        if tot_d != tot_c:
            raise ValueError(
                f"Écriture non équilibrée : D={tot_d} ≠ C={tot_c} "
                f"(pièce {self.numero_piece})"
            )
        return self


class Exercice(BaseModel):
    """Exercice comptable (par défaut 01/01 → 31/12)."""

    model_config = ConfigDict(frozen=True)

    annee: int
    date_debut: date
    date_fin: date
    cloture: bool = False

    @classmethod
    def annee_civile(cls, annee: int) -> "Exercice":
        return cls(
            annee=annee,
            date_debut=date(annee, 1, 1),
            date_fin=date(annee, 12, 31),
        )
