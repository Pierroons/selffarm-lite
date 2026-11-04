"""La sauvegarde SFTP est une option : paramiko vient avec l'extra `sftp`, absent du
verrou de prod et de l'image Docker. Sans lui, le test de connexion et la sauvegarde
le disent en clair, et la page le dit avant le formulaire."""

from __future__ import annotations

import pytest
from self_backup import remote


@pytest.fixture
def sans_option(monkeypatch):
    monkeypatch.setattr(remote, "sftp_disponible", lambda: False)


@pytest.fixture
def avec_option(monkeypatch):
    monkeypatch.setattr(remote, "sftp_disponible", lambda: True)


def test_le_test_de_connexion_nomme_l_option(sans_option):
    r = remote.test_sftp({"remote_dir": "/sauvegardes", "gpg_recipient": "x"})
    assert r == {"ok": False, "message": remote.OPTION_ABSENTE}


def test_la_sauvegarde_refuse_avant_de_rien_preparer(sans_option, monkeypatch):
    def interdit(**_):
        raise AssertionError("make_backup appelé sans l'option")
    monkeypatch.setattr(remote, "make_backup", interdit)
    with pytest.raises(RuntimeError, match="option à installer"):
        remote.backup_to_sftp(version="test")


def test_la_page_annonce_l_option_absente(client, sans_option):
    r = client.get("/backup")
    assert r.status_code == 200
    assert "Option à installer" in r.text
    assert "la clé du serveur est acceptée sans vérification" in r.text


def test_la_page_garde_la_limite_quand_l_option_est_la(client, avec_option):
    r = client.get("/backup")
    assert r.status_code == 200
    assert "Option à installer" not in r.text
    assert "la clé du serveur est acceptée sans vérification" in r.text


def test_sans_paramiko_l_option_est_dite_absente(monkeypatch):
    """La vraie détection, sans remplacement : elle lit ce que le venv porte."""
    monkeypatch.setattr(remote.importlib.util, "find_spec",
                        lambda nom: None if nom == "paramiko" else object())
    assert remote.sftp_disponible() is False
