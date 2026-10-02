"""Restauration poussée par le téléphone : une installation qui a des données
ne déchiffre qu'avec sa propre clé de coffre, et la démo publique la refuse."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from cryptography.fernet import Fernet
from self_agri_book import exploitation, storage
from self_backup import make_backup
from self_backup.vault import get_or_create_vault_key

import webapp.main

ROUTE = "/api/pos/backup/restore-push"


def _base(monkeypatch, dossier, piece: str, *, onboarding: bool = True) -> None:
    monkeypatch.setenv("SELFFARM_COMPTA_DB", str(dossier / "compta.db"))
    if onboarding:
        exploitation.save_exploitation(
            {"nom": "Ferme", "statut": "JA", "commune": "C", "saison_courante": 2026})
        exploitation.mark_onboarding_done()
    storage.save_ecriture(
        date_operation=date(2026, 10, 2), journal="VEN", numero_piece=piece,
        libelle=piece, compte_debit="411", compte_credit="701",
        montant_ttc=Decimal(100), source_module="self_invoice", source_id=piece)


def _pieces() -> list[str]:
    return [e["numero_piece"] for e in storage.list_ecritures()]


@pytest.fixture
def archive_du_tiers(tmp_path, monkeypatch) -> bytes:
    """Une archive valide, fabriquée ailleurs, avec une écriture qui n'est pas du paysan."""
    _base(monkeypatch, tmp_path / "tiers", "F-TIERS")
    zip_bytes, _ = make_backup(version="test")
    return zip_bytes


@pytest.fixture
def paysan(tmp_path, monkeypatch, archive_du_tiers) -> bytes:
    (tmp_path / "paysan").mkdir()
    _base(monkeypatch, tmp_path / "paysan", "F-PAYSAN")
    return get_or_create_vault_key()


def _pousse(client, blob: bytes, cle: bytes):
    return client.post(ROUTE, content=blob, headers={
        "Content-Type": "application/octet-stream",
        "X-Vault-Key": cle.decode("ascii"), "X-Confirm-Rollback": "1"})


def test_un_tiers_ne_remplace_ni_la_cle_ni_la_base(client, paysan, archive_du_tiers):
    cle_tiers = Fernet.generate_key()
    r = _pousse(client, Fernet(cle_tiers).encrypt(archive_du_tiers), cle_tiers)
    assert r.status_code == 400
    assert get_or_create_vault_key() == paysan
    assert _pieces() == ["F-PAYSAN"]


def test_le_telephone_appaire_restaure_avec_la_cle_du_pc(client, paysan, archive_du_tiers):
    r = _pousse(client, Fernet(paysan).encrypt(archive_du_tiers), paysan)
    assert r.status_code == 200, r.text
    assert r.json()["restored"] is True
    assert "F-TIERS" in _pieces()


def test_un_pc_vierge_accepte_la_cle_du_telephone(
        client, tmp_path, monkeypatch, archive_du_tiers):
    (tmp_path / "neuf").mkdir()
    _base(monkeypatch, tmp_path / "neuf", "F-VIDE", onboarding=False)
    # Le middleware d'onboarding redirige tout PC vierge vers l'assistant ;
    # on le laisse passer pour éprouver la règle de la route elle-même.
    monkeypatch.setattr(webapp.main, "is_onboarding_done", lambda: True)
    cle_tel = Fernet.generate_key()
    r = _pousse(client, Fernet(cle_tel).encrypt(archive_du_tiers), cle_tel)
    assert r.status_code == 200, r.text
    assert get_or_create_vault_key() == cle_tel


def test_la_demo_publique_refuse_la_restauration(client, paysan, monkeypatch):
    monkeypatch.setenv("SELFFARM_ENV", "demo")
    r = _pousse(client, Fernet(paysan).encrypt(b"x"), paysan)
    assert r.status_code == 404
