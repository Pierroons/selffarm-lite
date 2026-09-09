"""
Modèles d'une facture REÇUE via une Plateforme Agréée (PA).

Le sens entrant, pas le sortant : ce que `self_factur_x_agri` et le builder de
SelfInvoice construisent pour émettre, ce module le relit pour recevoir.

Une facture reçue vient d'un tiers. On ne maîtrise ni son profil Factur-X, ni son
logiciel d'origine, ni les champs qu'il a jugé bon de remplir. D'où deux partis
pris qui traversent tout le module :

- **les montants sont des `Decimal`**, jamais des `float` — un centime perdu à
  l'arrondi devient une écriture fausse ;
- **presque tout est optionnel.** En profil MINIMUM, une facture Factur-X n'a
  aucune ligne de détail : seuls les totaux existent. Un modèle qui exigerait des
  lignes rejetterait des factures parfaitement valides.

Ce que le module ne fait pas : juger. Le contrôle arithmétique et l'imputation
comptable vivent ailleurs. Ici on lit, et on dit ce qu'on n'a pas trouvé.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class CanalReception(StrEnum):
    """Par où la facture est arrivée.

    Le guide pratique DGFiP du 09/07/2026 (question 6) demande de pouvoir
    justifier le traitement d'une facture reçue « dans des conditions dégradées ».
    Pendant la phase de démarrage, une facture reçue par mail ou papier reste
    payable, comptabilisable et déductible — mais il faut savoir dire par où elle
    est passée.
    """

    PLATEFORME = "plateforme"
    MAIL = "mail"
    PAPIER = "papier"
    SAISIE = "saisie"


class LigneFacture(BaseModel):
    """Une ligne de détail. Absente des profils MINIMUM et BASIC WL."""

    model_config = ConfigDict(extra="allow")

    numero: str = ""
    designation: str = ""
    quantite: Decimal | None = None
    unite: str = ""
    prix_unitaire_ht: Decimal | None = None
    montant_ht: Decimal | None = None
    taux_tva: Decimal | None = None
    categorie_tva: str = Field(default="", description="UNTDID 5305 : S, Z, E, AE…")


class VentilationTva(BaseModel):
    """Un bloc de TVA par taux (`ram:ApplicableTradeTax` au niveau document)."""

    model_config = ConfigDict(extra="allow")

    base_ht: Decimal | None = None
    montant_tva: Decimal | None = None
    taux: Decimal | None = None
    categorie: str = ""
    motif_exoneration: str = ""


class PartieFacture(BaseModel):
    """Émetteur ou destinataire de la facture."""

    model_config = ConfigDict(extra="allow")

    nom: str = ""
    siren: str = Field(default="", description="BT-30, 9 chiffres — pas le SIRET")
    numero_tva: str = ""
    code_postal: str = ""
    ville: str = ""
    pays: str = ""


class FactureRecue(BaseModel):
    """Facture fournisseur reçue, telle que lue — sans jugement de validité.

    `champs_absents` porte ce que la lecture n'a pas trouvé. C'est délibérément un
    constat et non une erreur : une facture au profil MINIMUM sans lignes est
    valide, une facture sans SIREN émetteur ne l'est pas, et ce n'est pas au
    lecteur de trancher. L'imputation lira cette liste pour décider quoi présenter
    à l'humain.
    """

    model_config = ConfigDict(extra="allow")

    numero: str = Field(default="", description="BT-1")
    date_facture: date | None = Field(default=None, description="BT-2")
    type_code: str = Field(default="", description="UNTDID 1001 — 380 = facture")
    devise: str = "EUR"

    emetteur: PartieFacture = Field(default_factory=PartieFacture)
    destinataire: PartieFacture = Field(default_factory=PartieFacture)

    lignes: list[LigneFacture] = Field(default_factory=list)
    ventilation_tva: list[VentilationTva] = Field(default_factory=list)

    total_ht: Decimal | None = Field(default=None, description="BT-109")
    total_tva: Decimal | None = Field(default=None, description="BT-110")
    total_ttc: Decimal | None = Field(default=None, description="BT-112")
    net_a_payer: Decimal | None = Field(default=None, description="BT-115")

    profil: str = Field(default="", description="URN du guideline (BT-24)")
    champs_absents: list[str] = Field(default_factory=list)

    @property
    def cle_metier(self) -> str:
        """Clé de déduplication : SIREN émetteur + numéro de facture.

        Volontairement PAS le hash du fichier. Pendant la transition vers la
        facturation électronique, la même facture arrive par deux canaux — par
        mail en PDF, puis par la plateforme en XML — avec deux empreintes
        différentes. Dédupliquer sur le fichier laisserait passer le doublon, et
        le guide DGFiP en fait le risque numéro un de la période : double
        paiement, double comptabilisation, double déduction de TVA (questions 5
        et 15).

        Deux factures distinctes du même fournisseur ont deux numéros ; deux
        représentations d'une même facture ont le même. C'est la propriété
        recherchée.
        """
        return f"{self.emetteur.siren}:{self.numero}"
