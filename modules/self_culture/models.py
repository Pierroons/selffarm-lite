"""
Modèles Pydantic v2 pour le module self_culture.

Une `Variete` = une variété cataloguée (issue du YAML de référence ou ajoutée
par l'utilisateur). Chaque variété appartient à une `FamilleBotanique`, ce qui
permet ensuite la validation de rotation pluriannuelle (Solanaceae ne doit pas
revenir 2 ans de suite sur la même planche, etc.).

Les modèles `Parcelle`, `Planche`, `PlanCulture`, `AssolementCycle`, `Tache`
sont en draft pour les phases ultérieures et seront enrichis au fur et à mesure.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any

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


# ------------------------------------------------------------------
# Modèles draft pour les phases 2-4 (à étoffer au fur et à mesure)
# ------------------------------------------------------------------


class Parcelle(BaseModel):
    """Parcelle cadastrale (extension de self_parcelles à terme)."""

    model_config = ConfigDict(extra="allow")

    id: int | None = None
    nom: str = Field(description="Nom donné par l'exploitant (ex: 'Le Pré du Bas')")
    code_insee: str = Field(min_length=5, max_length=5, description="Code INSEE 5 chiffres de la commune")
    commune_nom: str = Field(description="Nom de la commune")
    section_cadastre: str = Field(default="", description="Section cadastrale (ex: ZK)")
    parcelle_cadastre: str = Field(default="", description="N° parcelle (ex: 0042)")
    surface_m2: Decimal = Field(ge=0, description="Surface totale en m²")
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class Planche(BaseModel):
    """Subdivision d'une parcelle (planche maraîchère, bloc)."""

    model_config = ConfigDict(extra="allow")

    id: int | None = None
    parcelle_id: int = Field(description="FK vers parcelles.id")
    nom: str = Field(description="Nom court (ex: 'A1', 'Planche Sud')")
    surface_m2: Decimal = Field(ge=0)
    largeur_m: Decimal | None = None
    longueur_m: Decimal | None = None
    abri: bool = Field(default=False, description="True si sous serre/tunnel")
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class PlanCulture(BaseModel):
    """Assignation d'une variété sur une planche pour une campagne donnée."""

    model_config = ConfigDict(extra="allow")

    id: int | None = None
    annee: int = Field(ge=2020, le=2100)
    planche_id: int
    variete_id: str = Field(description="Slug de la variété (FK logique)")
    date_semis_prev: date | None = None
    date_repiquage_prev: date | None = None
    date_recolte_prev: date | None = None
    densite_plants_m2: Decimal | None = None
    rendement_kg_attendu: Decimal | None = None
    notes: str = Field(default="")
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class AssolementCycle(BaseModel):
    """Vue pluriannuelle pour la rotation (parcelle × année × famille)."""

    model_config = ConfigDict(extra="allow")

    id: int | None = None
    parcelle_id: int
    annee: int = Field(ge=2020, le=2100)
    famille_botanique: FamilleBotanique
    culture_principale: str = Field(default="", description="Variété ou culture principale de l'année")
    engrais_vert_intercalaire: str = Field(default="", description="Engrais vert semé après récolte")
    notes: str = Field(default="")


class StatutTache(StrEnum):
    PREVUE = "prevue"
    EN_COURS = "en_cours"
    FAITE = "faite"
    REPORTEE = "reportee"
    ANNULEE = "annulee"


class TypeTache(StrEnum):
    SEMIS = "semis"
    REPIQUAGE = "repiquage"
    DESHERBAGE = "desherbage"
    IRRIGATION = "irrigation"
    TRAITEMENT = "traitement"
    RECOLTE = "recolte"
    CONDITIONNEMENT = "conditionnement"
    AUTRE = "autre"


class Tache(BaseModel):
    """Tâche d'une semaine du planning hebdo."""

    model_config = ConfigDict(extra="allow")

    id: int | None = None
    semaine_iso: str = Field(description="Format AAAA-Wnn (ex: 2026-W22)")
    date_prevue: date
    type: TypeTache
    libelle: str
    plan_culture_id: int | None = None
    duree_min_estimee_min: int | None = None
    duree_min_reelle_min: int | None = None
    affectation: str = Field(default="", description="Personne assignée (utilisateur ou bénévole asso)")
    statut: StatutTache = StatutTache.PREVUE
    done_at: date | None = None
    notes: str = Field(default="")
    metadata_json: dict[str, Any] = Field(default_factory=dict)
