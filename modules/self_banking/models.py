"""Modèles Pydantic pour les relevés et transactions bancaires."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field


class TypeMouvement(StrEnum):
    """Catégorisation technique des mouvements bancaires (source bank)."""

    VIREMENT_EMIS = "virement-emis"
    VIREMENT_RECU = "virement-recu"
    PRELEVEMENT = "prelevement"
    CARTE_BANCAIRE = "carte-bancaire"
    CHEQUE_EMIS = "cheque-emis"
    CHEQUE_RECU = "cheque-recu"
    RETRAIT_DAB = "retrait-dab"
    DEPOT_ESPECES = "depot-especes"
    FRAIS_BANCAIRES = "frais-bancaires"
    INTERETS = "interets"
    INCONNU = "inconnu"


class Transaction(BaseModel):
    """Une ligne de mouvement bancaire extraite d'un relevé."""

    date_operation: date
    date_valeur: date | None = None
    libelle: str = Field(description="Libellé brut tel qu'affiché par la banque")
    debit: Decimal | None = Field(default=None, ge=0)
    credit: Decimal | None = Field(default=None, ge=0)
    type_mouvement: TypeMouvement = TypeMouvement.INCONNU
    reference: str | None = Field(default=None, description="Référence bancaire si présente")
    contrepartie: str | None = Field(default=None, description="Bénéficiaire ou émetteur détecté")

    @property
    def montant_signe(self) -> Decimal:
        """Retourne le montant avec signe (+ pour crédit, - pour débit)."""
        if self.credit is not None:
            return self.credit
        if self.debit is not None:
            return -self.debit
        return Decimal("0")


class Releve(BaseModel):
    """Un relevé de compte bancaire normalisé."""

    banque: str = Field(description="Code banque (SG, CA, BOURSO, CE, CM, BNP)")
    iban_masque: str | None = Field(
        default=None,
        description="IBAN partiellement masqué (4 derniers chars visibles)",
    )
    periode_debut: date
    periode_fin: date
    solde_precedent: Decimal
    solde_final: Decimal
    transactions: list[Transaction] = Field(default_factory=list)

    @property
    def total_debits(self) -> Decimal:
        return sum((t.debit or Decimal("0") for t in self.transactions), Decimal("0"))

    @property
    def total_credits(self) -> Decimal:
        return sum((t.credit or Decimal("0") for t in self.transactions), Decimal("0"))

    @property
    def solde_calcule(self) -> Decimal:
        """Solde calculé = solde_precedent + credits − debits.
        Doit matcher solde_final (à centime près) si le parsing est correct.
        """
        return self.solde_precedent + self.total_credits - self.total_debits

    @property
    def ecart_parsing(self) -> Decimal:
        """Écart entre solde_final (extrait) et solde_calcule (somme mouvements).
        Indicateur de qualité du parsing — doit être ≈ 0.
        """
        return (self.solde_final - self.solde_calcule).quantize(Decimal("0.01"))
