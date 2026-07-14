"""
Modèles de données pour le prévisionnel DNJA/DJA.

Ces modèles formalisent les hypothèses d'installation que le candidat JA
produit lors de la phase prévisionnel : activités, recettes, charges,
immobilisations, aides. Le moteur (engine.py) s'appuie dessus pour produire
les comptes de résultat prévisionnels année par année.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, Field, model_validator


class RegimeFiscal(StrEnum):
    MICRO_BA = "micro-ba"
    REEL_SIMPLIFIE = "reel-simplifie"
    REEL_NORMAL = "reel-normal"


class StatutJuridique(StrEnum):
    INDIVIDUEL = "entreprise-individuelle"
    EARL = "earl"
    GAEC = "gaec"
    SCEA = "scea"
    EURL = "eurl"


class Activite(BaseModel):
    """Une activité productive (ex : maraîchage bio, chanvre CBD)."""

    nom: str
    surface_ha: Decimal = Field(ge=0, description="Surface exploitée en hectares")
    rendement_t_ha: Decimal | None = Field(
        default=None, ge=0, description="Rendement prévisionnel t/ha (facultatif)"
    )
    prix_vente_ht: Decimal = Field(
        ge=0, description="Prix de vente moyen HT par unité (€)"
    )
    unite_vente: str = Field(default="kg", description="Unité de vente (kg, t, bouquet…)")
    quantite_annuelle: Decimal | None = Field(
        default=None, ge=0, description="Quantité vendable annuelle (unité). Prio sur rendement×surface."
    )
    capacite_annuelle: Decimal | None = Field(
        default=None, ge=0,
        description="Capacité de production annuelle réelle (≥ quantité déclarée vendue). "
                    "L'écart capacité − vendu = stock de réserve non engagé. Annexe interne de pilotage.",
    )
    bio: bool = False
    annee_pleine_production: int = Field(
        ge=1, le=10, description="À partir de quelle année le plein régime est atteint"
    )
    montee_en_charge: list[Decimal] = Field(
        default_factory=lambda: [Decimal("0.5"), Decimal("0.75"), Decimal("1.0"), Decimal("1.0")],
        description="Facteur de charge N+1..N+4 (0..1). Ex: [0.3, 0.6, 1.0, 1.0].",
    )

    @model_validator(mode="after")
    def _check_quantity_inputs(self) -> Self:
        if self.quantite_annuelle is None and self.rendement_t_ha is None:
            raise ValueError(
                f"Activité '{self.nom}' : fournis soit `quantite_annuelle` "
                f"soit `rendement_t_ha` + `surface_ha`."
            )
        return self


class ChargeRecurrente(BaseModel):
    """Charge d'exploitation récurrente (intrants, mécanisation, etc.)."""

    nom: str
    montant_annuel_ht: Decimal = Field(ge=0)
    categorie: str = Field(
        description="Ex: 'intrants', 'mecanisation', 'eau', 'assurance', 'foncier'"
    )
    annee_demarrage: int = Field(
        default=1, ge=1, le=10,
        description="Année à partir de laquelle la charge commence (1 = dès installation)",
    )
    annee_fin: int | None = Field(
        default=None, ge=1, le=10,
        description="Dernière année où la charge s'applique (incluse). None = jusqu'à l'horizon. "
        "Permet une charge ponctuelle (ex: annee_demarrage = annee_fin = 1 → charge N1 seulement).",
    )


class Immobilisation(BaseModel):
    """Investissement amortissable (matériel, bâtiment, etc.)."""

    nom: str
    montant_ht: Decimal = Field(ge=0)
    annee_acquisition: int = Field(ge=1, le=10)
    duree_amortissement: int = Field(ge=1, le=30, description="Durée d'amortissement (années)")
    subvention_pct: Decimal = Field(
        default=Decimal("0"), ge=0, le=100,
        description="Part subventionnée (ex: 40%), réduit l'assiette amortissable"
    )


class Aide(BaseModel):
    """Aide publique (DJA, écorégime, AITA, CI bio, etc.)."""

    nom: str
    montant: Decimal = Field(ge=0)
    annee_versement: int = Field(ge=1, le=10)
    est_subvention_capital: bool = Field(
        default=False,
        description="True = subvention d'équipement (pas dans le résultat), "
                    "False = aide revenu (intégrée au résultat)"
    )


class CotisationsMSA(BaseModel):
    """Cotisations MSA selon statut JA."""

    exoneration_ja_active: bool = True
    pct_exoneration: list[Decimal] = Field(
        default_factory=lambda: [
            Decimal("65"), Decimal("55"), Decimal("35"), Decimal("25"), Decimal("15")
        ],
        description="Taux d'exonération N+1..N+5 (par défaut barème 2026)"
    )
    cotisation_base_annuelle: Decimal = Field(
        default=Decimal("4500"),
        description="Cotisation MSA annuelle estimée sans exonération JA"
    )


class Salariat(BaseModel):
    """Maintien d'une activité salariée parallèle."""

    salaire_net_mensuel: Decimal = Field(default=Decimal("0"), ge=0)
    fin_prevue_annee: int | None = Field(
        default=None, description="Année où le salariat s'arrête (None = jamais)"
    )


class TempsTravail(BaseModel):
    """Répartition annuelle des heures UTH (cible 1800 h/an pour 1 UTH)."""

    chanvre_culture: int = Field(default=0, ge=0, description="heures")
    transformation_huile: int = Field(default=0, ge=0)
    maraichage: int = Field(default=0, ge=0)
    vente_admin: int = Field(default=0, ge=0)
    autre: int = Field(default=0, ge=0)

    @property
    def total(self) -> int:
        return self.chanvre_culture + self.transformation_huile + self.maraichage + self.vente_admin + self.autre


class EvenementCalendrier(BaseModel):
    """Un événement du calendrier cultural annuel."""

    mois: str = Field(description="Ex: 'mars', 'avril-mai', 'octobre'")
    activite: str = Field(description="Ex: 'Semis chanvre', 'Récolte fleurs CBD'")
    duree: str = Field(default="", description="Ex: '2 semaines', '1 jour'")


class Hypotheses(BaseModel):
    """Bundle complet d'hypothèses pour un prévisionnel DNJA."""

    candidat: str = Field(description="Nom du candidat (ex: 'Pierroons')")
    date_installation: date
    adresse_exploitation: str | None = Field(default=None, description="Ex: '12 rue des Champs'")
    code_postal: str | None = Field(default=None, description="Ex: '33220'")
    commune: str
    departement: str
    statut_juridique: StatutJuridique
    regime_fiscal: RegimeFiscal
    horizon_annees: int = Field(default=4, ge=3, le=5, description="Horizon du prévisionnel")
    activites: list[Activite] = Field(min_length=1)
    charges_recurrentes: list[ChargeRecurrente] = Field(default_factory=list)
    immobilisations: list[Immobilisation] = Field(default_factory=list)
    aides: list[Aide] = Field(default_factory=list)
    cotisations_msa: CotisationsMSA = Field(default_factory=CotisationsMSA)
    salariat: Salariat = Field(default_factory=Salariat)
    uth: Decimal = Field(default=Decimal("1"), ge=Decimal("0.1"), le=Decimal("5"),
                          description="Unités Travail Humain (1 = exploitant seul plein-temps)")

    # --- Enrichissements v0.2 (prélèvements, impôt, calendrier, temps UTH) ---
    prelevements_mensuels: Decimal = Field(
        default=Decimal("1500"),
        ge=0,
        description="Prélèvements privés mensuels exploitant (salaire de vie)",
    )
    article_73b_actif: bool = Field(
        default=True,
        description="Abattement JA 50 % sur bénéfice agricole 5 premières années",
    )
    temps_travail: TempsTravail | None = None
    calendrier_cultural: list[EvenementCalendrier] = Field(default_factory=list)

    # --- Composantes RDA (Annexe 4 CdC DNJA) ---
    annuites_emprunts_annuelles: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        description="Annuités emprunts LT/MT qui réduisent le RDA (crédit moyen/long terme)",
    )
    frais_financiers_ct_annuels: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        description="Frais financiers des dettes court terme (agios, découverts)",
    )
    produits_financiers_ct_annuels: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        description="Produits financiers court terme (placements trésorerie)",
    )

    # --- Présentation & financement ---
    presentation_narrative: str = Field(
        default="",
        description="Présentation narrative exploitation (motivations, parcours, stratégie)",
    )
    plan_financement_apport_personnel: Decimal = Field(default=Decimal("0"), ge=0)
    plan_financement_emprunt: Decimal = Field(default=Decimal("0"), ge=0)
    bfr_besoin: Decimal = Field(
        default=Decimal("3000"),
        ge=0,
        description="BFR : fonds pour stocks en cours + créances clients avant encaissement",
    )
    tresorerie_securite: Decimal = Field(
        default=Decimal("3000"),
        ge=0,
        description="Matelas de trésorerie à conserver (sécurité aléas)",
    )

    # --- Engagements réglementaires DNJA ---
    choix_eco_conditionnalite: str = Field(
        default="AB_97pct",
        description="Un des 3 critères éco-conditionnalité DNJA : AB_97pct | ecoregime_bio | HVE",
    )
    structure_etude_economique: str = Field(
        default="",
        description="Structure agréée Région NA retenue pour l'étude économique AITA",
    )
    date_affiliation_msa_prevue: date | None = Field(
        default=None,
        description="Date prévue d'affiliation MSA chef exploitation (< 6 mois post-attribution aide)",
    )
    afficher_engagements_reglementaires: bool = Field(
        default=True,
        description="Afficher la section 15 « Engagements réglementaires DNJA » dans le PDF (off pour version Chambre)",
    )
    afficher_memos_pedagogiques: bool = Field(
        default=True,
        description="Afficher l'annexe finale « Mémos de lecture » (formules CAF, marge brute, tréso) — off pour version Chambre",
    )
    afficher_reserve_production: bool = Field(
        default=False,
        description="Affiche l'annexe « Capacité de production & stock de réserve » (écart capacité − vendu). "
                    "⚠️ Pilotage interne uniquement — laisser False pour la version remise à la DDT.",
    )
    afficher_note_methodologique: bool = Field(
        default=True,
        description="Afficher la note méthodologique de fin (outil self-dnja, disclaimer AITA) — off pour version Chambre épurée",
    )
    afficher_pied_de_page: bool = Field(
        default=True,
        description="Afficher les en-tête/pied de page (pagination + candidat + date) — off pour version Chambre épurée",
    )

    # --- Modalités versement DJA (titre principal vs installation progressive) ---
    dnja_acompte_pct: int = Field(
        default=80,
        ge=0,
        le=100,
        description="% de la DNJA versé en acompte à l'installation (80 titre principal, 60 progressive)",
    )
    dnja_annee_solde: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Année de versement du solde DNJA (solde = 100 − acompte %), défaut 5e année",
    )


class LigneResultat(BaseModel):
    """Ligne de compte de résultat prévisionnel pour une année donnée."""

    annee: int
    produits_exploitation: Decimal
    charges_exploitation: Decimal
    amortissements: Decimal
    charges_sociales: Decimal
    aides_revenu: Decimal
    ebe: Decimal  # Excédent brut d'exploitation
    resultat: Decimal  # Résultat courant avant impôts
    salaire_net_disponible: Decimal  # EBE - MSA - annuités (si prêt) = revenu dispo

    # --- Enrichissements v0.2 ---
    ir_estime: Decimal = Field(default=Decimal("0"))
    resultat_net_apres_ir: Decimal = Field(default=Decimal("0"))
    prelevements_annuels: Decimal = Field(default=Decimal("0"))
    revenu_disponible_mensuel: Decimal = Field(default=Decimal("0"))

    # --- Critère officiel DNJA (CdC V3 Annexe 4) ---
    # RDA = EBE + produits fin CT − annuités emprunts LT/MT − frais fin dettes CT
    rda: Decimal = Field(
        default=Decimal("0"),
        description="Revenu Disponible Agricole — critère officiel DNJA (Annexe 4 CdC V3)",
    )


class Ratios(BaseModel):
    """Ratios économiques clés N+4."""

    taux_marge_ebe_pct: Decimal  # EBE / CA × 100
    ca_par_uth: Decimal  # CA / UTH
    poids_aides_pct: Decimal  # aides / CA × 100
    prelevements_sur_ebe_pct: Decimal  # prélèvements / EBE × 100


class ScenarioStress(BaseModel):
    """Un scénario de stress test (CA ou prix baissés)."""

    nom: str
    description: str
    ebe_n4: Decimal
    resultat_n4: Decimal
    ebe_uth_n4: Decimal
    seuil_dnja_tenu: bool


class BilanSimplifie(BaseModel):
    """Bilan prévisionnel simplifié à fin d'exercice N+4."""

    # Actif
    immobilisations_nettes: Decimal
    stocks: Decimal
    creances: Decimal
    tresorerie: Decimal
    total_actif: Decimal
    # Passif
    capital_exploitant: Decimal
    subventions_etalees: Decimal
    dettes: Decimal
    total_passif: Decimal


class MargeBruteActivite(BaseModel):
    """Marge brute par activité (plein régime N+4)."""

    nom: str
    ca_annuel: Decimal
    charges_variables_allouees: Decimal
    marge_brute: Decimal
    taux_marge_pct: Decimal


class PlanFinancement(BaseModel):
    """Plan de financement initial équilibré."""

    # Besoins
    capex_total: Decimal
    bfr: Decimal
    tresorerie_securite: Decimal
    total_besoins: Decimal

    # Ressources
    dnja: Decimal  # DNJA TOTALE (acompte + solde)
    dnja_acompte: Decimal = Decimal("0")  # 80 % versé à l'installation
    dnja_solde: Decimal = Decimal("0")  # 20 % versé à l'issue 5e année
    dnja_annee_solde: int = 5
    apport_personnel: Decimal
    emprunt: Decimal
    subventions_capital: Decimal
    total_ressources: Decimal

    # Équilibre
    ecart: Decimal  # ressources - besoins (positif = marge, négatif = trou à combler)


class MoisTresorerie(BaseModel):
    """Un mois du plan de trésorerie."""

    mois_num: int  # 1 à 12
    annee: int  # 1 à horizon
    label: str  # "N+1 janvier", "N+2 mai", etc.
    entrees: Decimal
    sorties: Decimal
    solde_du_mois: Decimal
    solde_cumule: Decimal


class SeuilRentabilite(BaseModel):
    """Seuil de rentabilité calculé à partir des charges fixes."""

    charges_fixes_annuelles: Decimal  # structure + admin + assurances + loyer
    taux_marge_sur_couts_variables: Decimal  # %
    ca_seuil: Decimal  # CA mini pour couvrir charges fixes
    couverture_actuelle_pct: Decimal  # CA N+4 / CA seuil × 100


class PrevisionnelDnja(BaseModel):
    """Résultat complet du moteur de prévisionnel."""

    version: str
    genere_le: date
    hypotheses: Hypotheses
    lignes: list[LigneResultat]
    ebe_uth_atteint: bool  # True si EBE/UTH >= seuil DNJA à l'année cible
    ebe_uth_seuil: Decimal
    ebe_uth_annee_cible: Decimal

    # --- Enrichissements v0.2 ---
    ratios_n4: Ratios | None = None
    scenarios_stress: list[ScenarioStress] = Field(default_factory=list)
    bilan_n4: BilanSimplifie | None = None

    # --- Enrichissements v0.3 ---
    marges_brutes_n4: list[MargeBruteActivite] = Field(default_factory=list)
    plan_financement: PlanFinancement | None = None
    plan_tresorerie: list[MoisTresorerie] = Field(default_factory=list)
    seuil_rentabilite: SeuilRentabilite | None = None
    caf_annuelles: dict[int, Decimal] = Field(default_factory=dict)
