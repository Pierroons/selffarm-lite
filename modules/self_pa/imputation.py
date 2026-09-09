"""
Contrôle arithmétique et proposition d'écriture pour une facture reçue.

Rien ici n'écrit en comptabilité. Ce module produit une **proposition**, que
`webapp` présentera à côté de la facture pour qu'un humain la valide. C'est le
seul point du dispositif où l'automatisme s'arrête volontairement : une écriture
fausse est pire qu'une écriture absente, parce qu'elle ne se voit pas.

Le contrôle arithmétique est le garde-fou réel. Il est **déterministe** : il
n'accorde aucune confiance à l'origine de la donnée, ni au fournisseur, ni au
format. Une facture dont HT + TVA ≠ TTC est refusée qu'elle vienne d'un XML
signé ou d'une lecture approximative — c'est ce qui rend le dispositif sûr même
le jour où un maillon en amont se trompe.

Deux poids, deux mesures, et c'est délibéré :

- **strict** sur les égalités que la norme EN 16931 impose au centime près
  (BR-CO-15 : BT-112 = BT-109 + BT-110 ; BR-CO-14 : total TVA = Σ des TVA par
  catégorie). Un écart y est une anomalie, pas un arrondi.
- **tolérant à 0,01 €** sur les montants recalculés à partir d'un taux, où
  l'arrondi légal produit un écart légitime.

La somme des lignes, elle, n'est jamais bloquante : une remise globale ou des
frais de port créent un écart parfaitement normal entre BT-106 et BT-109.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from self_pa.models import FactureRecue

log = logging.getLogger("selffarm.self_pa.imputation")

# Écart admis sur un montant recalculé depuis un taux. La norme tolère l'arrondi
# au centime ; au-delà, ce n'est plus un arrondi.
TOLERANCE = Decimal("0.01")

COMPTE_FOURNISSEURS = "401"
JOURNAL_ACHATS = "ACH"


class Gravite(StrEnum):
    BLOQUANT = "bloquant"
    AVERTISSEMENT = "avertissement"


class Anomalie(BaseModel):
    """Un constat sur la facture. `code` sert aux tests et aux filtres, `message`
    est lu par l'humain qui validera."""

    model_config = ConfigDict(extra="allow")

    code: str
    message: str
    gravite: Gravite = Gravite.BLOQUANT


class LigneImputation(BaseModel):
    """Une écriture proposée, dans la forme que `save_ecriture()` attend.

    Une facture ventilée sur plusieurs comptes de charge produit plusieurs
    lignes — d'où `source_id` suffixé par le compte, comme le fait déjà
    `webapp/routes/invoice.py` pour les ventes multi-natures.
    """

    model_config = ConfigDict(extra="allow")

    compte_debit: str
    compte_credit: str = COMPTE_FOURNISSEURS
    montant_ht: Decimal
    montant_tva: Decimal
    montant_ttc: Decimal
    libelle: str
    source_id: str


class Imputation(BaseModel):
    """Proposition complète pour une facture."""

    model_config = ConfigDict(extra="allow")

    lignes: list[LigneImputation] = Field(default_factory=list)
    anomalies: list[Anomalie] = Field(default_factory=list)
    journal: str = JOURNAL_ACHATS

    @property
    def proposable(self) -> bool:
        """Vrai si aucune anomalie bloquante — donc si l'humain peut se voir
        présenter une écriture plutôt qu'un problème à trancher."""
        return not any(a.gravite is Gravite.BLOQUANT for a in self.anomalies)


def controler(facture: FactureRecue) -> list[Anomalie]:
    """Vérifie l'arithmétique de la facture. Liste vide = rien à signaler."""
    anomalies: list[Anomalie] = []

    # --- Identité : sans ces trois champs, aucune écriture n'est possible ---
    if not facture.numero:
        anomalies.append(Anomalie(code="numero_absent", message="Facture sans numéro."))
    if not facture.emetteur.siren:
        anomalies.append(
            Anomalie(
                code="siren_absent",
                message="SIREN de l'émetteur absent — la déduplication et le "
                        "compte fournisseur en dépendent.",
            )
        )
    if facture.date_facture is None:
        anomalies.append(
            Anomalie(code="date_absente", message="Date de facture absente.")
        )

    ht, tva, ttc = facture.total_ht, facture.total_tva, facture.total_ttc
    if ttc is None:
        anomalies.append(
            Anomalie(code="ttc_absent", message="Montant TTC absent ou illisible.")
        )
    if ht is None:
        anomalies.append(
            Anomalie(code="ht_absent", message="Montant HT absent ou illisible.")
        )

    # --- BR-CO-15 : TTC = HT + TVA, au centime près ---
    if ht is not None and ttc is not None:
        tva_effective = tva if tva is not None else Decimal(0)
        attendu = ht + tva_effective
        if attendu != ttc:
            anomalies.append(
                Anomalie(
                    code="totaux_incoherents",
                    message=(
                        f"HT + TVA ≠ TTC : {ht} + {tva_effective} = {attendu}, "
                        f"or la facture annonce {ttc} "
                        f"(écart de {(ttc - attendu):+})."
                    ),
                )
            )

    # --- BR-CO-14 : total TVA = somme des TVA par catégorie ---
    if tva is not None and facture.ventilation_tva:
        montants = [v.montant_tva for v in facture.ventilation_tva if v.montant_tva is not None]
        if len(montants) == len(facture.ventilation_tva):
            somme = sum(montants, Decimal(0))
            if somme != tva:
                anomalies.append(
                    Anomalie(
                        code="ventilation_tva_incoherente",
                        message=(
                            f"Somme des TVA par taux = {somme}, "
                            f"total TVA annoncé = {tva}."
                        ),
                    )
                )

    # --- Cohérence taux × base, avec la tolérance d'arrondi ---
    for v in facture.ventilation_tva:
        if v.base_ht is None or v.taux is None or v.montant_tva is None:
            continue
        attendu = (v.base_ht * v.taux / Decimal(100)).quantize(Decimal("0.01"))
        if abs(attendu - v.montant_tva) > TOLERANCE:
            anomalies.append(
                Anomalie(
                    code="taux_incoherent",
                    message=(
                        f"TVA à {v.taux} % sur une base de {v.base_ht} devrait "
                        f"faire {attendu}, la facture annonce {v.montant_tva}."
                    ),
                )
            )

    # --- Lignes vs total : informatif, jamais bloquant ---
    montants_lignes = [ln.montant_ht for ln in facture.lignes if ln.montant_ht is not None]
    if ht is not None and montants_lignes and len(montants_lignes) == len(facture.lignes):
        somme = sum(montants_lignes, Decimal(0))
        if somme != ht:
            anomalies.append(
                Anomalie(
                    code="ecart_lignes_total",
                    message=(
                        f"Somme des lignes = {somme}, total HT = {ht} "
                        f"(écart de {(ht - somme):+}). Une remise globale ou des "
                        "frais de port l'expliquent — à vérifier."
                    ),
                    gravite=Gravite.AVERTISSEMENT,
                )
            )

    return anomalies


def analyser(facture: FactureRecue) -> Imputation:
    """Contrôle seul, sans écriture — l'état d'une facture à sa réception.

    Le compte de charge n'est pas connu au moment où la facture arrive : il se
    choisit à la validation, quand un humain regarde. Cette fonction produit donc
    le verdict arithmétique et rien d'autre, ce qui suffit à décider si la
    facture peut être présentée pour imputation ou doit être signalée.
    """
    return Imputation(anomalies=controler(facture))


def proposer(facture: FactureRecue, compte_charge: str) -> Imputation:
    """Facture reçue → écriture d'achat proposée.

    `compte_charge` n'a pas de valeur par défaut, et c'est voulu : deviner un
    compte de charge produirait une écriture plausible et fausse, exactement le
    genre d'erreur qui traverse un bilan sans être vue. Le compte vient du
    fournisseur connu ou de l'humain.

    Schéma d'achat : le compte de charge au débit, le fournisseur (401) au
    crédit, la TVA déductible portée par `montant_tva` — la forme employée par
    les écritures existantes (`webapp/routes/invoice.py`, `self_pos/services.py`).
    """
    anomalies = controler(facture)
    imputation = Imputation(anomalies=anomalies)

    if not imputation.proposable:
        log.info(
            "Facture %s : %d anomalie(s) bloquante(s), aucune écriture proposée",
            facture.cle_metier,
            sum(1 for a in anomalies if a.gravite is Gravite.BLOQUANT),
        )
        return imputation

    # `proposable` garantit la présence de HT et TTC ; la TVA peut légitimement
    # être nulle (franchise en base, autoliquidation).
    assert facture.total_ht is not None and facture.total_ttc is not None
    tva = facture.total_tva if facture.total_tva is not None else Decimal(0)

    libelle = f"Achat {facture.emetteur.nom or facture.emetteur.siren} — {facture.numero}"
    imputation.lignes.append(
        LigneImputation(
            compte_debit=compte_charge,
            montant_ht=facture.total_ht,
            montant_tva=tva,
            montant_ttc=facture.total_ttc,
            libelle=libelle,
            source_id=f"{facture.cle_metier}#{compte_charge}",
        )
    )
    log.info(
        "Facture %s : écriture proposée %s → %s pour %s",
        facture.cle_metier, compte_charge, COMPTE_FOURNISSEURS, facture.total_ttc,
    )
    return imputation
