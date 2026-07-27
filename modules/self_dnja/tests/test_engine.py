"""Tests du moteur self-dnja."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from self_dnja.engine import EBE_UTH_SEUIL_DNJA_NA_2026, calculer
from self_dnja.models import (
    Activite,
    Aide,
    ChargeRecurrente,
    CotisationsMSA,
    Hypotheses,
    Immobilisation,
    RegimeFiscal,
    StatutJuridique,
)

EXAMPLES_DIR = Path(__file__).parent.parent.parent.parent / "examples"


def _minimal_hyp(**overrides) -> Hypotheses:
    base = {
        "candidat": "Testeur",
        "date_installation": date(2026, 6, 1),
        "commune": "Sainte-Foy",
        "departement": "le departement",
        "statut_juridique": StatutJuridique.INDIVIDUEL,
        "regime_fiscal": RegimeFiscal.REEL_SIMPLIFIE,
        "horizon_annees": 4,
        "activites": [
            Activite(
                nom="Maraîchage bio",
                surface_ha=Decimal(1),
                quantite_annuelle=Decimal(2000),
                prix_vente_ht=Decimal(5),
                unite_vente="kg",
                bio=True,
                annee_pleine_production=3,
                montee_en_charge=[Decimal("0.3"), Decimal("0.6"), Decimal("1.0"), Decimal("1.0")],
            )
        ],
    }
    base.update(overrides)
    return Hypotheses(**base)


def test_calcul_produits_progression():
    """La montée en charge doit être respectée."""
    r = calculer(_minimal_hyp())
    assert r.lignes[0].produits_exploitation == Decimal("3000.00")
    assert r.lignes[1].produits_exploitation == Decimal("6000.00")
    assert r.lignes[2].produits_exploitation == Decimal("10000.00")
    assert r.lignes[3].produits_exploitation == Decimal("10000.00")


def test_horizon_annees_respecte():
    r = calculer(_minimal_hyp(horizon_annees=5))
    assert len(r.lignes) == 5
    assert [l.annee for l in r.lignes] == [1, 2, 3, 4, 5]


def test_charges_recurrentes_soustraites_ebe():
    hyp = _minimal_hyp(
        charges_recurrentes=[
            ChargeRecurrente(nom="Semences", montant_annuel_ht=Decimal(1000), categorie="intrants"),
            ChargeRecurrente(nom="Engrais", montant_annuel_ht=Decimal(500), categorie="intrants"),
        ]
    )
    r = calculer(hyp)
    for l in r.lignes:
        # EBE = produits - charges + aides (0 ici)
        assert l.charges_exploitation == Decimal("1500.00")
        assert l.ebe == l.produits_exploitation - Decimal("1500.00")


def test_amortissement_linaire():
    hyp = _minimal_hyp(
        immobilisations=[
            Immobilisation(
                nom="Serre",
                montant_ht=Decimal(4000),
                annee_acquisition=1,
                duree_amortissement=4,
                subvention_pct=Decimal(0),
            )
        ]
    )
    r = calculer(hyp)
    # 4000 / 4 = 1000 par an, depuis N+1 à N+4
    for l in r.lignes:
        assert l.amortissements == Decimal("1000.00")


def test_amortissement_avec_subvention():
    hyp = _minimal_hyp(
        immobilisations=[
            Immobilisation(
                nom="Serre",
                montant_ht=Decimal(4000),
                annee_acquisition=1,
                duree_amortissement=4,
                subvention_pct=Decimal(40),
            )
        ]
    )
    r = calculer(hyp)
    # assiette = 4000 * 0.6 = 2400 ; amort annuel = 600
    for l in r.lignes:
        assert l.amortissements == Decimal("600.00")


def test_amortissement_debute_annee_acquisition():
    """L'amortissement démarre à partir de l'année d'acquisition."""
    hyp = _minimal_hyp(
        immobilisations=[
            Immobilisation(
                nom="Séchoir",
                montant_ht=Decimal(2000),
                annee_acquisition=3,
                duree_amortissement=4,
                subvention_pct=Decimal(0),
            )
        ]
    )
    r = calculer(hyp)
    assert r.lignes[0].amortissements == Decimal(0)  # N+1 : pas encore acquis
    assert r.lignes[1].amortissements == Decimal(0)  # N+2 : pas encore
    assert r.lignes[2].amortissements == Decimal("500.00")  # N+3 : amort
    assert r.lignes[3].amortissements == Decimal("500.00")  # N+4 : amort


def test_cotisations_msa_exoneration_ja():
    hyp = _minimal_hyp(
        cotisations_msa=CotisationsMSA(
            exoneration_ja_active=True,
            cotisation_base_annuelle=Decimal(4000),
            pct_exoneration=[Decimal(65), Decimal(55), Decimal(35), Decimal(25)],
        )
    )
    r = calculer(hyp)
    # N+1 : 4000 * (1 - 0.65) = 1400
    assert r.lignes[0].charges_sociales == Decimal("1400.00")
    # N+2 : 4000 * (1 - 0.55) = 1800
    assert r.lignes[1].charges_sociales == Decimal("1800.00")
    # N+3 : 4000 * (1 - 0.35) = 2600
    assert r.lignes[2].charges_sociales == Decimal("2600.00")
    # N+4 : 4000 * (1 - 0.25) = 3000
    assert r.lignes[3].charges_sociales == Decimal("3000.00")


def test_cotisations_msa_sans_exoneration():
    hyp = _minimal_hyp(
        cotisations_msa=CotisationsMSA(
            exoneration_ja_active=False,
            cotisation_base_annuelle=Decimal(4000),
        )
    )
    r = calculer(hyp)
    for l in r.lignes:
        assert l.charges_sociales == Decimal(4000)


def test_aide_revenu_integree_ebe():
    hyp = _minimal_hyp(
        aides=[
            Aide(nom="DNJA", montant=Decimal(18000), annee_versement=1, est_subvention_capital=False),
        ]
    )
    r = calculer(hyp)
    assert r.lignes[0].aides_revenu == Decimal("18000.00")
    assert r.lignes[1].aides_revenu == Decimal("0.00")  # pas de versement N+2


def test_subvention_capital_hors_resultat():
    """Les subventions de capital ne sont PAS comptées en aide revenu."""
    hyp = _minimal_hyp(
        aides=[
            Aide(nom="Subv serre", montant=Decimal(5000), annee_versement=1, est_subvention_capital=True),
        ]
    )
    r = calculer(hyp)
    assert r.lignes[0].aides_revenu == Decimal("0.00")


def test_ebe_uth_seuil_atteint():
    hyp = _minimal_hyp(
        activites=[
            Activite(
                nom="CBD bio",
                surface_ha=Decimal(1),
                quantite_annuelle=Decimal(20),
                prix_vente_ht=Decimal(2500),
                unite_vente="kg",
                bio=True,
                annee_pleine_production=3,
                montee_en_charge=[Decimal(1), Decimal(1), Decimal(1), Decimal(1)],
            )
        ]
    )
    r = calculer(hyp)
    # 20 kg × 2500 € × 1 = 50000 € → EBE/UTH dépasse 22 000 €
    assert r.ebe_uth_atteint is True
    assert r.ebe_uth_annee_cible > EBE_UTH_SEUIL_DNJA_NA_2026


def test_ebe_uth_seuil_non_atteint_revenu_insuffisant():
    hyp = _minimal_hyp()  # 10 000 € CA année 4 = bien en-dessous
    r = calculer(hyp)
    assert r.ebe_uth_atteint is False
    assert r.ebe_uth_annee_cible < EBE_UTH_SEUIL_DNJA_NA_2026


def test_rendement_t_ha_conversion_en_kg():
    """rendement_t_ha × surface_ha × 1000 = quantité en kg."""
    hyp = _minimal_hyp(
        activites=[
            Activite(
                nom="Chanvre industriel",
                surface_ha=Decimal(2),
                rendement_t_ha=Decimal("1.5"),
                prix_vente_ht=Decimal(3),
                unite_vente="kg",
                annee_pleine_production=2,
                montee_en_charge=[Decimal(1), Decimal(1), Decimal(1), Decimal(1)],
            )
        ]
    )
    r = calculer(hyp)
    # 1.5 × 2 × 1000 = 3000 kg × 3 € = 9000 €
    assert r.lignes[0].produits_exploitation == Decimal("9000.00")


def test_activite_sans_quantite_ni_rendement_echoue():
    with pytest.raises(ValueError, match="fournis soit"):
        Activite(
            nom="Incomplet",
            surface_ha=Decimal(1),
            prix_vente_ht=Decimal(5),
            annee_pleine_production=1,
        )


def test_exemple_yaml_pierroons_se_charge():
    """Les YAML d'exemple doivent se charger sans erreur."""
    for filename in ["hypotheses-pierroons.yaml", "hypotheses-pierroons-realiste.yaml"]:
        path = EXAMPLES_DIR / filename
        if not path.exists():
            pytest.skip(f"{filename} absent")
        data = yaml.safe_load(path.read_text())
        hyp = Hypotheses.model_validate(data)
        result = calculer(hyp)
        assert len(result.lignes) == hyp.horizon_annees


def test_version_dans_resultat():
    r = calculer(_minimal_hyp())
    assert r.version
    assert r.genere_le == date.today()


def test_bilan_n4_equilibre():
    """Invariant comptable fondamental : le bilan doit balancer (Actif = Passif)."""
    bilan = calculer(_minimal_hyp()).bilan_n4
    assert bilan is not None
    assert bilan.total_actif == bilan.total_passif, (
        f"Bilan déséquilibré : actif {bilan.total_actif} ≠ passif {bilan.total_passif}"
    )
    # Cohérence des sous-totaux avec leurs postes.
    assert bilan.total_actif == (
        bilan.immobilisations_nettes + bilan.stocks + bilan.creances + bilan.tresorerie
    )
    assert bilan.total_passif == (
        bilan.capital_exploitant + bilan.subventions_etalees + bilan.dettes
    )


def test_annee_fin_charge_ponctuelle_n1():
    """Une charge avec annee_demarrage = annee_fin = 1 ne s'applique qu'en N1."""
    hyp = _minimal_hyp(
        charges_recurrentes=[
            ChargeRecurrente(
                nom="Constitution stock N1", montant_annuel_ht=Decimal(1000),
                categorie="intrants", annee_demarrage=1, annee_fin=1,
            ),
        ]
    )
    r = calculer(hyp)
    assert r.lignes[0].charges_exploitation == Decimal("1000.00")  # N1
    assert r.lignes[1].charges_exploitation == Decimal("0.00")     # N2
    assert r.lignes[2].charges_exploitation == Decimal("0.00")     # N3
    assert r.lignes[3].charges_exploitation == Decimal("0.00")     # N4


def test_annee_fin_none_court_jusqu_horizon():
    """Sans annee_fin (None), la charge s'applique chaque année (comportement par défaut)."""
    hyp = _minimal_hyp(
        charges_recurrentes=[
            ChargeRecurrente(nom="Récurrente", montant_annuel_ht=Decimal(500), categorie="intrants"),
        ]
    )
    r = calculer(hyp)
    for l in r.lignes:
        assert l.charges_exploitation == Decimal("500.00")


def test_annee_fin_fenetre_n2_n3():
    """Charge active uniquement sur la fenêtre [annee_demarrage, annee_fin] (N2→N3)."""
    hyp = _minimal_hyp(
        charges_recurrentes=[
            ChargeRecurrente(
                nom="Fenêtre", montant_annuel_ht=Decimal(300),
                categorie="intrants", annee_demarrage=2, annee_fin=3,
            ),
        ]
    )
    r = calculer(hyp)
    assert r.lignes[0].charges_exploitation == Decimal("0.00")    # N1
    assert r.lignes[1].charges_exploitation == Decimal("300.00")  # N2
    assert r.lignes[2].charges_exploitation == Decimal("300.00")  # N3
    assert r.lignes[3].charges_exploitation == Decimal("0.00")    # N4


def test_plan_financement_dnja_acompte_solde_sans_resplit():
    """La DNJA du plan de financement est lue des aides (acompte N1 + solde ultérieur),
    sans re-split 80/20, et seul l'acompte finance l'installation."""
    hyp = _minimal_hyp(
        aides=[
            Aide(nom="DNJA acompte 80%", montant=Decimal(19600), annee_versement=1, est_subvention_capital=True),
            Aide(nom="DNJA solde 20%", montant=Decimal(4900), annee_versement=4, est_subvention_capital=True),
        ],
    )
    p = calculer(hyp).plan_financement
    assert p.dnja == Decimal("24500.00")          # total = somme des versements
    assert p.dnja_acompte == Decimal("19600.00")  # versement N1, PAS 80% de 19600
    assert p.dnja_solde == Decimal("4900.00")     # versement ultérieur
    # Seul l'acompte (cash N1) entre dans les ressources d'installation ; le solde N4 est exclu.
    # Pas d'immo / apport / emprunt dans _minimal_hyp → ressources = acompte seul.
    assert p.total_ressources == Decimal("19600.00")
