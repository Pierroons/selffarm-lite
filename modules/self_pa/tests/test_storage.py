"""Tests de la persistance des factures reçues."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from self_pa import storage
from self_pa.imputation import proposer
from self_pa.models import CanalReception, FactureRecue, PartieFacture


@pytest.fixture
def base_isolee(tmp_path, monkeypatch):
    """Une base SQLite par test — même motif que test_storage.py du hub compta."""
    monkeypatch.setenv("SELFFARM_COMPTA_DB", str(tmp_path / "test_compta.db"))
    yield tmp_path


def facture(numero="FA-2026-0142", siren="552100554", ttc="1200.00") -> FactureRecue:
    return FactureRecue(
        numero=numero,
        date_facture=date(2026, 9, 3),
        emetteur=PartieFacture(nom="Outillage Pro Distribution", siren=siren),
        total_ht=Decimal("1000.00"),
        total_tva=Decimal("200.00"),
        total_ttc=Decimal(ttc),
    )


def enregistrer(f: FactureRecue, **kwargs):
    return storage.enregistrer(f, proposer(f, compte_charge="6063"), **kwargs)


# ---------------- schéma ----------------

def test_la_migration_est_namespacee(base_isolee):
    """`self_pa#1` vit dans le registre à côté du noyau et de self_culture, sans
    collision de numérotation."""
    enregistrer(facture())

    from self_agri_book.storage import _conn
    with _conn() as c:
        lignes = c.execute(
            "SELECT version, name FROM _schema_migrations WHERE module = 'self_pa'"
        ).fetchall()

    assert [(x["version"], x["name"]) for x in lignes] == [(1, "create_facture_recue")]


def test_les_montants_traversent_sans_perte(base_isolee):
    """TEXT et non REAL : un Decimal doit revenir identique au centime."""
    enregistrer(facture(ttc="1863.79"))
    stockee = storage.obtenir("552100554:FA-2026-0142")

    assert Decimal(stockee["montant_ttc"]) == Decimal("1863.79")
    assert stockee["montant_ttc"] == "1863.79"


# ---------------- déduplication ----------------

def test_premier_enregistrement_cree(base_isolee):
    cle, creee = enregistrer(facture())

    assert cle == "552100554:FA-2026-0142"
    assert creee is True
    assert len(storage.lister()) == 1


def test_la_meme_facture_deux_fois_ne_cree_quune_ligne(base_isolee):
    enregistrer(facture())
    _, creee = enregistrer(facture())

    assert creee is False
    assert len(storage.lister()) == 1


def test_meme_facture_par_deux_canaux_ne_cree_quune_ligne(base_isolee):
    """Le cas réel de la transition : la facture arrive par mail, puis par la
    plateforme. Deux fichiers, deux empreintes, une seule dette à payer."""
    enregistrer(facture(), canal=CanalReception.MAIL, hash_fichier="a" * 64)
    _, creee = enregistrer(
        facture(), canal=CanalReception.PLATEFORME, hash_fichier="b" * 64,
        provider_invoice_id=84385,
    )

    assert creee is False
    lignes = storage.lister()
    assert len(lignes) == 1
    # Le premier canal est conservé : c'est par là qu'elle est réellement arrivée.
    assert lignes[0]["canal"] == "mail"


def test_deux_factures_distinctes_coexistent(base_isolee):
    enregistrer(facture(numero="FA-2026-0142"))
    enregistrer(facture(numero="FA-2026-0143"))

    assert len(storage.lister()) == 2


def test_meme_numero_chez_deux_fournisseurs_coexiste(base_isolee):
    """Deux fournisseurs numérotent chacun leur suite : « FA-001 » de l'un n'est
    pas « FA-001 » de l'autre."""
    enregistrer(facture(siren="552100554", numero="FA-001"))
    enregistrer(facture(siren="999999999", numero="FA-001"))

    assert len(storage.lister()) == 2


# ---------------- statuts ----------------

def test_facture_saine_est_proposee(base_isolee):
    enregistrer(facture())

    assert storage.obtenir("552100554:FA-2026-0142")["statut"] == "proposee"
    assert len(storage.lister("proposee")) == 1


def test_facture_incoherente_est_bloquee(base_isolee):
    """HT + TVA ≠ TTC : elle est reçue et conservée, mais aucune écriture n'est
    proposée."""
    enregistrer(facture(ttc="9999.00"))
    stockee = storage.obtenir("552100554:FA-2026-0142")

    assert stockee["statut"] == "bloquee"
    assert stockee["imputation_json"] == "[]"
    assert "totaux_incoherents" in stockee["anomalies_json"]


def test_validation_rattache_lecriture(base_isolee):
    enregistrer(facture())

    assert storage.marquer_validee("552100554:FA-2026-0142", ecriture_id=42) is True
    stockee = storage.obtenir("552100554:FA-2026-0142")
    assert stockee["statut"] == "validee"
    assert stockee["ecriture_id"] == 42
    assert stockee["traitee_le"] is not None


def test_double_validation_est_sans_effet(base_isolee):
    """Le garde-fou du double clic : une facture déjà validée ne repasse pas,
    sans quoi on créerait une seconde écriture pour la même dette."""
    enregistrer(facture())
    storage.marquer_validee("552100554:FA-2026-0142", ecriture_id=42)

    assert storage.marquer_validee("552100554:FA-2026-0142", ecriture_id=43) is False
    assert storage.obtenir("552100554:FA-2026-0142")["ecriture_id"] == 42


def test_ecarter_conserve_la_facture_et_son_motif(base_isolee):
    """Écarter n'est pas supprimer : la facture a été reçue, et le guide DGFiP
    (question 6) demande de pouvoir justifier son traitement."""
    enregistrer(facture())

    assert storage.marquer_ecartee("552100554:FA-2026-0142", "Doublon fournisseur") is True
    stockee = storage.obtenir("552100554:FA-2026-0142")
    assert stockee["statut"] == "ecartee"
    assert "Doublon fournisseur" in stockee["anomalies_json"]
    assert storage.obtenir("552100554:FA-2026-0142") is not None


def test_valider_une_facture_inconnue_ne_fait_rien(base_isolee):
    assert storage.marquer_validee("000000000:INEXISTANTE", ecriture_id=1) is False


def test_statut_inconnu_est_refuse(base_isolee):
    with pytest.raises(ValueError, match="Statut inconnu"):
        storage.lister("nimportequoi")


# ---------------- curseur de reprise ----------------

def test_curseur_vide_au_depart(base_isolee):
    assert storage.dernier_id_plateforme() is None


def test_curseur_rend_le_plus_grand_id(base_isolee):
    """Le curseur pilote `starting_after_id` : s'il rendait autre chose que le
    maximum, des factures seraient relues ou sautées."""
    enregistrer(facture(numero="FA-1"), provider_invoice_id=84385)
    enregistrer(facture(numero="FA-2"), provider_invoice_id=84390)
    enregistrer(facture(numero="FA-3"), provider_invoice_id=84387)

    assert storage.dernier_id_plateforme() == 84390


def test_curseur_ignore_les_factures_hors_plateforme(base_isolee):
    """Une facture arrivée par mail n'a pas d'identifiant plateforme : elle ne
    doit pas faire avancer le curseur de reprise."""
    enregistrer(facture(numero="FA-1"), provider_invoice_id=84385)
    enregistrer(facture(numero="FA-2"), canal=CanalReception.MAIL)

    assert storage.dernier_id_plateforme() == 84385
