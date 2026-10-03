"""Restauration par fichier envoyé (`POST /backup/restore`) : le format se lit au
contenu, et un fichier illisible donne une erreur claire, jamais un 500."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from self_agri_book import storage
from self_backup import make_backup

ROUTE = "/backup/restore"


@pytest.fixture
def archive(tmp_path, monkeypatch) -> bytes:
    """Une archive de l'« ancien PC », puis l'app pointée sur une base avec données."""
    for nom, piece in (("ancien", "F-ANCIEN"), ("pc", "F-PC")):
        monkeypatch.setenv("SELFFARM_COMPTA_DB", str(tmp_path / nom / "compta.db"))
        storage.save_ecriture(
            date_operation=date(2026, 10, 3), journal="VEN", numero_piece=piece,
            libelle=piece, compte_debit="411", compte_credit="701",
            montant_ttc=Decimal(100), source_module="self_invoice", source_id=piece)
        if nom == "ancien":
            zip_bytes, _ = make_backup(version="test")
    return zip_bytes


def _envoie(client, contenu: bytes, nom: str = "sauvegarde.zip"):
    return client.post(ROUTE, files={"archive": (nom, contenu)},
                       data={"confirm_rollback": "on"})


def test_une_archive_se_restaure_quel_que_soit_son_nom(client, archive):
    r = _envoie(client, archive, nom="sans-extension")
    assert r.status_code == 200, r.text
    assert "fusion avec les données présentes" in r.text
    assert {e["numero_piece"] for e in storage.list_ecritures()} == {"F-ANCIEN", "F-PC"}


@pytest.mark.parametrize("contenu", [b"pas une archive", b"PK\x03\x04 tronque"])
def test_un_fichier_illisible_donne_400(client, archive, contenu):
    r = _envoie(client, contenu)
    assert r.status_code == 400
    assert [e["numero_piece"] for e in storage.list_ecritures()] == ["F-PC"]
