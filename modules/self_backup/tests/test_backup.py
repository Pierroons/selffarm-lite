"""Tests du module self_backup — export/import ZIP de la DB compta."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import date
from decimal import Decimal

import pytest

from self_agri_book import storage
from self_backup import make_backup, restore_from_bytes


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_compta.db"
    monkeypatch.setenv("SELFFARM_COMPTA_DB", str(db_file))
    yield db_file


def _seed_db(n: int = 3):
    for i in range(n):
        storage.save_ecriture(
            date_operation=date(2026, 4, 26),
            journal="VEN",
            numero_piece=f"F-{i}",
            libelle=f"vente {i}",
            compte_debit="411",
            compte_credit="701",
            montant_ttc=Decimal(f"{(i + 1) * 100}"),
            source_module="self_invoice",
            source_id=f"F-{i}",
        )


def test_make_backup_returns_zip_with_required_files(isolated_db):
    _seed_db(2)
    zip_bytes, filename = make_backup(version="0.2.0-test")
    assert zip_bytes
    assert filename.endswith(".zip")
    assert "selffarm-backup" in filename
    assert "2ecr" in filename

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        assert "compta.db" in names
        assert "manifest.json" in names
        assert "README.md" in names

        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert manifest["selffarm_version"] == "0.2.0-test"
        assert manifest["stats"]["nb_ecritures"] == 2
        assert "db_sha256" in manifest
        assert manifest["manifest_version"] >= 1


def test_make_backup_raises_if_db_absent(isolated_db):
    # DB pas encore initialisée → fichier absent
    with pytest.raises(FileNotFoundError):
        make_backup(version="0.2.0-test")


def test_restore_from_bytes_creates_db(isolated_db, tmp_path):
    _seed_db(3)
    zip_bytes, _ = make_backup(version="0.2.0-test")
    initial_count = storage.stats_globales()["nb_ecritures"]
    assert initial_count == 3

    # Reset DB local pour simuler import sur instance vide
    storage.reset_demo()
    assert storage.stats_globales()["nb_ecritures"] == 0

    result = restore_from_bytes(zip_bytes)
    assert result["restored"] is True
    assert result["sha256_match"] is True

    # Après restore, les écritures doivent être de retour
    assert storage.stats_globales()["nb_ecritures"] == 3


def test_restore_creates_backup_of_old_db(isolated_db, tmp_path):
    _seed_db(2)
    zip_bytes, _ = make_backup(version="0.2.0-test")

    # Modifier la DB pour qu'elle soit différente
    storage.save_ecriture(
        date_operation=date(2026, 4, 26),
        journal="VEN",
        numero_piece="F-NEW",
        libelle="ajout post-backup",
        compte_debit="411",
        compte_credit="701",
        montant_ttc=Decimal("999"),
        source_module="self_invoice",
        source_id="F-NEW",
    )

    result = restore_from_bytes(zip_bytes)
    assert result["old_backup_path"] is not None
    from pathlib import Path
    assert Path(result["old_backup_path"]).exists()
    assert ".bak-" in result["old_backup_path"]


def test_restore_rejects_invalid_archive(isolated_db):
    # Un blob non-ZIP lève BadZipFile (qu'on laisse remonter — la route HTTP
    # le traduit en 500). On vérifie ici qu'aucune données n'est altérée.
    import zipfile as _zipfile
    with pytest.raises((_zipfile.BadZipFile, ValueError)):
        restore_from_bytes(b"this is not a zip")


def test_restore_rejects_archive_without_manifest(isolated_db):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("compta.db", b"fake db")
    with pytest.raises(ValueError, match="manifest.json absent"):
        restore_from_bytes(buf.getvalue())


def test_make_backup_includes_sha256(isolated_db):
    _seed_db(1)
    zip_bytes, _ = make_backup()
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        sha = manifest["db_sha256"]
        assert isinstance(sha, str)
        assert len(sha) == 64  # SHA256 hex


def test_roundtrip_backup_restore_preserves_data(isolated_db):
    _seed_db(5)
    zip_bytes, _ = make_backup()

    # Reset complet
    storage.reset_demo()
    storage.save_ecriture(
        date_operation=date(2026, 4, 26),
        journal="ACH",
        numero_piece="A-X",
        libelle="parasite",
        compte_debit="606",
        compte_credit="401",
        montant_ttc=Decimal("50"),
        source_module="self_achats",
        source_id="A-X",
    )
    # Maintenant 1 écriture (parasite). Restore va l'écraser.

    restore_from_bytes(zip_bytes)

    rows = storage.list_ecritures()
    # Le parasite ne doit plus exister, on retrouve les 5 originaux
    assert len(rows) == 5
    numeros = sorted(r["numero_piece"] for r in rows)
    assert numeros == ["F-0", "F-1", "F-2", "F-3", "F-4"]
