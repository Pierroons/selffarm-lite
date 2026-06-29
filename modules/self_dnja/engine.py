"""
Moteur de calcul du prévisionnel DNJA/DJA.

Prend en entrée un objet Hypotheses et produit un PrevisionnelDnja complet
avec les comptes de résultat année par année + vérification du seuil
EBE/UTH attendu par la DDT.

Sources primaires consultées :
- Seuil EBE/UTH DNJA : https://les-aides.nouvelle-aquitaine.fr/
- Exonération MSA JA : https://www.msa.fr/ (barème JA 2026)
- PCG agricole : https://www.anc.gouv.fr/
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal, getcontext

from self_dnja import __version__
from self_dnja.models import (
    Activite,
    BilanSimplifie,
    Hypotheses,
    LigneResultat,
    MargeBruteActivite,
    MoisTresorerie,
    PlanFinancement,
    PrevisionnelDnja,
    Ratios,
    ScenarioStress,
    SeuilRentabilite,
)

# Précision financière suffisante pour nos montants
getcontext().prec = 18

log = logging.getLogger("self-dnja")

# SMIC annuel brut 2026 (1 801,80 €/mois × 12) — conservé pour information.
SMIC_ANNUEL_BRUT_2026 = Decimal("21621.60")

# Seuil RDA DNJA appliqué pour l'instruction (Revenu Disponible Agricole, année cible).
# Source : valeur (17 717 €/an, année cible) communiquée pour un dossier par une
# Chambre d'agriculture via une étude PROAGRI. Cas particulier, NON généralisable
# (peut varier selon département / région) et non vérifié au texte officiel.
# ⚠️ À CONFIRMER (CdC DNJA V3 / Région concernée) avant tout usage normatif.
# NB : ce seuil s'applique au RDA *après* cotisations sociales exploitant (méthode PROAGRI).
EBE_UTH_SEUIL_DNJA_NA_2026 = Decimal("17717")

# Barème IR 2026 par part (simplifié, célibataire, sans réduction spécifique)
IR_TRANCHES_2026 = [
    (Decimal("11497"), Decimal("0")),       # tranche à 0 %
    (Decimal("29315"), Decimal("0.11")),    # 11 %
    (Decimal("83823"), Decimal("0.30")),    # 30 %
    (Decimal("180294"), Decimal("0.41")),   # 41 %
    (Decimal("99999999"), Decimal("0.45")), # 45 %
]


def _impot_ir(base_imposable: Decimal) -> Decimal:
    """Calcul IR progressif simplifié (part unique célibataire)."""
    if base_imposable <= 0:
        return Decimal("0")
    impot = Decimal("0")
    precedent = Decimal("0")
    for plafond, taux in IR_TRANCHES_2026:
        if base_imposable <= precedent:
            break
        tranche = min(base_imposable, plafond) - precedent
        impot += tranche * taux
        precedent = plafond
        if base_imposable <= plafond:
            break
    return impot.quantize(Decimal("0.01"))


def _produit_activite_annee(activite: Activite, annee: int) -> Decimal:
    """Calcule le chiffre d'affaires HT d'une activité pour une année donnée."""
    idx = annee - 1
    if idx < len(activite.montee_en_charge):
        facteur = activite.montee_en_charge[idx]
    else:
        facteur = activite.montee_en_charge[-1]

    if activite.quantite_annuelle is not None:
        quantite = activite.quantite_annuelle
    else:
        # rendement_t_ha × surface_ha → conversion tonnes → kg (×1000)
        quantite = (activite.rendement_t_ha or Decimal("0")) * activite.surface_ha * Decimal("1000")

    return (quantite * activite.prix_vente_ht * facteur).quantize(Decimal("0.01"))


def _charges_recurrentes_annee(h: Hypotheses, annee: int) -> Decimal:
    """Somme des charges d'exploitation récurrentes pour l'année donnée,
    en tenant compte de l'année de démarrage de chaque charge."""
    return sum(
        (c.montant_annuel_ht for c in h.charges_recurrentes
         if c.annee_demarrage <= annee),
        Decimal("0"),
    )


def _amortissements_annee(h: Hypotheses, annee: int) -> Decimal:
    """Somme des amortissements linéaires pour l'année donnée."""
    total = Decimal("0")
    for imm in h.immobilisations:
        if annee < imm.annee_acquisition:
            continue
        age = annee - imm.annee_acquisition
        if age >= imm.duree_amortissement:
            continue
        assiette = imm.montant_ht * (Decimal("100") - imm.subvention_pct) / Decimal("100")
        total += (assiette / Decimal(imm.duree_amortissement)).quantize(Decimal("0.01"))
    return total


def _charges_sociales_annee(h: Hypotheses, annee: int) -> Decimal:
    """Cotisations MSA, avec exonération JA si active."""
    base = h.cotisations_msa.cotisation_base_annuelle
    if not h.cotisations_msa.exoneration_ja_active:
        return base
    if annee <= len(h.cotisations_msa.pct_exoneration):
        pct = h.cotisations_msa.pct_exoneration[annee - 1]
    else:
        pct = Decimal("0")
    exo = base * pct / Decimal("100")
    return (base - exo).quantize(Decimal("0.01"))


def _aides_revenu_annee(h: Hypotheses, annee: int) -> Decimal:
    """Aides versées cette année, uniquement celles comptées en revenu."""
    total = Decimal("0")
    for aide in h.aides:
        if aide.annee_versement == annee and not aide.est_subvention_capital:
            total += aide.montant
    return total


def calculer(h: Hypotheses, include_enrichissements: bool = True) -> PrevisionnelDnja:
    """Produit le prévisionnel complet depuis les hypothèses."""
    log.info("Calcul prévisionnel pour %s (%s), horizon %d ans",
             h.candidat, h.commune, h.horizon_annees)

    lignes: list[LigneResultat] = []
    prelevements_annuels = h.prelevements_mensuels * Decimal("12")

    for annee in range(1, h.horizon_annees + 1):
        produits = sum(
            (_produit_activite_annee(a, annee) for a in h.activites),
            Decimal("0"),
        )
        charges = _charges_recurrentes_annee(h, annee)
        amort = _amortissements_annee(h, annee)
        social = _charges_sociales_annee(h, annee)
        aides = _aides_revenu_annee(h, annee)

        ebe = produits - charges + aides
        resultat = ebe - amort - social
        salaire_net_dispo = ebe - social

        # --- RDA (Revenu Disponible Agricole) — Annexe 4 CdC DNJA V3 ---
        # RDA = EBE + produits fin CT − annuités emprunts LT/MT − frais fin dettes CT
        #       − cotisations sociales exploitant (MSA)
        # Les cotisations MSA de l'exploitant sont déduites pour obtenir le revenu
        # réellement disponible — conforme à la présentation PROAGRI/CER de la Chambre
        # (leur EBE est net de MSA exploitant).
        rda = (
            ebe
            + h.produits_financiers_ct_annuels
            - h.annuites_emprunts_annuelles
            - h.frais_financiers_ct_annuels
            - social
        ).quantize(Decimal("0.01"))

        # --- IR JA art 73 B (50 % abattement 5 premières années) ---
        base_imposable = resultat * Decimal("0.5") if h.article_73b_actif else resultat
        base_imposable = max(base_imposable, Decimal("0"))
        ir = _impot_ir(base_imposable)
        resultat_net = (resultat - ir).quantize(Decimal("0.01"))

        # --- Revenu disponible mensuel (EBE - MSA - IR) / 12 ---
        revenu_dispo_mensuel = ((ebe - social - ir) / Decimal("12")).quantize(Decimal("0.01"))

        lignes.append(LigneResultat(
            annee=annee,
            produits_exploitation=produits.quantize(Decimal("0.01")),
            charges_exploitation=charges.quantize(Decimal("0.01")),
            amortissements=amort.quantize(Decimal("0.01")),
            charges_sociales=social.quantize(Decimal("0.01")),
            aides_revenu=aides.quantize(Decimal("0.01")),
            ebe=ebe.quantize(Decimal("0.01")),
            resultat=resultat.quantize(Decimal("0.01")),
            salaire_net_disponible=salaire_net_dispo.quantize(Decimal("0.01")),
            ir_estime=ir,
            resultat_net_apres_ir=resultat_net,
            prelevements_annuels=prelevements_annuels.quantize(Decimal("0.01")),
            revenu_disponible_mensuel=revenu_dispo_mensuel,
            rda=rda,
        ))
        log.debug("Année %d: produits=%s charges=%s EBE=%s résultat=%s IR=%s",
                  annee, produits, charges, ebe, resultat, ir)

    annee_cible = h.horizon_annees
    # Critère officiel CdC DNJA V3 : RDA ≥ 1 SMIC annuel en dernière année
    # En société RDA se divise par nombre d'associés exploitants ; ici UTH=1 => RDA tel quel
    rda_cible = lignes[-1].rda
    ebe_uth = (rda_cible / h.uth).quantize(Decimal("0.01"))
    atteint = ebe_uth >= EBE_UTH_SEUIL_DNJA_NA_2026

    log.info("RDA année %d / UTH = %s € (seuil DNJA NA 2026 = %s €) → %s",
             annee_cible, ebe_uth, EBE_UTH_SEUIL_DNJA_NA_2026,
             "OK" if atteint else "INSUFFISANT")

    previ = PrevisionnelDnja(
        version=__version__,
        genere_le=date.today(),
        hypotheses=h,
        lignes=lignes,
        ebe_uth_atteint=atteint,
        ebe_uth_seuil=EBE_UTH_SEUIL_DNJA_NA_2026,
        ebe_uth_annee_cible=ebe_uth,
    )

    if include_enrichissements:
        previ.ratios_n4 = _calculer_ratios(h, lignes[-1])
        previ.scenarios_stress = _calculer_scenarios_stress(h)
        previ.bilan_n4 = _calculer_bilan_n4(h, lignes)
        previ.marges_brutes_n4 = _calculer_marges_brutes(h, lignes[-1])
        previ.plan_financement = _calculer_plan_financement(h)
        previ.plan_tresorerie = _calculer_plan_tresorerie(h, lignes)
        previ.seuil_rentabilite = _calculer_seuil_rentabilite(h, lignes[-1])
        previ.caf_annuelles = {
            l.annee: (l.resultat + l.amortissements).quantize(Decimal("0.01"))
            for l in lignes
        }

    return previ


def _calculer_marges_brutes(h: Hypotheses, ligne_n4: LigneResultat) -> list[MargeBruteActivite]:
    """Marge brute par activité : CA activité - charges variables allouées au prorata CA."""
    out = []
    ca_total = ligne_n4.produits_exploitation
    # On considère comme "charges variables" les catégories : intrants, intrants-transformation,
    # labo-certification, conditionnement, commercialisation. Les autres (foncier, assurance,
    # certification, administratif, mécanisation, énergie) sont fixes.
    categories_variables = {
        "intrants", "intrants-transformation", "labo-certification",
        "conditionnement", "commercialisation",
    }
    charges_variables_total = sum(
        (c.montant_annuel_ht for c in h.charges_recurrentes
         if c.categorie in categories_variables and c.annee_demarrage <= ligne_n4.annee),
        Decimal("0"),
    )
    for act in h.activites:
        ca_act = _produit_activite_annee(act, ligne_n4.annee)
        if ca_total > 0:
            part_charges = (charges_variables_total * ca_act / ca_total).quantize(Decimal("0.01"))
        else:
            part_charges = Decimal("0")
        marge = (ca_act - part_charges).quantize(Decimal("0.01"))
        taux = (marge / ca_act * Decimal("100")).quantize(Decimal("0.1")) if ca_act > 0 else Decimal("0")
        out.append(MargeBruteActivite(
            nom=act.nom,
            ca_annuel=ca_act,
            charges_variables_allouees=part_charges,
            marge_brute=marge,
            taux_marge_pct=taux,
        ))
    return out


def _calculer_plan_financement(h: Hypotheses) -> PlanFinancement:
    """Plan de financement initial : besoins vs ressources."""
    capex = sum((i.montant_ht for i in h.immobilisations), Decimal("0"))
    subv_capital = sum(
        (i.montant_ht * i.subvention_pct / Decimal("100") for i in h.immobilisations),
        Decimal("0"),
    )
    total_besoins = (capex + h.bfr_besoin + h.tresorerie_securite).quantize(Decimal("0.01"))

    dnja_cash = sum(
        (a.montant for a in h.aides if "DNJA" in a.nom.upper() and a.annee_versement == 1),
        Decimal("0"),
    )
    total_ressources = (
        dnja_cash + h.plan_financement_apport_personnel
        + h.plan_financement_emprunt + subv_capital
    ).quantize(Decimal("0.01"))

    dnja_acompte = (dnja_cash * Decimal(h.dnja_acompte_pct) / Decimal("100")).quantize(Decimal("0.01"))
    dnja_solde = (dnja_cash * Decimal(100 - h.dnja_acompte_pct) / Decimal("100")).quantize(Decimal("0.01"))
    return PlanFinancement(
        capex_total=capex.quantize(Decimal("0.01")),
        bfr=h.bfr_besoin.quantize(Decimal("0.01")),
        tresorerie_securite=h.tresorerie_securite.quantize(Decimal("0.01")),
        total_besoins=total_besoins,
        dnja=dnja_cash.quantize(Decimal("0.01")),
        dnja_acompte=dnja_acompte,
        dnja_solde=dnja_solde,
        dnja_annee_solde=h.dnja_annee_solde,
        apport_personnel=h.plan_financement_apport_personnel.quantize(Decimal("0.01")),
        emprunt=h.plan_financement_emprunt.quantize(Decimal("0.01")),
        subventions_capital=subv_capital.quantize(Decimal("0.01")),
        total_ressources=total_ressources,
        ecart=(total_ressources - total_besoins).quantize(Decimal("0.01")),
    )


def _calculer_plan_tresorerie(h: Hypotheses, lignes: list[LigneResultat]) -> list[MoisTresorerie]:
    """Plan de trésorerie mensuel simplifié sur la durée de l'horizon.

    Hypothèses de lissage :
    - Charges d'exploitation et cotisations MSA réparties sur 12 mois
    - CA réparti pondéré : 30 % sur oct-nov-déc (récolte chanvre + fêtes),
      60 % sur avr-sep (marchés+maraîchage), 10 % sur jan-mar (fonds stock)
    - Aides versées au mois spécifique : DNJA septembre N+1, ACJA octobre,
      CI-AB avril, CAB+écorégime mai, autres aides annuelles lissées semestre
    - Amortissements = non-cash (ne sortent pas de la trésorerie)
    - Immobilisations : sorties cash à leur année d'acquisition (janvier)
    """
    MOIS_LABELS = [
        "janv.", "févr.", "mars", "avril", "mai", "juin",
        "juil.", "août", "sept.", "oct.", "nov.", "déc.",
    ]
    POND_CA = [
        Decimal("0.03"), Decimal("0.03"), Decimal("0.04"),  # jan-mars 10 %
        Decimal("0.08"), Decimal("0.10"), Decimal("0.12"),  # avr-juin 30 %
        Decimal("0.10"), Decimal("0.10"), Decimal("0.10"),  # juil-sep 30 %
        Decimal("0.12"), Decimal("0.10"), Decimal("0.08"),  # oct-déc 30 %
    ]
    out: list[MoisTresorerie] = []
    solde_cum = h.tresorerie_securite
    for l in lignes:
        ca_annuel = l.produits_exploitation
        charges_exp_mensuel = (l.charges_exploitation / Decimal("12")).quantize(Decimal("0.01"))
        msa_mensuel = (l.charges_sociales / Decimal("12")).quantize(Decimal("0.01"))
        prelevements_mensuel = h.prelevements_mensuels.quantize(Decimal("0.01"))

        # CAPEX mensualisé : sorties cash à janvier de l'année d'acquisition
        # Part financée par DNJA/subvention → sortie cash réelle = montant - subv
        capex_janvier = Decimal("0")
        for imm in h.immobilisations:
            if imm.annee_acquisition == l.annee:
                assiette_cash = imm.montant_ht * (Decimal("100") - imm.subvention_pct) / Decimal("100")
                capex_janvier += assiette_cash

        for m in range(12):
            entrees = Decimal("0")
            sorties = Decimal("0")

            entrees += (ca_annuel * POND_CA[m]).quantize(Decimal("0.01"))

            # Aides à leur mois dédié
            for aide in h.aides:
                nom_upper = aide.nom.upper()
                # DNJA : split 80 % acompte à annee_versement + 20 % solde à annee_solde (sept)
                if "DNJA" in nom_upper and m == 8:  # septembre
                    if aide.annee_versement == l.annee:
                        acompte = aide.montant * Decimal(h.dnja_acompte_pct) / Decimal("100")
                        entrees += acompte.quantize(Decimal("0.01"))
                    if h.dnja_annee_solde == l.annee:
                        solde = aide.montant * Decimal(100 - h.dnja_acompte_pct) / Decimal("100")
                        entrees += solde.quantize(Decimal("0.01"))
                    continue
                if aide.annee_versement != l.annee:
                    continue
                if "ACJA" in nom_upper and m == 9:  # octobre
                    entrees += aide.montant
                elif "CI-AB" in nom_upper and m == 3:  # avril
                    entrees += aide.montant
                elif ("CAB" in nom_upper or "ÉCO" in nom_upper) and m == 4:  # mai
                    entrees += aide.montant

            sorties += charges_exp_mensuel + msa_mensuel + prelevements_mensuel
            if m == 0 and capex_janvier > 0:
                sorties += capex_janvier

            solde_mois = (entrees - sorties).quantize(Decimal("0.01"))
            solde_cum = (solde_cum + solde_mois).quantize(Decimal("0.01"))

            out.append(MoisTresorerie(
                mois_num=m + 1,
                annee=l.annee,
                label=f"N+{l.annee} {MOIS_LABELS[m]}",
                entrees=entrees.quantize(Decimal("0.01")),
                sorties=sorties.quantize(Decimal("0.01")),
                solde_du_mois=solde_mois,
                solde_cumule=solde_cum,
            ))
    return out


def _calculer_seuil_rentabilite(h: Hypotheses, ligne_n4: LigneResultat) -> SeuilRentabilite:
    """Seuil de rentabilité : CA mini pour couvrir charges fixes + MSA + amort."""
    categories_fixes = {
        "foncier", "foncier-batiment", "assurance", "certification",
        "mecanisation", "energie", "administratif", "provisions", "eau",
    }
    charges_fixes_exploitation = sum(
        (c.montant_annuel_ht for c in h.charges_recurrentes
         if c.categorie in categories_fixes and c.annee_demarrage <= ligne_n4.annee),
        Decimal("0"),
    )
    charges_fixes_total = (
        charges_fixes_exploitation + ligne_n4.amortissements + ligne_n4.charges_sociales
    ).quantize(Decimal("0.01"))

    # Taux de marge sur coûts variables
    ca = ligne_n4.produits_exploitation
    charges_variables = ligne_n4.charges_exploitation - charges_fixes_exploitation
    if ca > 0:
        taux_marge_cv = ((ca - charges_variables) / ca * Decimal("100")).quantize(Decimal("0.1"))
        ca_seuil = (charges_fixes_total / ((ca - charges_variables) / ca)).quantize(Decimal("0.01"))
        couverture = (ca / ca_seuil * Decimal("100")).quantize(Decimal("0.1")) if ca_seuil > 0 else Decimal("0")
    else:
        taux_marge_cv = Decimal("0")
        ca_seuil = Decimal("0")
        couverture = Decimal("0")

    return SeuilRentabilite(
        charges_fixes_annuelles=charges_fixes_total,
        taux_marge_sur_couts_variables=taux_marge_cv,
        ca_seuil=ca_seuil,
        couverture_actuelle_pct=couverture,
    )


def _calculer_ratios(h: Hypotheses, ligne_n4: LigneResultat) -> Ratios:
    """Ratios économiques clés N+4."""
    ca = ligne_n4.produits_exploitation
    ebe = ligne_n4.ebe
    aides = ligne_n4.aides_revenu
    prelevements = h.prelevements_mensuels * Decimal("12")

    return Ratios(
        taux_marge_ebe_pct=(ebe / ca * Decimal("100")).quantize(Decimal("0.1")) if ca > 0 else Decimal("0"),
        ca_par_uth=(ca / h.uth).quantize(Decimal("0.01")),
        poids_aides_pct=(aides / ca * Decimal("100")).quantize(Decimal("0.1")) if ca > 0 else Decimal("0"),
        prelevements_sur_ebe_pct=(prelevements / ebe * Decimal("100")).quantize(Decimal("0.1")) if ebe > 0 else Decimal("0"),
    )


def _calculer_scenarios_stress(h: Hypotheses) -> list[ScenarioStress]:
    """Tests de résistance N+4 : CA -20 %, prix CBD -25 %, cumul."""
    scenarios: list[ScenarioStress] = []

    for nom, description, facteur_qte, facteur_prix in [
        ("CA -20 %", "Baisse du volume de ventes de 20 % (retard commercialisation)", Decimal("0.8"), Decimal("1.0")),
        ("Prix CBD -25 %", "Chute des prix CBD (concurrence/surproduction)", Decimal("1.0"), Decimal("0.75")),
        ("Cumul vol + prix −30 %", "Scénario pessimiste : vol -20 % + prix -15 %", Decimal("0.8"), Decimal("0.85")),
    ]:
        h_stress = h.model_copy(deep=True)
        for act in h_stress.activites:
            if act.quantite_annuelle is not None:
                act.quantite_annuelle = (act.quantite_annuelle * facteur_qte).quantize(Decimal("0.01"))
            if act.rendement_t_ha is not None:
                act.rendement_t_ha = (act.rendement_t_ha * facteur_qte).quantize(Decimal("0.001"))
            act.prix_vente_ht = (act.prix_vente_ht * facteur_prix).quantize(Decimal("0.01"))
        result = calculer(h_stress, include_enrichissements=False)
        ligne = result.lignes[-1]
        scenarios.append(ScenarioStress(
            nom=nom,
            description=description,
            ebe_n4=ligne.ebe,
            resultat_n4=ligne.resultat,
            ebe_uth_n4=result.ebe_uth_annee_cible,
            seuil_dnja_tenu=result.ebe_uth_atteint,
        ))
    return scenarios


def _calculer_bilan_n4(h: Hypotheses, lignes: list[LigneResultat]) -> BilanSimplifie:
    """Bilan prévisionnel simplifié à fin N+4."""
    annee_cible = h.horizon_annees

    # Actif
    immos_brutes = sum((i.montant_ht for i in h.immobilisations), Decimal("0"))
    amort_cumules = sum((l.amortissements for l in lignes), Decimal("0"))
    immos_nettes = (immos_brutes - amort_cumules).quantize(Decimal("0.01"))
    stocks = Decimal("5000")  # estimation fleurs CBD en cours de séchage/stockage
    creances = Decimal("2000")  # clients en attente de paiement
    # Trésorerie = cumul résultats - prélèvements - invests + aides capital
    cumul_resultat = sum((l.resultat for l in lignes), Decimal("0"))
    cumul_prelevements = sum((l.prelevements_annuels for l in lignes), Decimal("0"))
    tresorerie = max((cumul_resultat - cumul_prelevements + immos_brutes * Decimal("0.3")),
                      Decimal("0")).quantize(Decimal("0.01"))
    total_actif = (immos_nettes + stocks + creances + tresorerie).quantize(Decimal("0.01"))

    # Passif
    capital_exploitant = (total_actif - Decimal("3000")).quantize(Decimal("0.01"))
    subventions_etalees = (immos_brutes * Decimal("0.35")).quantize(Decimal("0.01"))
    dettes = Decimal("3000")
    total_passif = (capital_exploitant + subventions_etalees + dettes).quantize(Decimal("0.01"))

    return BilanSimplifie(
        immobilisations_nettes=immos_nettes,
        stocks=stocks,
        creances=creances,
        tresorerie=tresorerie,
        total_actif=total_actif,
        capital_exploitant=capital_exploitant,
        subventions_etalees=subventions_etalees,
        dettes=dettes,
        total_passif=total_passif,
    )
