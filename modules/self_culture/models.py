"""
Modèles Pydantic v2 pour le module self_culture.

Une `Variete` = une variété cataloguée (issue du YAML de référence ou ajoutée
par l'utilisateur). Chaque variété appartient à une `FamilleBotanique`, ce qui
permet ensuite la validation de rotation pluriannuelle (Solanaceae ne doit pas
revenir 2 ans de suite sur la même planche, etc.).

Périmètre : ce module porte le vocabulaire typé du catalogue de variétés
(enums + modèles `Variete`/`CalendrierCulture`/`RendementReference`). Le schéma
parcelle/plan_culture vit dans cultures.py (CRUD branché sur la DB du hub).
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class FamilleBotanique(StrEnum):
    """Familles botaniques majeures pour la validation de rotation.

    Référence : classification botanique standard (APG IV).
    Utilisée par rotation.py pour détecter les successions à risque.
    """

    SOLANACEAE = "Solanaceae"          # tomate, pomme de terre, aubergine, poivron
    APIACEAE = "Apiaceae"              # carotte, persil, céleri, fenouil
    BRASSICACEAE = "Brassicaceae"      # chou, radis, navet, moutarde
    AMARYLLIDACEAE = "Amaryllidaceae"  # ail, oignon, échalote, poireau
    FABACEAE = "Fabaceae"              # haricot, pois, fève, vesce, luzerne (légumineuses)
    CUCURBITACEAE = "Cucurbitaceae"    # courgette, concombre, courge, melon
    AMARANTHACEAE = "Amaranthaceae"    # betterave, blette, épinards, quinoa
    ASTERACEAE = "Asteraceae"          # salade, chicorée, artichaut
    POACEAE = "Poaceae"                # blé, maïs, seigle, avoine
    LAMIACEAE = "Lamiaceae"            # basilic, menthe, thym, sauge
    BORAGINACEAE = "Boraginaceae"      # phacélie (engrais vert)
    POLYGONACEAE = "Polygonaceae"      # sarrasin, oseille, rhubarbe
    CANNABACEAE = "Cannabaceae"        # chanvre, houblon
    AUTRE = "autre"


class CategorieVariete(StrEnum):
    """Type d'usage d'une variété."""

    LEGUME = "legume"
    FRUIT = "fruit"
    AROMATIQUE = "aromatique"
    GRANDE_CULTURE = "grande_culture"
    ENGRAIS_VERT = "engrais_vert"
    INDUSTRIEL = "industriel"  # ex : chanvre


class Saison(StrEnum):
    PRINTEMPS = "printemps"
    ETE = "ete"
    AUTOMNE = "automne"
    HIVER = "hiver"


class ModeProduction(StrEnum):
    AB = "ab"             # Agriculture biologique
    NT = "nt"             # Non traité
    CONVENTIONNEL = "conv"
    HVE = "hve"           # Haute Valeur Environnementale


class CalendrierCulture(BaseModel):
    """Fenêtres temporelles indicatives pour semis et récolte."""

    model_config = ConfigDict(extra="allow")

    semis_mois_min: int = Field(ge=1, le=12, description="Mois début de fenêtre de semis (1-12)")
    semis_mois_max: int = Field(ge=1, le=12, description="Mois fin de fenêtre de semis (1-12)")
    recolte_mois_min: int = Field(ge=1, le=12, description="Mois début de fenêtre de récolte (1-12)")
    recolte_mois_max: int = Field(ge=1, le=12, description="Mois fin de fenêtre de récolte (1-12)")
    duree_jours_min: int = Field(ge=10, description="Durée mini de culture du semis à la récolte (jours)")
    duree_jours_max: int = Field(ge=10, description="Durée maxi de culture du semis à la récolte (jours)")
    sous_abri: bool = Field(default=False, description="True si la variété est typiquement sous serre/tunnel")


class RendementReference(BaseModel):
    """Rendement de référence en agriculture biologique."""

    model_config = ConfigDict(extra="allow")

    valeur_min_kg_m2: Decimal = Field(ge=0, description="Rendement plancher (kg/m²)")
    valeur_max_kg_m2: Decimal = Field(ge=0, description="Rendement plafond (kg/m²)")
    densite_plants_m2: Decimal = Field(ge=0, description="Plants par m² (densité indicative)")
    source_note: str = Field(default="", description="Origine de la donnée (ITAB, GEVES, terrain…)")


class Variete(BaseModel):
    """Une variété cultivable, issue du catalogue de référence ou perso."""

    model_config = ConfigDict(extra="allow")

    id: str = Field(description="Identifiant slug unique (ex: tomate-marmande-ab)")
    nom_commun: str = Field(description="Nom usuel en français (ex: Tomate Marmande)")
    nom_botanique: str = Field(description="Nom binomial latin (ex: Solanum lycopersicum)")
    famille: FamilleBotanique
    categorie: CategorieVariete
    mode_production_principal: ModeProduction = Field(default=ModeProduction.AB)
    calendrier: CalendrierCulture
    rendement: RendementReference
    saisons_principales: list[Saison] = Field(default_factory=list)
    fournisseurs_recommandes: list[str] = Field(
        default_factory=list,
        description="Sélectionneurs/semenciers (ex: Kokopelli, Genscore, Germinance)",
    )
    notes: str = Field(default="", description="Notes agronomiques libres")


class CatalogueVarietes(BaseModel):
    """Bundle de variétés tel que stocké dans data/varietes-references.yaml."""

    version: str = Field(description="Version du catalogue (ex: 2026-04)")
    licence: str = Field(default="AGPL-3.0-or-later")
    description: str = Field(default="")
    varietes: list[Variete]
