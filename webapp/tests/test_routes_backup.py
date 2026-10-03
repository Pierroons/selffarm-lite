"""Restauration par fichier envoyé (`POST /backup/restore`) : une archive ZIP, ou le
fichier qu'exporte le coffre d'un téléphone (sauvegarde chiffrée + sa clé). Un
fichier illisible donne une erreur claire, jamais un 500, et ne touche à rien."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal

import pytest
from cryptography.fernet import Fernet
from self_agri_book import storage
from self_agri_book.exploitation import is_onboarding_done, mark_onboarding_done, save_exploitation
from self_backup import make_backup
from self_backup.vault import get_or_create_vault_key, vault_key_id
from self_elevage.elevage import save_bande
from self_pos.devices import new_pair_token

ROUTE = "/backup/restore"


def _pc(monkeypatch, dossier, piece: str | None = None, *, profil: bool = False) -> None:
    """Pointe l'app sur la base d'un PC ; `piece` y ajoute une écriture."""
    monkeypatch.setenv("SELFFARM_COMPTA_DB", str(dossier / "compta.db"))
    storage.init_db()
    if profil:
        save_exploitation({"nom": "Ferme", "statut": "JA", "commune": "C", "saison_courante": 2026})
        mark_onboarding_done()
    if piece:
        storage.save_ecriture(
            date_operation=date(2026, 10, 3), journal="VEN", numero_piece=piece,
            libelle=piece, compte_debit="411", compte_credit="701",
            montant_ttc=Decimal(100), source_module="self_invoice", source_id=piece)


def _pieces() -> set[str]:
    return {e["numero_piece"] for e in storage.list_ecritures()}


def _fichier_du_telephone(archive: bytes, cle: bytes) -> bytes:
    """Ce qu'exporte le coffre du téléphone (mobile.js, exportBackup)."""
    return json.dumps({
        "format": "selffarm-coffre", "version": 1, "backup_name": "sauvegarde.zip.vault",
        "vault_key": cle.decode("ascii"), "token": Fernet(cle).encrypt(archive).decode("ascii"),
    }).encode("utf-8")


@pytest.fixture
def ancien_pc(tmp_path, monkeypatch) -> tuple[bytes, bytes]:
    """L'archive de l'ancien PC (profil, une écriture, une bande) et sa clé de coffre."""
    _pc(monkeypatch, tmp_path / "ancien", "F-ANCIEN", profil=True)
    save_bande({"nom": "Pondeuses", "effectif_initial": 40})
    archive, _ = make_backup(version="test")
    return archive, get_or_create_vault_key()


def _envoie(client, contenu: bytes, nom: str = "sauvegarde.zip"):
    return client.post(ROUTE, files={"archive": (nom, contenu)},
                       data={"confirm_rollback": "on"})


def test_une_archive_se_restaure_quel_que_soit_son_nom(client, ancien_pc, tmp_path, monkeypatch):
    _pc(monkeypatch, tmp_path / "pc", "F-PC")
    r = _envoie(client, ancien_pc[0], nom="sans-extension")
    assert r.status_code == 200, r.text
    assert "fusion avec les données présentes" in r.text
    assert _pieces() == {"F-ANCIEN", "F-PC"}


@pytest.mark.parametrize("contenu", [b"pas une archive", b"PK\x03\x04 tronque"])
def test_un_fichier_illisible_donne_400(client, ancien_pc, tmp_path, monkeypatch, contenu):
    _pc(monkeypatch, tmp_path / "pc", "F-PC")
    assert _envoie(client, contenu).status_code == 400
    assert _pieces() == {"F-PC"}


def test_un_pc_neuf_restaure_le_fichier_du_telephone_et_reprend_sa_cle(
        client, ancien_pc, tmp_path, monkeypatch):
    archive, cle = ancien_pc
    _pc(monkeypatch, tmp_path / "neuf")   # la première page affichée a créé la base

    r = _envoie(client, _fichier_du_telephone(archive, cle), nom="sauvegarde.sfcoffre")

    assert r.status_code == 200, r.text
    assert "base vierge" in r.text
    assert "reprise de l'ancien PC" in r.text
    assert get_or_create_vault_key() == cle
    assert is_onboarding_done()
    assert _pieces() == {"F-ANCIEN"}
    with storage._conn() as c:
        assert c.execute("SELECT COUNT(*) FROM bande").fetchone()[0] == 1


def test_un_pc_qui_a_des_donnees_garde_sa_cle(client, ancien_pc, tmp_path, monkeypatch):
    archive, cle = ancien_pc
    _pc(monkeypatch, tmp_path / "pc", "F-PC", profil=True)
    cle_du_pc = get_or_create_vault_key()

    r = _envoie(client, _fichier_du_telephone(archive, cle), nom="sauvegarde.sfcoffre")

    assert r.status_code == 200, r.text
    assert get_or_create_vault_key() == cle_du_pc != cle
    assert _pieces() == {"F-ANCIEN", "F-PC"}


@pytest.mark.parametrize("fichier", [
    pytest.param(lambda a, c: _fichier_du_telephone(a, c).replace(
        c.decode().encode(), Fernet.generate_key()), id="cle-qui-ne-dechiffre-pas"),
    pytest.param(lambda a, c: b'{"format": "autre", "version": 1}', id="pas-un-fichier-de-coffre"),
    pytest.param(lambda a, c: b'{"format": "selffarm-coffre"', id="json-tronque"),
])
def test_un_fichier_du_telephone_invalide_ne_touche_a_rien(
        client, ancien_pc, tmp_path, monkeypatch, fichier):
    archive, cle = ancien_pc
    _pc(monkeypatch, tmp_path / "neuf")
    avant = get_or_create_vault_key()

    r = _envoie(client, fichier(archive, cle), nom="sauvegarde.sfcoffre")

    assert r.status_code == 400
    assert get_or_create_vault_key() == avant
    assert _pieces() == set()


def test_le_telephone_recoit_l_empreinte_de_la_cle(client, tmp_path, monkeypatch):
    _pc(monkeypatch, tmp_path / "pc", "F-PC", profil=True)
    attendue = hashlib.sha256(get_or_create_vault_key()).hexdigest()[:16]

    appairage = client.post("/api/pos/pair", json={"token": new_pair_token()}).json()
    manifeste = client.get("/api/pos/backup/manifest").json()

    assert appairage["vault_key_id"] == manifeste["vault_key_id"] == vault_key_id() == attendue


def test_la_demo_publique_refuse_la_restauration(client, ancien_pc, monkeypatch):
    monkeypatch.setenv("SELFFARM_ENV", "demo")
    assert _envoie(client, ancien_pc[0]).status_code == 404


def test_la_restauration_poussee_par_le_reseau_n_existe_plus(client):
    assert client.post("/api/pos/backup/restore-push", content=b"x").status_code in (404, 405)
