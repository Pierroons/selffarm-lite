"""Tests du hub compta SQLite — self_agri_book.storage."""

from __future__ import annotations

import json
import os
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from self_agri_book import storage


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Force la DB SQLite vers un fichier temporaire par test → tests indépendants."""
    db_file = tmp_path / "test_compta.db"
    monkeypatch.setenv("SELFFARM_COMPTA_DB", str(db_file))
    yield db_file


# ---------------- init_db / save_ecriture ----------------

def test_init_db_creates_schema(isolated_db):
    storage.init_db()
    assert isolated_db.exists()
    with storage._conn() as c:
        rows = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='ecritures_comptables'"
        ).fetchall()
    assert len(rows) == 1


def test_save_ecriture_basic(isolated_db):
    eid, created = storage.save_ecriture(
        date_operation=date(2026, 4, 26),
        journal="VEN",
        numero_piece="F-2026-0001",
        libelle="Vente test",
        compte_debit="411",
        compte_credit="701",
        montant_ttc=Decimal("100.00"),
        montant_ht=Decimal("100.00"),
        montant_tva=Decimal("0.00"),
    )
    assert created is True
    assert eid > 0


def test_save_ecriture_dedup_on_source(isolated_db):
    """Deux saves consécutifs avec même (source_module, source_id) → 1 seule écriture."""
    kwargs = dict(
        date_operation=date(2026, 4, 26),
        journal="VEN",
        numero_piece="F-2026-0042",
        libelle="Vente dédup test",
        compte_debit="411",
        compte_credit="701",
        montant_ttc=Decimal("250.00"),
        source_module="self_invoice",
        source_id="F-2026-0042",
    )
    eid1, created1 = storage.save_ecriture(**kwargs)
    eid2, created2 = storage.save_ecriture(**kwargs)
    assert created1 is True
    assert created2 is False
    assert eid1 == eid2


def test_save_ecriture_dedup_can_be_bypassed(isolated_db):
    """allow_duplicate=True force une insertion même si la source existe."""
    kwargs = dict(
        date_operation=date(2026, 4, 26),
        journal="VEN",
        numero_piece="F-2026-9999",
        libelle="dup",
        compte_debit="411",
        compte_credit="701",
        montant_ttc=Decimal("10.00"),
        source_module="self_invoice",
        source_id="F-2026-9999",
    )
    eid1, _ = storage.save_ecriture(**kwargs)
    eid2, created2 = storage.save_ecriture(**kwargs, allow_duplicate=True)
    assert eid2 != eid1
    assert created2 is True


def test_save_ecriture_no_dedup_without_source(isolated_db):
    """Pas de source_module → chaque save crée une nouvelle écriture."""
    kwargs = dict(
        date_operation=date(2026, 4, 26),
        journal="MAN",
        numero_piece="MAN-001",
        libelle="manuel sans source",
        compte_debit="606",
        compte_credit="512",
        montant_ttc=Decimal("50.00"),
    )
    eid1, _ = storage.save_ecriture(**kwargs)
    eid2, created2 = storage.save_ecriture(**kwargs)
    assert eid1 != eid2
    assert created2 is True


# ---------------- find_ecriture_by_source ----------------

def test_find_ecriture_by_source_returns_existing(isolated_db):
    storage.save_ecriture(
        date_operation=date(2026, 4, 26),
        journal="VEN",
        numero_piece="F-X",
        libelle="trouve-moi",
        compte_debit="411",
        compte_credit="701",
        montant_ttc=Decimal("75.00"),
        source_module="self_invoice",
        source_id="F-X",
    )
    found = storage.find_ecriture_by_source("self_invoice", "F-X")
    assert found is not None
    assert found["numero_piece"] == "F-X"
    assert found["libelle"] == "trouve-moi"


def test_find_ecriture_by_source_returns_none_if_absent(isolated_db):
    storage.init_db()
    assert storage.find_ecriture_by_source("self_invoice", "INEXISTANT") is None
    assert storage.find_ecriture_by_source("", "x") is None


# ---------------- list_ecritures ----------------

def test_list_ecritures_returns_all_in_desc_order(isolated_db):
    for i in range(3):
        storage.save_ecriture(
            date_operation=date(2026, 4, 26),
            journal="VEN",
            numero_piece=f"F-{i}",
            libelle=f"vente {i}",
            compte_debit="411",
            compte_credit="701",
            montant_ttc=Decimal(f"{(i + 1) * 10}.00"),
            source_module="self_invoice",
            source_id=f"F-{i}",
        )
    rows = storage.list_ecritures(limit=10)
    assert len(rows) == 3
    # Ordre desc → dernier inséré en premier
    assert rows[0]["numero_piece"] == "F-2"
    assert rows[2]["numero_piece"] == "F-0"


def test_list_ecritures_filter_by_source_module(isolated_db):
    storage.save_ecriture(
        date_operation=date(2026, 4, 26),
        journal="VEN",
        numero_piece="F-A",
        libelle="invoice",
        compte_debit="411",
        compte_credit="701",
        montant_ttc=Decimal("100"),
        source_module="self_invoice",
        source_id="F-A",
    )
    storage.save_ecriture(
        date_operation=date(2026, 4, 26),
        journal="ACH",
        numero_piece="A-A",
        libelle="achat",
        compte_debit="6011",
        compte_credit="401",
        montant_ttc=Decimal("50"),
        source_module="self_achats",
        source_id="A-A",
    )
    rows_inv = storage.list_ecritures(source_module="self_invoice")
    rows_ach = storage.list_ecritures(source_module="self_achats")
    assert len(rows_inv) == 1
    assert rows_inv[0]["numero_piece"] == "F-A"
    assert len(rows_ach) == 1
    assert rows_ach[0]["numero_piece"] == "A-A"


# ---------------- balance_par_compte ----------------

def test_balance_par_compte_aggregates_correctly(isolated_db):
    # Deux ventes sur 411/701
    for i in range(2):
        storage.save_ecriture(
            date_operation=date(2026, 4, 26),
            journal="VEN",
            numero_piece=f"F-{i}",
            libelle=f"v{i}",
            compte_debit="411",
            compte_credit="701",
            montant_ttc=Decimal("100"),
            source_module="self_invoice",
            source_id=f"F-{i}",
        )
    bal = storage.balance_par_compte()
    comptes = {b["compte"]: b for b in bal}
    assert "411" in comptes
    assert "701" in comptes
    # 411 = clients : 200 € débit, 0 € crédit
    assert comptes["411"]["total_debit"] == 200.0
    assert comptes["411"]["total_credit"] == 0.0
    # 701 = ventes : 0 € débit, 200 € crédit
    assert comptes["701"]["total_credit"] == 200.0
    assert comptes["701"]["total_debit"] == 0.0


# ---------------- stats_globales ----------------

def test_stats_globales_empty(isolated_db):
    storage.init_db()
    s = storage.stats_globales()
    assert s["nb_ecritures"] == 0
    assert s["total_volume"] == 0
    assert s["par_source"] == {}


def test_stats_globales_filled(isolated_db):
    for i in range(3):
        storage.save_ecriture(
            date_operation=date(2026, 4, 26),
            journal="VEN",
            numero_piece=f"F-{i}",
            libelle=f"v{i}",
            compte_debit="411",
            compte_credit="701",
            montant_ttc=Decimal("120"),
            source_module="self_invoice",
            source_id=f"F-{i}",
        )
    s = storage.stats_globales()
    assert s["nb_ecritures"] == 3
    assert s["total_volume"] == 360.0
    assert s["par_source"] == {"self_invoice": 3}


# ---------------- bilan_data / resultat_data ----------------

def test_resultat_data_calcule_benefice(isolated_db):
    # Vente 1000 (compte 701 / classe 7 = produits)
    storage.save_ecriture(
        date_operation=date(2026, 4, 26),
        journal="VEN",
        numero_piece="F-1",
        libelle="grosse vente",
        compte_debit="411",
        compte_credit="701",
        montant_ttc=Decimal("1000"),
        source_module="self_invoice",
        source_id="F-1",
    )
    # Achat 200 (compte 6011 / classe 6 = charges)
    storage.save_ecriture(
        date_operation=date(2026, 4, 26),
        journal="ACH",
        numero_piece="A-1",
        libelle="achat compost",
        compte_debit="6011",
        compte_credit="401",
        montant_ttc=Decimal("200"),
        source_module="self_achats",
        source_id="A-1",
    )
    r = storage.resultat_data()
    assert r["total_produits"] == 1000.0
    assert r["total_charges"] == 200.0
    assert r["resultat_net"] == 800.0
    assert r["is_benefice"] is True


def test_resultat_data_calcule_deficit(isolated_db):
    # Vente 100, achat 500 → déficit
    storage.save_ecriture(
        date_operation=date(2026, 4, 26),
        journal="VEN",
        numero_piece="F-1",
        libelle="petite vente",
        compte_debit="411",
        compte_credit="701",
        montant_ttc=Decimal("100"),
        source_module="self_invoice",
        source_id="F-1",
    )
    storage.save_ecriture(
        date_operation=date(2026, 4, 26),
        journal="ACH",
        numero_piece="A-1",
        libelle="gros achat",
        compte_debit="6011",
        compte_credit="401",
        montant_ttc=Decimal("500"),
        source_module="self_achats",
        source_id="A-1",
    )
    r = storage.resultat_data()
    assert r["total_charges"] - r["total_produits"] == 400.0
    assert r["resultat_net"] == -400.0
    assert r["is_benefice"] is False


def test_bilan_data_equilibre(isolated_db):
    """Le bilan doit être équilibré (Actif = Passif) avec résultat injecté."""
    storage.save_ecriture(
        date_operation=date(2026, 4, 26),
        journal="VEN",
        numero_piece="F-1",
        libelle="vente",
        compte_debit="411",
        compte_credit="701",
        montant_ttc=Decimal("500"),
        source_module="self_invoice",
        source_id="F-1",
    )
    b = storage.bilan_data()
    # Actif total et passif total doivent égaler (résultat injecté en passif côté capitaux)
    assert b["equilibre"] is True
    assert abs(b["ecart"]) < 0.01


# ---------------- export_fec ----------------

def test_export_fec_format_dgfip(isolated_db):
    """Vérifie format FEC : 18 colonnes tab-separated UTF-8."""
    storage.save_ecriture(
        date_operation=date(2026, 4, 26),
        journal="VEN",
        numero_piece="F-1",
        libelle="vente FEC",
        compte_debit="411",
        compte_credit="701",
        montant_ttc=Decimal("100.00"),
        montant_ht=Decimal("100.00"),
        montant_tva=Decimal("0"),
        source_module="self_invoice",
        source_id="F-1",
    )
    # export_fec retourne (filename, content)
    filename, content = storage.export_fec(siren="111222333")
    assert filename.endswith(".txt")
    assert "111222333" in filename
    lines = content.strip().split("\n")
    # Ligne 1 = header avec 18 colonnes tab-separated
    headers = lines[0].split("\t")
    assert len(headers) == 18
    # Données : 2 lignes par écriture (une débit + une crédit)
    assert len(lines) >= 3  # header + 2 lignes


# ---------------- reset_demo ----------------

def test_reset_demo_purge_all(isolated_db):
    storage.save_ecriture(
        date_operation=date(2026, 4, 26),
        journal="VEN",
        numero_piece="F-1",
        libelle="à purger",
        compte_debit="411",
        compte_credit="701",
        montant_ttc=Decimal("10"),
        source_module="self_invoice",
        source_id="F-1",
    )
    assert storage.stats_globales()["nb_ecritures"] == 1
    storage.reset_demo()
    assert storage.stats_globales()["nb_ecritures"] == 0


# ---------------- Migrations versionnées ----------------

def test_migration_table_created(isolated_db):
    """init_db crée la table _schema_migrations."""
    storage.init_db()
    with storage._conn() as c:
        rows = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='_schema_migrations'"
        ).fetchall()
    assert len(rows) == 1


def test_apply_migrations_idempotent(isolated_db, monkeypatch):
    """Appliquer plusieurs fois les mêmes migrations ne duplique rien."""
    fake_migrations = [
        (100, "test_add_dummy_column",
         "CREATE TABLE IF NOT EXISTS dummy_test (id INTEGER PRIMARY KEY);"),
    ]
    monkeypatch.setattr(storage, "MIGRATIONS", fake_migrations)
    storage.init_db()
    storage.init_db()  # 2e appel
    storage.init_db()  # 3e appel
    with storage._conn() as c:
        rows = c.execute(
            "SELECT * FROM _schema_migrations WHERE version = 100"
        ).fetchall()
    assert len(rows) == 1


def test_apply_migrations_runs_in_order(isolated_db, monkeypatch):
    fake_migrations = [
        (101, "first", "CREATE TABLE t1 (id INTEGER);"),
        (102, "second", "CREATE TABLE t2 (id INTEGER);"),
    ]
    monkeypatch.setattr(storage, "MIGRATIONS", fake_migrations)
    storage.init_db()
    with storage._conn() as c:
        rows = c.execute(
            "SELECT version, name FROM _schema_migrations WHERE version IN (101, 102) ORDER BY version"
        ).fetchall()
    versions = [r["version"] for r in rows]
    names = [r["name"] for r in rows]
    assert versions == [101, 102]
    assert names == ["first", "second"]


# ---------------- Métadonnées JSON ----------------

def test_metadata_json_roundtrip(isolated_db):
    """Le metadata_json est stocké/lu sans transformation."""
    meta = {"client": "ACME", "regime": "reel", "facturx_profile": "EN16931"}
    storage.save_ecriture(
        date_operation=date(2026, 4, 26),
        journal="VEN",
        numero_piece="F-META",
        libelle="meta",
        compte_debit="411",
        compte_credit="701",
        montant_ttc=Decimal("10"),
        source_module="self_invoice",
        source_id="F-META",
        metadata_json=json.dumps(meta),
    )
    found = storage.find_ecriture_by_source("self_invoice", "F-META")
    assert found is not None
    parsed = json.loads(found["metadata_json"])
    assert parsed == meta
