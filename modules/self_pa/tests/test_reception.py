"""Tests du geste complet : récupérer, puis comptabiliser.

Le client est mocké (httpx MockTransport), la base est temporaire. Aucun appel
réseau, aucune écriture dans une base réelle.
"""

from __future__ import annotations

import asyncio
import functools
from decimal import Decimal

import httpx
import pytest

from self_pa import reception, storage
from self_pa.client import ClientPA, ConfigPA
from self_pa.tests.test_en_invoice import en_invoice

CONFIG = ConfigPA(client_id="id-de-test", client_secret="secret-de-test")


def asynchrone(fn):
    @functools.wraps(fn)
    def enveloppe(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))

    return enveloppe


@pytest.fixture
def base_isolee(tmp_path, monkeypatch):
    monkeypatch.setenv("SELFFARM_COMPTA_DB", str(tmp_path / "test_compta.db"))
    yield tmp_path


def plateforme(factures: dict[int, dict], pdf: bytes | None = b"%PDF-1.7\nfaux"):
    """Un faux Super PDP : liste, détail, téléchargement."""

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        chemin = requete.url.path
        if chemin == "/oauth2/token":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 1800})
        if chemin.endswith("/download"):
            if pdf is None:
                return httpx.Response(503, json={"message": "indisponible"})
            return httpx.Response(200, content=pdf,
                                  headers={"Content-Type": "application/pdf"})
        if chemin == "/v1.beta/invoices":
            apres = requete.url.params.get("starting_after_id")
            ids = sorted(factures)
            if apres is not None:
                ids = [i for i in ids if i > int(apres)]
            return httpx.Response(200, json={
                "data": [{"id": i, "direction": "in"} for i in ids],
                "count": len(ids), "has_after": False,
            })
        fid = int(chemin.rsplit("/", 1)[-1])
        return httpx.Response(200, json={"id": fid, "direction": "in",
                                         "en_invoice": factures[fid], "events": []})

    return ClientPA(CONFIG, httpx.AsyncClient(transport=httpx.MockTransport(gestionnaire)))


# ---------------- récupération ----------------

@asynchrone
async def test_recuperer_enregistre_sans_rien_comptabiliser(base_isolee):
    """Le point central : le bouton du matin ne crée aucune écriture."""
    from self_agri_book.storage import _conn

    async with plateforme({1: en_invoice()}) as pa:
        rapport = await reception.recuperer_nouvelles(pa)

    assert rapport.nouvelles == ["552100554:FA-2026-0142"]
    assert storage.obtenir("552100554:FA-2026-0142")["statut"] == "proposee"

    with _conn() as c:
        n = c.execute("SELECT count(*) AS n FROM ecritures_comptables").fetchone()["n"]
    assert n == 0


@asynchrone
async def test_recuperer_deux_fois_ne_duplique_pas(base_isolee):
    async with plateforme({1: en_invoice()}) as pa:
        await reception.recuperer_nouvelles(pa)
    async with plateforme({1: en_invoice()}) as pa:
        rapport = await reception.recuperer_nouvelles(pa)

    # Le curseur a avancé : la facture n'est même plus proposée par la plateforme.
    assert rapport.nouvelles == []
    assert len(storage.lister()) == 1


@asynchrone
async def test_le_hash_du_pdf_est_conserve(base_isolee):
    """C'est lui qui rattachera l'écriture à son justificatif."""
    async with plateforme({1: en_invoice()}, pdf=b"%PDF-1.7\ncontenu") as pa:
        await reception.recuperer_nouvelles(pa)

    import hashlib
    attendu = hashlib.sha256(b"%PDF-1.7\ncontenu").hexdigest()
    assert storage.obtenir("552100554:FA-2026-0142")["hash_fichier"] == attendu


@asynchrone
async def test_pdf_indisponible_ne_perd_pas_la_facture(base_isolee):
    """Les données sont déjà lues : perdre la facture parce que son PDF ne
    descend pas serait perdre plus que le justificatif."""
    async with plateforme({1: en_invoice()}, pdf=None) as pa:
        rapport = await reception.recuperer_nouvelles(pa)

    assert rapport.nouvelles == ["552100554:FA-2026-0142"]
    assert storage.obtenir("552100554:FA-2026-0142")["hash_fichier"] is None


@asynchrone
async def test_une_facture_illisible_narrete_pas_les_autres(base_isolee):
    """Un fournisseur qui envoie n'importe quoi ne doit pas priver l'exploitant
    des autres factures du jour."""
    factures = {
        1: en_invoice(numero="FA-001"),
        2: {"pas": "une facture"},
        3: en_invoice(numero="FA-003"),
    }
    async with plateforme(factures) as pa:
        rapport = await reception.recuperer_nouvelles(pa)

    assert len(rapport.nouvelles) == 2
    assert len(rapport.echecs) == 1
    assert rapport.echecs[0][0] == "2"


@asynchrone
async def test_facture_incoherente_est_signalee_mais_conservee(base_isolee):
    charge = en_invoice()
    charge["totals"]["total_with_vat"] = "9999.00"  # HT + TVA ≠ TTC

    async with plateforme({1: charge}) as pa:
        rapport = await reception.recuperer_nouvelles(pa)

    cle = "552100554:FA-2026-0142"
    assert cle in rapport.bloquees
    assert storage.obtenir(cle)["statut"] == "bloquee"


# ---------------- validation ----------------

@asynchrone
async def test_valider_cree_lecriture(base_isolee):
    from self_agri_book.storage import _conn

    async with plateforme({1: en_invoice()}) as pa:
        await reception.recuperer_nouvelles(pa)

    ecriture_id = reception.valider("552100554:FA-2026-0142", compte_charge="6063")

    with _conn() as c:
        ligne = c.execute(
            "SELECT * FROM ecritures_comptables WHERE id = ?", (ecriture_id,)
        ).fetchone()

    assert ligne["journal"] == "ACH"
    assert ligne["compte_debit"] == "6063"
    assert ligne["compte_credit"] == "401"
    assert Decimal(ligne["montant_ttc"]) == Decimal("1200.00")
    assert Decimal(ligne["montant_tva"]) == Decimal("200.00")
    assert ligne["source_module"] == "self_pa"
    assert ligne["source_id"] == "552100554:FA-2026-0142#6063"
    assert ligne["hash_pdf"] is not None


@asynchrone
async def test_valider_marque_la_facture(base_isolee):
    async with plateforme({1: en_invoice()}) as pa:
        await reception.recuperer_nouvelles(pa)
    ecriture_id = reception.valider("552100554:FA-2026-0142", compte_charge="6063")

    stockee = storage.obtenir("552100554:FA-2026-0142")
    assert stockee["statut"] == "validee"
    assert stockee["ecriture_id"] == ecriture_id


@asynchrone
async def test_double_validation_refusee(base_isolee):
    """Le garde-fou qui compte : deux clics ne font pas deux dettes."""
    from self_agri_book.storage import _conn

    async with plateforme({1: en_invoice()}) as pa:
        await reception.recuperer_nouvelles(pa)
    reception.valider("552100554:FA-2026-0142", compte_charge="6063")

    with pytest.raises(ValueError, match="déjà comptabilisée"):
        reception.valider("552100554:FA-2026-0142", compte_charge="6063")

    with _conn() as c:
        n = c.execute("SELECT count(*) AS n FROM ecritures_comptables").fetchone()["n"]
    assert n == 1


@asynchrone
async def test_valider_une_facture_bloquee_est_refuse(base_isolee):
    charge = en_invoice()
    charge["totals"]["total_with_vat"] = "9999.00"
    async with plateforme({1: charge}) as pa:
        await reception.recuperer_nouvelles(pa)

    with pytest.raises(ValueError, match="HT \\+ TVA ≠ TTC"):
        reception.valider("552100554:FA-2026-0142", compte_charge="6063")


def test_valider_une_facture_inconnue_est_refuse(base_isolee):
    with pytest.raises(ValueError, match="inconnue"):
        reception.valider("000000000:INEXISTANTE", compte_charge="6063")


@asynchrone
async def test_le_compte_de_charge_choisi_est_celui_utilise(base_isolee):
    """Rien n'est deviné : l'humain choisit, et c'est son choix qui part en
    comptabilité."""
    async with plateforme({1: en_invoice()}) as pa:
        await reception.recuperer_nouvelles(pa)

    from self_agri_book.storage import _conn
    ecriture_id = reception.valider("552100554:FA-2026-0142", compte_charge="6132")
    with _conn() as c:
        ligne = c.execute(
            "SELECT compte_debit, source_id FROM ecritures_comptables WHERE id = ?",
            (ecriture_id,),
        ).fetchone()

    assert ligne["compte_debit"] == "6132"
    assert ligne["source_id"].endswith("#6132")
