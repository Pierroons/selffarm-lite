"""
Modèles spécifiques Factur-X agricole.

Ces modèles complètent ceux de SelfInvoice avec les spécificités métier agri :
- codes UOM agricoles UN/ECE Recommendation 20
- codes CPV (Common Procurement Vocabulary) pour la PAC
- catégories de produits FranceAgriMer (animal/végétal, bio/conventionnel)
- régime fiscal (micro-BA ou réel agricole) avec code TVA spécial (298 bis CGI)
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class UomAgri(StrEnum):
    """UOM agricoles (UN/ECE Recommendation 20). Tous exclus d'Odoo."""

    HECTARE = "HAR"
    METRE_CARRE = "MTK"
    TONNE = "TNE"
    KILOGRAMME = "KGM"
    LITRE = "LTR"
    NOMBRE_ANIMAUX = "NAR"
    BOTTE = "BX"  # box / botte de foin
    TETE = "HEA"  # head (animal)
    UNIT = "C62"  # unité générique si rien ne matche


class CategorieTvaAgri(StrEnum):
    """Catégories TVA agricoles (fondées sur UNTDID 5305 + spécificités FR).

    S = taux standard (5.5, 10, 20)
    Z = taux zéro
    E = exonérée (hors champ ou exonération spécifique)
    AE = autoliquidation (reverse charge)
    """

    STANDARD = "S"          # 5.5 %, 10 %, 20 %
    ZERO = "Z"
    EXONERE = "E"
    AUTOLIQUIDATION = "AE"


class TauxTvaAgri(BaseModel):
    """Taux de TVA avec catégorie UNTDID et libellé humain."""

    model_config = ConfigDict(frozen=True)

    categorie: CategorieTvaAgri
    taux_pct: Decimal = Field(ge=0, le=100)
    libelle: str
    article_cgi: str | None = None


# Barème TVA agricole FR 2026
TVA_BRUTS_55 = TauxTvaAgri(
    categorie=CategorieTvaAgri.STANDARD,
    taux_pct=Decimal("5.5"),
    libelle="Produits agricoles bruts et denrées alimentaires",
    article_cgi="278-0 bis CGI",
)
TVA_TRANSFORMES_10 = TauxTvaAgri(
    categorie=CategorieTvaAgri.STANDARD,
    taux_pct=Decimal("10"),
    libelle="Produits agricoles non transformés pour usage professionnel / transformés",
    article_cgi="278 bis CGI",
)
TVA_STANDARD_20 = TauxTvaAgri(
    categorie=CategorieTvaAgri.STANDARD,
    taux_pct=Decimal("20"),
    libelle="TVA normale (services, outillage, intrants hors chaîne alim)",
    article_cgi="278 CGI",
)
TVA_MICRO_BA_298BIS = TauxTvaAgri(
    categorie=CategorieTvaAgri.EXONERE,
    taux_pct=Decimal("0"),
    libelle="Régime forfaitaire agricole — non-assujetti TVA",
    article_cgi="298 bis CGI",
)


class ProduitAgriFactor(BaseModel):
    """Un produit agricole tel que facturé (à placer sur un InvoiceLine)."""

    nom: str
    quantite: Decimal = Field(gt=0)
    unite: UomAgri
    prix_unitaire_ht: Decimal = Field(ge=0)
    tva: TauxTvaAgri
    bio: bool = False
    compte_pcg: str = Field(
        description="Compte PCG agricole, ex: 7011 (ventes de produits végétaux)"
    )
    code_cpv: str | None = Field(
        default=None,
        description="Code CPV Common Procurement Vocabulary (optionnel)",
    )
    franceagrimer_categorie: str | None = Field(
        default=None,
        description="Catégorie FranceAgriMer (chanvre_fibre, maraichage_bio, etc.)",
    )

    @property
    def montant_ht(self) -> Decimal:
        return (self.quantite * self.prix_unitaire_ht).quantize(Decimal("0.01"))

    @property
    def montant_tva(self) -> Decimal:
        return (self.montant_ht * self.tva.taux_pct / Decimal("100")).quantize(Decimal("0.01"))

    @property
    def montant_ttc(self) -> Decimal:
        return (self.montant_ht + self.montant_tva).quantize(Decimal("0.01"))
