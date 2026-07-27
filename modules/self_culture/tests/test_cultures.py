"""Tests du découplage noyau/verticale pour self_culture.cultures.

Vérifie que le schéma agri (parcelle/plan_culture) est porté par la verticale et
non par le noyau compta, via le mécanisme de migrations namespacées.
"""

from __future__ import annotations

import sqlite3

import pytest
from self_agri_book import storage

from self_culture import cultures


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Force la DB SQLite vers un fichier temporaire par test."""
    db_file = tmp_path / "test_compta.db"
    monkeypatch.setenv("SELFFARM_COMPTA_DB", str(db_file))
    yield db_file


def _tables(db_file) -> set[str]:
    con = sqlite3.connect(str(db_file))
    try:
        return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        con.close()


def _tracking(db_file) -> set[tuple[str, int]]:
    con = sqlite3.connect(str(db_file))
    try:
        return {(r[0], r[1]) for r in con.execute("SELECT module, version FROM _schema_migrations")}
    finally:
        con.close()


def test_noyau_seul_ne_cree_pas_parcelle(isolated_db):
    """init_db() (noyau agnostique) ne crée AUCUNE table agricole."""
    storage.init_db()
    tables = _tables(isolated_db)
    assert "parcelle" not in tables
    assert "plan_culture" not in tables
    # Le tracking ne contient que le namespace noyau, jamais self_culture.
    modules = {m for m, _ in _tracking(isolated_db)}
    assert modules == {"self_agri_book"}


def test_verticale_cree_son_schema_au_premier_acces(isolated_db):
    """Une opération CRUD culture crée parcelle/plan_culture sous self_culture/1,2."""
    p = cultures.save_parcelle(
        {"nom": "Champ test", "commune": "Sainte-Foy", "surface_ha": 1.5, "statut": "bio"}
    )
    assert p["id"] >= 1
    tables = _tables(isolated_db)
    assert "parcelle" in tables and "plan_culture" in tables
    tracking = _tracking(isolated_db)
    assert ("self_culture", 1) in tracking
    assert ("self_culture", 2) in tracking
    # Le noyau coexiste dans son propre namespace.
    assert any(m == "self_agri_book" for m, _ in tracking)


def test_ensure_schema_idempotent(isolated_db):
    """Rejouer _ensure_schema ne duplique pas le tracking et ne casse rien."""
    cultures._ensure_schema()
    cultures._ensure_schema()
    cultures._ensure_schema()
    versions = [v for m, v in _tracking(isolated_db) if m == "self_culture"]
    assert sorted(versions) == [1, 2]


def test_apply_module_migrations_isolation_namespaces(isolated_db):
    """Deux modules peuvent porter la même version sans collision (clé composite)."""
    storage.apply_module_migrations(
        "vertical_x", [(1, "create_x", "CREATE TABLE IF NOT EXISTS vx (id INTEGER PRIMARY KEY);")]
    )
    storage.apply_module_migrations(
        "vertical_y", [(1, "create_y", "CREATE TABLE IF NOT EXISTS vy (id INTEGER PRIMARY KEY);")]
    )
    tracking = _tracking(isolated_db)
    assert ("vertical_x", 1) in tracking
    assert ("vertical_y", 1) in tracking
    tables = _tables(isolated_db)
    assert {"vx", "vy"} <= tables
