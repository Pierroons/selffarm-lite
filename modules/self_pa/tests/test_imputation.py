"""Tests du contrôle arithmétique et de la proposition d'écriture."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from self_pa.imputation import Gravite, controler, proposer
from self_pa.models import (
    FactureRecue,
    LigneFacture,
    PartieFacture,
    VentilationTva,
)


def facture(
    *,
    ht="1000.00",
    tva="200.00",
    ttc="1200.00",
    numero="FA-2026-0142",
    siren="552100554",
    date_facture=date(2026, 9, 3),
    ventilation=True,
    lignes=None,
) -> FactureRecue:
    """Facture d'outillage cohérente par défaut ; chaque test casse un point."""
    return FactureRecue(
        numero=numero,
        date_facture=date_facture,
        emetteur=PartieFacture(nom="Outillage Pro Distribution", siren=siren),
        total_ht=Decimal(ht) if ht is not None else None,
        total_tva=Decimal(tva) if tva is not None else None,
        total_ttc=Decimal(ttc) if ttc is not None else None,
        ventilation_tva=[
            VentilationTva(
                base_ht=Decimal("1000.00"),
                montant_tva=Decimal("200.00"),
                taux=Decimal("20.00"),
                categorie="S",
            )
        ]
        if ventilation
        else [],
        lignes=lignes or [],
    )


def codes(anomalies) -> set[str]:
    return {a.code for a in anomalies}


# ---------------- le cas nominal ----------------

def test_facture_coherente_ne_produit_aucune_anomalie():
    assert controler(facture()) == []


def test_facture_coherente_produit_une_ecriture_dachat():
    imp = proposer(facture(), compte_charge="6063")

    assert imp.proposable
    assert imp.journal == "ACH"
    assert len(imp.lignes) == 1
    ligne = imp.lignes[0]
    assert ligne.compte_debit == "6063"
    assert ligne.compte_credit == "401"
    assert ligne.montant_ht == Decimal("1000.00")
    assert ligne.montant_tva == Decimal("200.00")
    assert ligne.montant_ttc == Decimal("1200.00")


def test_source_id_porte_la_cle_metier_et_le_compte():
    """Le suffixe par compte reprend le précédent de webapp/routes/invoice.py :
    une facture ventilée sur plusieurs charges donne plusieurs écritures, et
    chacune doit être dédupliquée séparément."""
    imp = proposer(facture(), compte_charge="6063")

    assert imp.lignes[0].source_id == "552100554:FA-2026-0142#6063"


def test_tva_nulle_reste_valide():
    """Franchise en base ou autoliquidation : pas de TVA, facture parfaitement
    régulière."""
    imp = proposer(
        facture(ht="1000.00", tva="0.00", ttc="1000.00", ventilation=False),
        compte_charge="6063",
    )

    assert imp.proposable
    assert imp.lignes[0].montant_tva == Decimal("0.00")


# ---------------- ce que le contrôle doit ATTRAPER ----------------

def test_totaux_incoherents_bloquent():
    """Le garde-fou central : HT + TVA ≠ TTC. Une facture qui ne tombe pas juste
    ne devient jamais une écriture, quelle que soit sa provenance."""
    anomalies = controler(facture(ht="1000.00", tva="200.00", ttc="1500.00"))

    assert "totaux_incoherents" in codes(anomalies)
    assert all(a.gravite is Gravite.BLOQUANT for a in anomalies)


def test_totaux_incoherents_empechent_toute_proposition():
    imp = proposer(facture(ttc="1500.00"), compte_charge="6063")

    assert not imp.proposable
    assert imp.lignes == []


def test_un_centime_decart_est_deja_une_anomalie():
    """Pas de tolérance sur BR-CO-15 : l'égalité est stricte. Un centime toléré
    ici, ce sont des centimes qui s'accumulent sans que rien ne le dise."""
    anomalies = controler(facture(ht="1000.00", tva="200.00", ttc="1200.01"))

    assert "totaux_incoherents" in codes(anomalies)


def test_ventilation_tva_qui_ne_somme_pas_au_total():
    f = facture(tva="250.00", ttc="1250.00")  # ventilation à 200, total à 250
    anomalies = controler(f)

    assert "ventilation_tva_incoherente" in codes(anomalies)


def test_taux_incoherent_avec_sa_base():
    f = facture()
    f.ventilation_tva[0].taux = Decimal("5.50")  # 5,5 % de 1000 ≠ 200
    anomalies = controler(f)

    assert "taux_incoherent" in codes(anomalies)


def test_arrondi_legal_dun_centime_est_tolere():
    """L'inverse du test précédent : un écart d'un centime sur un montant
    recalculé depuis un taux est un arrondi légitime, pas une anomalie. Un
    contrôle qui crierait ici serait ignoré au bout de trois factures."""
    f = facture(ht="333.33", tva="66.67", ttc="400.00", ventilation=False)
    f.ventilation_tva = [
        VentilationTva(
            base_ht=Decimal("333.33"),
            montant_tva=Decimal("66.67"),  # 20 % font 66.666 → 66.67
            taux=Decimal("20.00"),
            categorie="S",
        )
    ]

    assert controler(f) == []


# ---------------- identité manquante ----------------

def test_siren_absent_bloque():
    anomalies = controler(facture(siren=""))

    assert "siren_absent" in codes(anomalies)
    assert not proposer(facture(siren=""), compte_charge="6063").proposable


def test_numero_absent_bloque():
    assert "numero_absent" in codes(controler(facture(numero="")))


def test_date_absente_bloque():
    assert "date_absente" in codes(controler(facture(date_facture=None)))


def test_ttc_illisible_bloque():
    assert "ttc_absent" in codes(controler(facture(ttc=None)))


# ---------------- ce qui doit rester un simple avertissement ----------------

def test_remise_globale_navertit_sans_bloquer():
    """Somme des lignes ≠ total HT est normal dès qu'il y a une remise ou des
    frais de port. Bloquer là-dessus rendrait l'outil inutilisable."""
    f = facture(
        lignes=[
            LigneFacture(designation="Perceuse", montant_ht=Decimal("1100.00")),
        ]
    )
    anomalies = controler(f)

    assert "ecart_lignes_total" in codes(anomalies)
    ecart = next(a for a in anomalies if a.code == "ecart_lignes_total")
    assert ecart.gravite is Gravite.AVERTISSEMENT
    assert proposer(f, compte_charge="6063").proposable


def test_lignes_coherentes_navertissent_pas():
    f = facture(
        lignes=[
            LigneFacture(designation="Perceuse", montant_ht=Decimal("600.00")),
            LigneFacture(designation="Meuleuse", montant_ht=Decimal("400.00")),
        ]
    )

    assert controler(f) == []
