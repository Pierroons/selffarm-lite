"""Clé du coffre : privée dès sa naissance, jamais écrasée par une course,
remplacée en un geste à la restauration."""

from __future__ import annotations

import os
import stat

import pytest

from self_backup import vault


@pytest.fixture
def dossier(tmp_path, monkeypatch):
    monkeypatch.setenv("SELFFARM_COMPTA_DB", str(tmp_path / "compta.db"))
    return tmp_path


def _mode(p) -> int:
    return stat.S_IMODE(os.stat(p).st_mode)


def _espionne(monkeypatch, nom: str) -> list[int]:
    """Relève les permissions du fichier au moment où il prend son nom."""
    vus: list[int] = []
    reel = getattr(os, nom)

    def espion(src, dst, *a, **k):
        vus.append(_mode(src))
        return reel(src, dst, *a, **k)

    monkeypatch.setattr(os, nom, espion)
    return vus


def test_la_cle_generee_est_privee_avant_de_prendre_son_nom(dossier, monkeypatch):
    vus = _espionne(monkeypatch, "link")
    cle = vault.get_or_create_vault_key()
    assert vus == [0o600]
    assert len(cle) == 44
    assert vault.get_or_create_vault_key() == cle
    assert [f.name for f in dossier.iterdir()] == ["vault.key"]


def test_le_processus_qui_perd_la_course_garde_la_cle_du_gagnant(dossier):
    p = dossier / "k"
    p.write_bytes(b"gagnant")
    assert vault.write_key_file(p, b"perdant") is False
    assert p.read_bytes() == b"gagnant"
    assert [f.name for f in dossier.iterdir()] == ["k"]


def test_l_import_remplace_la_cle_et_la_rend_privee(dossier, monkeypatch):
    from cryptography.fernet import Fernet

    p = dossier / "vault.key"
    p.write_bytes(b"ancienne")
    p.chmod(0o644)
    vus = _espionne(monkeypatch, "replace")
    neuve = Fernet.generate_key()
    vault.import_vault_key(neuve.decode("ascii"))
    assert vus == [0o600]
    assert p.read_bytes() == neuve
    assert _mode(p) == 0o600
    assert [f.name for f in dossier.iterdir()] == ["vault.key"]


def test_un_import_invalide_laisse_la_cle_en_place(dossier):
    p = dossier / "vault.key"
    p.write_bytes(b"en-place")
    with pytest.raises(ValueError):
        vault.import_vault_key("pas-une-cle-fernet")
    assert p.read_bytes() == b"en-place"
