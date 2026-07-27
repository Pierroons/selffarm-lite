"""Tests du hub compta SQLite — self_agri_book.storage."""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from decimal import Decimal

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
    kwargs = {
        "date_operation": date(2026, 4, 26),
        "journal": "VEN",
        "numero_piece": "F-2026-0042",
        "libelle": "Vente dédup test",
        "compte_debit": "411",
        "compte_credit": "701",
        "montant_ttc": Decimal("250.00"),
        "source_module": "self_invoice",
        "source_id": "F-2026-0042",
    }
    eid1, created1 = storage.save_ecriture(**kwargs)
    eid2, created2 = storage.save_ecriture(**kwargs)
    assert created1 is True
    assert created2 is False
    assert eid1 == eid2


def test_save_ecriture_dedup_can_be_bypassed(isolated_db):
    """allow_duplicate=True force une insertion même si la source existe."""
    kwargs = {
        "date_operation": date(2026, 4, 26),
        "journal": "VEN",
        "numero_piece": "F-2026-9999",
        "libelle": "dup",
        "compte_debit": "411",
        "compte_credit": "701",
        "montant_ttc": Decimal("10.00"),
        "source_module": "self_invoice",
        "source_id": "F-2026-9999",
    }
    eid1, _ = storage.save_ecriture(**kwargs)
    eid2, created2 = storage.save_ecriture(**kwargs, allow_duplicate=True)
    assert eid2 != eid1
    assert created2 is True


def test_save_ecriture_no_dedup_without_source(isolated_db):
    """Pas de source_module → chaque save crée une nouvelle écriture."""
    kwargs = {
        "date_operation": date(2026, 4, 26),
        "journal": "MAN",
        "numero_piece": "MAN-001",
        "libelle": "manuel sans source",
        "compte_debit": "606",
        "compte_credit": "512",
        "montant_ttc": Decimal("50.00"),
    }
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
        montant_ttc=Decimal(100),
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
        montant_ttc=Decimal(50),
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
            montant_ttc=Decimal(100),
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
            montant_ttc=Decimal(120),
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
        montant_ttc=Decimal(1000),
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
        montant_ttc=Decimal(200),
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
        montant_ttc=Decimal(100),
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
        montant_ttc=Decimal(500),
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
        montant_ttc=Decimal(500),
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
        montant_tva=Decimal(0),
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
        montant_ttc=Decimal(10),
        source_module="self_invoice",
        source_id="F-1",
    )
    assert storage.stats_globales()["nb_ecritures"] == 1
    storage.reset_demo()
    assert storage.stats_globales()["nb_ecritures"] == 0


# ---------------- Compteur factures séquentiel ----------------

def test_next_numero_facture_starts_at_0001(isolated_db):
    n = storage.next_numero_facture(2026)
    assert n == "F-2026-0001"


def test_next_numero_facture_increments(isolated_db):
    n1 = storage.next_numero_facture(2026)
    n2 = storage.next_numero_facture(2026)
    n3 = storage.next_numero_facture(2026)
    assert n1 == "F-2026-0001"
    assert n2 == "F-2026-0002"
    assert n3 == "F-2026-0003"


def test_next_numero_facture_per_year(isolated_db):
    storage.next_numero_facture(2026)
    storage.next_numero_facture(2026)
    storage.next_numero_facture(2027)
    storage.next_numero_facture(2026)
    # Compteurs séparés par année
    last_2026 = storage.peek_numero_facture(2026)
    last_2027 = storage.peek_numero_facture(2027)
    assert last_2026 == "F-2026-0004"
    assert last_2027 == "F-2027-0002"


def test_next_numero_facture_per_prefix(isolated_db):
    f1 = storage.next_numero_facture(2026, "F")
    av1 = storage.next_numero_facture(2026, "AV")
    f2 = storage.next_numero_facture(2026, "F")
    av2 = storage.next_numero_facture(2026, "AV")
    assert f1 == "F-2026-0001"
    assert f2 == "F-2026-0002"
    assert av1 == "AV-2026-0001"
    assert av2 == "AV-2026-0002"


def test_peek_numero_facture_does_not_increment(isolated_db):
    p1 = storage.peek_numero_facture(2026)
    p2 = storage.peek_numero_facture(2026)
    p3 = storage.peek_numero_facture(2026)
    assert p1 == p2 == p3 == "F-2026-0001"
    # Et après un vrai next, peek renvoie le suivant
    storage.next_numero_facture(2026)
    assert storage.peek_numero_facture(2026) == "F-2026-0002"


def test_compteur_extends_to_5_digits_after_9999(isolated_db):
    """Le format passe automatiquement à 5 chiffres au-delà de 9999/an."""
    storage.init_db()  # garantit que la table compteurs_factures existe
    with storage._conn() as c:
        c.execute(
            "INSERT INTO compteurs_factures (annee, prefix, dernier_numero) VALUES (?, ?, ?)",
            (2026, "F", 9999),
        )
    n = storage.next_numero_facture(2026)
    assert n == "F-2026-10000"


def test_compteur_initialisation_depuis_historique(tmp_path, monkeypatch):
    """La migration 1 doit pré-remplir le compteur depuis les écritures existantes."""
    db_file = tmp_path / "compta_with_history.db"
    monkeypatch.setenv("SELFFARM_COMPTA_DB", str(db_file))
    # Crée des écritures self_invoice avec des numéros aléatoires (style démo)
    storage.save_ecriture(
        date_operation=date(2026, 4, 26),
        journal="VEN",
        numero_piece="F-2026-3742",  # ancien numéro random
        libelle="vente démo",
        compte_debit="411",
        compte_credit="701",
        montant_ttc=Decimal(100),
        source_module="self_invoice",
        source_id="F-2026-3742",
    )
    storage.save_ecriture(
        date_operation=date(2026, 4, 26),
        journal="VEN",
        numero_piece="F-2026-8421",
        libelle="autre vente démo",
        compte_debit="411",
        compte_credit="701",
        montant_ttc=Decimal(200),
        source_module="self_invoice",
        source_id="F-2026-8421",
    )
    # init_db re-appelée → la migration 1 a déjà tourné via la fixture, mais
    # on simule un init "vierge" en supprimant la table compteurs et en
    # ré-appliquant la migration manuellement
    with storage._conn() as c:
        c.execute("DROP TABLE IF EXISTS compteurs_factures")
        c.execute("DELETE FROM _schema_migrations WHERE version = 1")
    storage.init_db()
    # Le compteur doit reprendre au max + 1 = 8422
    next_n = storage.next_numero_facture(2026)
    assert next_n == "F-2026-8422"


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


# ---------------- Hash chain + verrouillage (PAF CGI 289-VII) ----------------

def test_save_ecriture_calcule_hash_data(isolated_db):
    eid, _ = storage.save_ecriture(
        date_operation=date(2026, 4, 26),
        journal="VEN",
        numero_piece="F-1",
        libelle="hash test",
        compte_debit="411",
        compte_credit="701",
        montant_ttc=Decimal(100),
        source_module="self_invoice",
        source_id="F-1",
    )
    with storage._conn() as c:
        row = c.execute(
            "SELECT hash_data, hash_previous FROM ecritures_comptables WHERE id=?",
            (eid,),
        ).fetchone()
    assert row["hash_data"] is not None
    assert len(row["hash_data"]) == 64  # SHA256 hex
    assert row["hash_previous"] == ""   # première écriture


def test_chain_links_consecutive_ecritures(isolated_db):
    eid1, _ = storage.save_ecriture(
        date_operation=date(2026, 4, 26),
        journal="VEN",
        numero_piece="F-1",
        libelle="v1",
        compte_debit="411",
        compte_credit="701",
        montant_ttc=Decimal(100),
        source_module="self_invoice",
        source_id="F-1",
    )
    eid2, _ = storage.save_ecriture(
        date_operation=date(2026, 4, 26),
        journal="VEN",
        numero_piece="F-2",
        libelle="v2",
        compte_debit="411",
        compte_credit="701",
        montant_ttc=Decimal(200),
        source_module="self_invoice",
        source_id="F-2",
    )
    with storage._conn() as c:
        r1 = c.execute("SELECT hash_data FROM ecritures_comptables WHERE id=?", (eid1,)).fetchone()
        r2 = c.execute("SELECT hash_previous FROM ecritures_comptables WHERE id=?", (eid2,)).fetchone()
    assert r2["hash_previous"] == r1["hash_data"]


def test_verify_chain_returns_valid_for_clean_data(isolated_db):
    for i in range(3):
        storage.save_ecriture(
            date_operation=date(2026, 4, 26),
            journal="VEN",
            numero_piece=f"F-{i}",
            libelle=f"v{i}",
            compte_debit="411",
            compte_credit="701",
            montant_ttc=Decimal(f"{(i + 1) * 100}"),
            source_module="self_invoice",
            source_id=f"F-{i}",
        )
    res = storage.verify_chain()
    assert res["valid"] is True
    assert res["nb_ecritures"] == 3
    assert res["broken_at"] is None


def test_verify_chain_detects_tampering(isolated_db):
    """Modifier directement une écriture en SQL doit casser la chaîne."""
    eid, _ = storage.save_ecriture(
        date_operation=date(2026, 4, 26),
        journal="VEN",
        numero_piece="F-1",
        libelle="originale",
        compte_debit="411",
        compte_credit="701",
        montant_ttc=Decimal(100),
        source_module="self_invoice",
        source_id="F-1",
    )
    storage.save_ecriture(
        date_operation=date(2026, 4, 26),
        journal="VEN",
        numero_piece="F-2",
        libelle="suivante",
        compte_debit="411",
        compte_credit="701",
        montant_ttc=Decimal(200),
        source_module="self_invoice",
        source_id="F-2",
    )
    # Falsification : modifie le montant directement en SQL (sans passer par save_ecriture)
    with storage._conn() as c:
        c.execute(
            "UPDATE ecritures_comptables SET montant_ttc='999999' WHERE id=?",
            (eid,),
        )
    res = storage.verify_chain()
    assert res["valid"] is False
    assert res["broken_at"] == eid


def test_locked_ecriture_at_creation(isolated_db):
    eid, _ = storage.save_ecriture(
        date_operation=date(2026, 4, 26),
        journal="VEN",
        numero_piece="F-LOCK",
        libelle="locked at creation",
        compte_debit="411",
        compte_credit="701",
        montant_ttc=Decimal(100),
        source_module="self_invoice",
        source_id="F-LOCK",
        locked=True,
    )
    with storage._conn() as c:
        row = c.execute(
            "SELECT locked, locked_at FROM ecritures_comptables WHERE id=?", (eid,),
        ).fetchone()
    assert row["locked"] == 1
    assert row["locked_at"] is not None


def test_lock_ecriture_post_creation(isolated_db):
    eid, _ = storage.save_ecriture(
        date_operation=date(2026, 4, 26),
        journal="VEN",
        numero_piece="F-LOCK2",
        libelle="à verrouiller",
        compte_debit="411",
        compte_credit="701",
        montant_ttc=Decimal(50),
        source_module="self_invoice",
        source_id="F-LOCK2",
    )
    # Pas locked au départ
    with storage._conn() as c:
        assert c.execute("SELECT locked FROM ecritures_comptables WHERE id=?", (eid,)).fetchone()["locked"] == 0
    # On verrouille
    assert storage.lock_ecriture(eid) is True
    with storage._conn() as c:
        assert c.execute("SELECT locked FROM ecritures_comptables WHERE id=?", (eid,)).fetchone()["locked"] == 1
    # 2e appel = no-op
    assert storage.lock_ecriture(eid) is False


def test_lock_ecriture_raises_if_unknown(isolated_db):
    storage.init_db()
    with pytest.raises(ValueError, match="introuvable"):
        storage.lock_ecriture(999999)


def test_hash_pdf_stored(isolated_db):
    eid, _ = storage.save_ecriture(
        date_operation=date(2026, 4, 26),
        journal="VEN",
        numero_piece="F-PDF",
        libelle="avec hash PDF",
        compte_debit="411",
        compte_credit="701",
        montant_ttc=Decimal(100),
        source_module="self_invoice",
        source_id="F-PDF",
        hash_pdf="abc123" * 10 + "abcd",  # 64 chars fake hash
    )
    with storage._conn() as c:
        row = c.execute(
            "SELECT hash_pdf FROM ecritures_comptables WHERE id=?", (eid,)
        ).fetchone()
    assert row["hash_pdf"] == "abc123" * 10 + "abcd"


# ---------------- Audit log append-only ----------------

def test_audit_log_created_on_ecriture(isolated_db):
    storage.save_ecriture(
        date_operation=date(2026, 4, 26),
        journal="VEN",
        numero_piece="F-1",
        libelle="audited",
        compte_debit="411",
        compte_credit="701",
        montant_ttc=Decimal(100),
        source_module="self_invoice",
        source_id="F-1",
    )
    log_entries = storage.list_audit_log()
    assert len(log_entries) >= 1
    actions = [e["action"] for e in log_entries]
    assert "ecriture.create" in actions


def test_audit_log_append_only_no_update(isolated_db):
    """Trigger SQLite doit refuser tout UPDATE sur audit_log."""
    storage.write_audit(action="test.action", target_type="x", target_id="1")
    with storage._conn() as c, pytest.raises(sqlite3.IntegrityError, match="append-only"):
        c.execute("UPDATE audit_log SET action='hack' WHERE id=1")


def test_audit_log_append_only_no_delete(isolated_db):
    """Trigger SQLite doit refuser tout DELETE sur audit_log."""
    storage.write_audit(action="test.action", target_type="x", target_id="1")
    with storage._conn() as c, pytest.raises(sqlite3.IntegrityError, match="append-only"):
        c.execute("DELETE FROM audit_log")


def test_lock_action_audited(isolated_db):
    eid, _ = storage.save_ecriture(
        date_operation=date(2026, 4, 26),
        journal="VEN",
        numero_piece="F-AUDIT",
        libelle="lock audit",
        compte_debit="411",
        compte_credit="701",
        montant_ttc=Decimal(10),
        source_module="self_invoice",
        source_id="F-AUDIT",
    )
    storage.lock_ecriture(eid)
    log_entries = storage.list_audit_log()
    actions = [e["action"] for e in log_entries]
    assert "ecriture.lock" in actions


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
        montant_ttc=Decimal(10),
        source_module="self_invoice",
        source_id="F-META",
        metadata_json=json.dumps(meta),
    )
    found = storage.find_ecriture_by_source("self_invoice", "F-META")
    assert found is not None
    parsed = json.loads(found["metadata_json"])
    assert parsed == meta
