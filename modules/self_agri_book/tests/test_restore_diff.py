"""Restauration d'une sauvegarde : rien de ce qu'elle porte ne se perd, quelle que
soit la base qui la reçoit — vierge, avec des données, ou d'une autre version."""

from __future__ import annotations

import io
import sqlite3
import zipfile
from datetime import date
from decimal import Decimal

import pytest
from cryptography.fernet import Fernet
from self_backup import EXTERNAL_SUBDIR, make_backup, restore_from_bytes, restore_from_support
from self_backup.vault import get_or_create_vault_key
from self_culture.cultures import save_parcelle
from self_elevage.elevage import ELEVAGE_MIGRATIONS, save_bande, save_ponte

from self_agri_book import storage
from self_agri_book.exploitation import is_onboarding_done, mark_onboarding_done, save_exploitation


@pytest.fixture
def base(tmp_path, monkeypatch):
    """Fait pointer l'app vers la base d'un PC : base("ancien"), puis base("neuf")."""
    def vers(nom: str):
        chemin = tmp_path / nom / "compta.db"
        monkeypatch.setenv("SELFFARM_COMPTA_DB", str(chemin))
        storage.init_db()   # ce que fait la première page affichée
        return chemin
    return vers


def _profil():
    save_exploitation({"nom": "Ferme", "statut": "JA", "commune": "C", "saison_courante": 2026})
    mark_onboarding_done()


def _ecriture(piece: str):
    storage.save_ecriture(
        date_operation=date(2026, 10, 3), journal="VEN", numero_piece=piece, libelle="vente",
        compte_debit="411", compte_credit="701", montant_ttc=Decimal(100),
        source_module="self_invoice", source_id=piece,
    )


def _compte(table: str) -> int:
    with storage._conn() as c:
        return c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _tables() -> set[str]:
    with storage._conn() as c:
        return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _retoucher(zip_bytes: bytes, sql: str, tmp_path) -> bytes:
    """Rejoue `sql` sur la base d'une archive, pour fabriquer une sauvegarde d'un autre âge."""
    src = zipfile.ZipFile(io.BytesIO(zip_bytes))
    db = tmp_path / "retouche.db"
    db.write_bytes(src.read("compta.db"))
    conn = sqlite3.connect(db)
    conn.executescript(sql)
    conn.close()
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as dst:
        for name in src.namelist():
            dst.writestr(name, db.read_bytes() if name == "compta.db" else src.read(name))
    return out.getvalue()


def test_un_pc_neuf_recoit_toute_la_sauvegarde(base):
    base("ancien")
    _profil()
    save_parcelle({"nom": "Le Pré", "commune": "C", "surface_ha": 1.5})
    save_bande({"nom": "Pondeuses", "effectif_initial": 40})
    archive, _ = make_backup(version="test")

    base("neuf")
    r = restore_from_bytes(archive)

    assert r["mode"] == "fresh"
    assert (_compte("parcelles"), _compte("bande")) == (1, 1)
    assert is_onboarding_done()
    save_parcelle({"nom": "La Lande", "commune": "C", "surface_ha": 2})
    assert _compte("parcelles") == 2


def test_une_base_avec_des_donnees_recoit_la_verticale_qui_lui_manque(base):
    base("ancien")
    _profil()
    _ecriture("F-ANCIEN")
    save_bande({"nom": "Pondeuses", "effectif_initial": 40})
    archive, _ = make_backup(version="test")

    base("neuf")
    _profil()
    _ecriture("F-NEUF")
    r = restore_from_bytes(archive)

    assert r["mode"] == "merge"
    assert r["importees"]["self_elevage"]["bande"] == 1
    assert _compte("ecritures_comptables") == 2
    with storage._conn() as c:
        versions = c.execute(
            "SELECT COUNT(*) FROM _schema_migrations WHERE module = 'self_elevage'").fetchone()[0]
    assert versions == len(ELEVAGE_MIGRATIONS)
    save_bande({"nom": "Poulets", "effectif_initial": 10})
    assert _compte("bande") == 2


def test_une_sauvegarde_plus_ancienne_qu_une_colonne_se_fusionne(base, tmp_path):
    base("ancien")
    _profil()
    _ecriture("F-ANCIEN")
    bande = save_bande({"nom": "Pondeuses", "effectif_initial": 40})
    save_ponte({"bande_id": bande["id"], "date_ponte": "2026-10-01", "nb_oeufs": 30})
    archive, _ = make_backup(version="test")
    archive = _retoucher(archive, """
        ALTER TABLE ponte DROP COLUMN nb_declasses;
        DELETE FROM _schema_migrations WHERE module = 'self_elevage' AND version = 5;
    """, tmp_path)

    base("neuf")
    _profil()
    _ecriture("F-NEUF")
    save_bande({"nom": "Poulets", "effectif_initial": 10})
    r = restore_from_bytes(archive)

    assert r["mode"] == "merge"
    with storage._conn() as c:
        assert [tuple(r) for r in c.execute("SELECT nb_oeufs, nb_declasses FROM ponte")] == [(30, 0)]


def test_un_registre_d_avant_0_2_0_se_restaure(base, tmp_path):
    base("ancien")
    _profil()
    _ecriture("F-ANCIEN")
    archive, _ = make_backup(version="test")
    archive = _retoucher(archive, """
        CREATE TABLE _ancien AS SELECT version, name, applied_at FROM _schema_migrations
            WHERE module = 'self_agri_book';
        DROP TABLE _schema_migrations;
        ALTER TABLE _ancien RENAME TO _schema_migrations;
    """, tmp_path)

    base("neuf")
    r = restore_from_bytes(archive)

    assert r["mode"] == "fresh"
    assert {"_schema_migrations", "_schema_migrations_avant_0_2_0"} <= _tables()
    with storage._conn() as c:
        assert "module" in {row[1] for row in c.execute("PRAGMA table_info(_schema_migrations)")}
    assert _compte("ecritures_comptables") == 1
    assert is_onboarding_done()


def test_une_table_inconnue_est_signalee_et_pas_importee(base, tmp_path):
    base("ancien")
    _profil()
    _ecriture("F-ANCIEN")
    archive, _ = make_backup(version="test")
    archive = _retoucher(archive, """
        CREATE TABLE plan_culture_v3 (id INTEGER PRIMARY KEY);
        INSERT INTO plan_culture_v3 VALUES (1);
    """, tmp_path)

    base("neuf")
    _profil()
    _ecriture("F-NEUF")
    r = restore_from_bytes(archive)

    assert r["signalees"] == ["plan_culture_v3"]
    assert "plan_culture_v3" not in _tables()


def _disque_avec(archive: bytes, tmp_path) -> tuple[str, bytes]:
    dossier = tmp_path / "disque" / EXTERNAL_SUBDIR
    dossier.mkdir(parents=True)
    (dossier / "sauvegarde.zip").write_bytes(archive)
    cle = Fernet.generate_key()
    (dossier / "vault.key").write_bytes(cle)
    return str(tmp_path / "disque"), cle


def test_le_disque_externe_ne_remplace_pas_la_cle_d_un_pc_appaire(base, tmp_path):
    base("ancien")
    _profil()
    _ecriture("F-ANCIEN")
    disque, cle_du_disque = _disque_avec(make_backup(version="test")[0], tmp_path)

    base("neuf")
    _profil()
    _ecriture("F-NEUF")
    cle_du_pc = get_or_create_vault_key()
    r = restore_from_support(disque, "sauvegarde.zip")

    assert "vault_recovered" not in r
    assert get_or_create_vault_key() == cle_du_pc != cle_du_disque


def test_le_disque_externe_rend_sa_cle_a_un_pc_neuf(base, tmp_path):
    base("ancien")
    _profil()
    _ecriture("F-ANCIEN")
    disque, cle_du_disque = _disque_avec(make_backup(version="test")[0], tmp_path)

    base("neuf")
    r = restore_from_support(disque, "sauvegarde.zip")

    assert r["vault_recovered"] is True
    assert get_or_create_vault_key() == cle_du_disque
