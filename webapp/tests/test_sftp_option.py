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


# --- Chaque lecteur de l'option la nomme ---------------------------------------

@pytest.fixture
def config(tmp_path, monkeypatch):
    chemin = tmp_path / "backup_sftp.json"
    monkeypatch.setattr(remote, "_sftp_config_path", lambda: chemin)
    return chemin


def test_la_connexion_elle_meme_nomme_l_option(sans_option):
    """La réplication du grand livre passe par `_connect`, comme le test et la sauvegarde."""
    with pytest.raises(RuntimeError, match="option à installer"):
        remote._connect({"host": "nas", "username": "u"})


def test_la_config_garde_les_champs_mais_n_active_pas_sans_l_option(client, sans_option, config):
    r = client.post("/backup/distant/config", data={
        "host": "nas.local", "port": "22", "username": "sauvegarde", "key_path": "~/.ssh/id",
        "remote_dir": "/sauvegardes", "gpg_recipient": "x", "retention": "30", "enabled": "on",
    }, follow_redirects=False)
    assert r.status_code == 303
    cfg = remote.load_sftp_config()
    assert cfg["host"] == "nas.local"
    assert cfg["enabled"] is False
    assert cfg["last_test"]["message"] == remote.OPTION_ABSENTE


def test_le_bandeau_de_sante_nomme_l_option(sans_option, config):
    from self_backup import backup_health
    remote.save_sftp_config({"enabled": True, "host": "nas", "username": "u"})
    messages = backup_health()["messages"]
    assert any(remote.OPTION_ABSENTE in m for m in messages), messages


def test_la_notification_du_cron_nomme_l_option(sans_option, config, monkeypatch):
    import logging

    from self_backup import autobackup
    remote.save_sftp_config({"enabled": True, "host": "nas", "username": "u",
                             "remote_dir": "/sauvegardes"})
    notes: list[str] = []
    monkeypatch.setattr(autobackup, "_notify", lambda _log, message: notes.append(message))
    assert autobackup._backup_sftp(logging.getLogger("test"), "test") == 2
    assert notes and remote.OPTION_ABSENTE in notes[0]
    assert "injoignable" not in notes[0]


def test_la_config_ne_se_lit_jamais_a_moitie_ecrite(config):
    """Un écrivain et un lecteur en même temps : une lecture vide effaçait la config
    au premier enregistrement qui suivait."""
    import threading
    remote.save_sftp_config({"enabled": True, "host": "nas"})
    vides, fini = [], threading.Event()

    def lire():
        while not fini.is_set():
            if remote.load_sftp_config() == {}:
                vides.append(1)

    lecteur = threading.Thread(target=lire)
    lecteur.start()
    for i in range(400):
        remote.save_sftp_config({"enabled": True, "host": "nas", "tour": i, "remplissage": "x" * 4000})
    fini.set()
    lecteur.join()
    assert vides == []
