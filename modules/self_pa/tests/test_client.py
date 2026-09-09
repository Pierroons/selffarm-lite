"""Tests du client de réception — httpx mocké, aucun appel réseau.

Sur le patron de `selfinvoice/tests/unit/test_superpdp_client.py`. Les réponses
reproduisent celles relevées en sandbox le 9 septembre 2026.
"""

from __future__ import annotations

import asyncio
import functools
import json

import httpx
import pytest

from self_pa.client import ClientPA, ConfigPA, ErreurPlateforme


def asynchrone(fn):
    """Exécute un test asynchrone sans greffon pytest.

    SelfFarm-Lite ne porte aucun autre test asynchrone : ajouter
    `pytest-asyncio` aux dépendances et à la CI pour ce seul module coûterait
    plus que ces quelques lignes.
    """

    @functools.wraps(fn)
    def enveloppe(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))

    return enveloppe

CONFIG = ConfigPA(client_id="id-de-test", client_secret="secret-de-test")


def transport(gestionnaire) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(gestionnaire))


def reponse_jeton() -> httpx.Response:
    return httpx.Response(
        200, json={"access_token": "jeton-de-test", "token_type": "bearer",
                   "expires_in": 1800}
    )


def facture(fid: int, direction: str = "in") -> dict:
    return {"id": fid, "company_id": 1, "direction": direction,
            "created_at": "2026-09-03T10:00:00Z"}


# ---------------- authentification ----------------

@asynchrone
async def test_le_jeton_est_mis_en_cache():
    """Un jeton par session, pas un par appel : la plateforme le donne pour
    1800 s."""
    appels = {"token": 0, "get": 0}

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        if requete.url.path == "/oauth2/token":
            appels["token"] += 1
            return reponse_jeton()
        appels["get"] += 1
        return httpx.Response(200, json={"data": [facture(1)], "count": 1,
                                         "has_after": False})

    async with ClientPA(CONFIG, transport(gestionnaire)) as pa:
        await pa.lister_factures()
        await pa.lister_factures()
        await pa.lister_factures()

    assert appels["token"] == 1
    assert appels["get"] == 3


@asynchrone
async def test_echec_dauthentification_ne_reproduit_pas_le_secret():
    """Le message d'erreur remonte dans les journaux : il ne doit jamais porter
    la requête, qui contient le client_secret."""
    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "invalid client"})

    async with ClientPA(CONFIG, transport(gestionnaire)) as pa:
        with pytest.raises(ErreurPlateforme) as info:
            await pa.lister_factures()

    assert "secret-de-test" not in str(info.value)


def test_config_absente_le_dit_clairement(monkeypatch):
    monkeypatch.delenv("SUPERPDP_CLIENT_ID", raising=False)
    monkeypatch.delenv("SUPERPDP_CLIENT_SECRET", raising=False)

    with pytest.raises(ErreurPlateforme, match="SUPERPDP_CLIENT_ID"):
        ConfigPA.depuis_env()


# ---------------- lister et paginer ----------------

@asynchrone
async def test_lister_filtre_sur_les_recues():
    vues = {}

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        if requete.url.path == "/oauth2/token":
            return reponse_jeton()
        vues["direction"] = requete.url.params.get("direction")
        return httpx.Response(200, json={"data": [facture(1)], "count": 1,
                                         "has_after": False})

    async with ClientPA(CONFIG, transport(gestionnaire)) as pa:
        factures, encore = await pa.lister_factures()

    assert vues["direction"] == "in"
    assert len(factures) == 1
    assert encore is False


@asynchrone
async def test_parcourir_suit_le_curseur_sur_plusieurs_pages():
    pages = {
        None: ([facture(10), facture(11)], True),
        "11": ([facture(12)], False),
    }
    demandes: list[str | None] = []

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        if requete.url.path == "/oauth2/token":
            return reponse_jeton()
        curseur = requete.url.params.get("starting_after_id")
        demandes.append(curseur)
        data, encore = pages[curseur]
        return httpx.Response(200, json={"data": data, "count": 3,
                                         "has_after": encore})

    async with ClientPA(CONFIG, transport(gestionnaire)) as pa:
        vues = [f["id"] async for f in pa.parcourir_recues()]

    assert vues == [10, 11, 12]
    assert demandes == [None, "11"]


@asynchrone
async def test_parcourir_sarrete_sur_has_after_meme_si_count_ment():
    """Le piège relevé en sandbox : `count` reste le total du filtre même quand
    la page est vide. Boucler dessus tournerait sans fin."""
    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        if requete.url.path == "/oauth2/token":
            return reponse_jeton()
        # count=1 alors que data est vide — exactement ce que rend l'API quand
        # le curseur a épuisé la liste.
        return httpx.Response(200, json={"data": [], "count": 1,
                                         "has_after": False})

    async with ClientPA(CONFIG, transport(gestionnaire)) as pa:
        vues = [f async for f in pa.parcourir_recues(apres_id=999)]

    assert vues == []


@asynchrone
async def test_parcourir_reprend_apres_le_dernier_traite():
    demandes: list[str | None] = []

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        if requete.url.path == "/oauth2/token":
            return reponse_jeton()
        demandes.append(requete.url.params.get("starting_after_id"))
        return httpx.Response(200, json={"data": [], "count": 0,
                                         "has_after": False})

    async with ClientPA(CONFIG, transport(gestionnaire)) as pa:
        [f async for f in pa.parcourir_recues(apres_id=84385)]

    assert demandes == ["84385"]


# ---------------- détail et téléchargement ----------------

@asynchrone
async def test_obtenir_facture_rend_len_invoice():
    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        if requete.url.path == "/oauth2/token":
            return reponse_jeton()
        return httpx.Response(200, json={"id": 84385, "direction": "in",
                                         "en_invoice": {"number": "FA-1"},
                                         "events": []})

    async with ClientPA(CONFIG, transport(gestionnaire)) as pa:
        detail = await pa.obtenir_facture(84385)

    assert detail["en_invoice"]["number"] == "FA-1"


@asynchrone
async def test_telecharger_rend_le_pdf():
    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        if requete.url.path == "/oauth2/token":
            return reponse_jeton()
        assert requete.url.path.endswith("/download")
        return httpx.Response(200, content=b"%PDF-1.7\n...",
                              headers={"Content-Type": "application/pdf"})

    async with ClientPA(CONFIG, transport(gestionnaire)) as pa:
        pdf = await pa.telecharger_facture(84385)

    assert pdf.startswith(b"%PDF-")


@asynchrone
async def test_telecharger_refuse_un_contenu_qui_nest_pas_un_pdf():
    """Si la plateforme rendait du JSON d'erreur en 200, l'enregistrer comme
    justificatif produirait un fichier illisible attaché à une écriture — une
    pièce comptable manquante qui se croit présente."""
    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        if requete.url.path == "/oauth2/token":
            return reponse_jeton()
        return httpx.Response(200, json={"message": "not ready"},
                              headers={"Content-Type": "application/json"})

    async with ClientPA(CONFIG, transport(gestionnaire)) as pa:
        with pytest.raises(ErreurPlateforme, match="contenu inattendu"):
            await pa.telecharger_facture(84385)


@asynchrone
async def test_erreur_http_est_traduite():
    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        if requete.url.path == "/oauth2/token":
            return reponse_jeton()
        return httpx.Response(400, text=json.dumps({"message": "invalid direction"}))

    async with ClientPA(CONFIG, transport(gestionnaire)) as pa:
        with pytest.raises(ErreurPlateforme, match="invalid direction"):
            await pa.lister_factures(direction="nimportequoi")
