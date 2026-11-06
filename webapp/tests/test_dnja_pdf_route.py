"""`GET /dnja/pdf` : un rendu de près d'une seconde, sans compte. Il se fait hors de la boucle
d'événements — les autres pages répondent pendant ce temps — et un seul à la fois, sur
son propre limiteur : une rafale ne prend ni la mémoire ni le pool de threads commun."""

from __future__ import annotations

import asyncio
import threading
import time

import httpx
import pytest

from webapp.main import app
from webapp.routes import dnja as route_dnja

SCENARIO = "hypotheses-demo-publique"


@pytest.fixture
def rendu_lent(monkeypatch):
    """Un faux rendu de 0,6 s qui note combien tournent en même temps."""
    etat = {"en_cours": 0, "maximum": 0}
    verrou = threading.Lock()

    def faux_pdf(_resultat):
        with verrou:
            etat["en_cours"] += 1
            etat["maximum"] = max(etat["maximum"], etat["en_cours"])
        time.sleep(0.6)
        with verrou:
            etat["en_cours"] -= 1
        return b"%PDF-1.7 faux"

    monkeypatch.setattr(route_dnja, "pdf_bytes", faux_pdf)
    return etat


async def _get(client: httpx.AsyncClient, url: str, fins: dict, nom: str):
    r = await client.get(url)
    fins[nom] = time.monotonic()
    return r


def test_les_autres_pages_repondent_pendant_un_rendu(rendu_lent):
    async def scenario():
        fins: dict[str, float] = {}
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            pdf = asyncio.create_task(_get(c, f"/dnja/pdf?example={SCENARIO}", fins, "pdf"))
            await asyncio.sleep(0.1)
            sante = await _get(c, "/healthz", fins, "healthz")
            assert (await pdf).status_code == 200
        assert sante.status_code == 200
        return fins

    fins = asyncio.run(scenario())
    assert fins["healthz"] < fins["pdf"]


def test_les_rendus_passent_un_par_un(rendu_lent):
    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            reponses = await asyncio.gather(*[c.get(f"/dnja/pdf?example={SCENARIO}") for _ in range(3)])
        assert all(r.status_code == 200 for r in reponses)

    asyncio.run(scenario())
    assert rendu_lent["maximum"] == 1
