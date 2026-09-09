"""
Client de la Plateforme Agréée — sens ENTRANT.

Repris du connecteur éprouvé de SelfInvoice (`integrations/superpdp/client.py`,
e2e sandbox du 25/06/2026), dont il garde l'authentification et le cache de
jeton, et auquel il ajoute ce que l'émission n'avait pas besoin de savoir :
lister les factures reçues, les paginer, et récupérer leur PDF.

Toutes les méthodes sont en LECTURE. Ce module ne dépose rien, ne modifie rien
côté plateforme : recevoir n'écrit pas.

Surface relevée en sandbox le 9 septembre 2026 — l'API n'expose aucune
spécification OpenAPI, ce client est donc écrit sur observation. Le README du
module porte le relevé complet.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Self

try:
    import httpx
except ImportError as e:  # pragma: no cover - dépend de l'installation
    raise ImportError(
        "self_pa a besoin de httpx : pip install 'selffarm-lite[pa]'"
    ) from e

log = logging.getLogger("selffarm.self_pa.client")

BASE_URL_DEFAUT = "https://api.superpdp.tech"
PREFIXE_API = "/v1.beta"

# Marge avant expiration du jeton. Il vit 1800 s ; on le renouvelle un peu avant
# pour qu'un appel lancé juste avant l'échéance n'échoue pas en vol.
MARGE_JETON_S = 30


class ErreurPlateforme(RuntimeError):
    """La plateforme a répondu une erreur, ou n'a pas répondu."""


@dataclass
class ConfigPA:
    client_id: str
    client_secret: str
    env: str = "sandbox"
    base_url: str = BASE_URL_DEFAUT

    @classmethod
    def depuis_env(cls) -> Self:
        """Lit `SUPERPDP_*`. Chaque installation porte ses propres identifiants.

        Le bac à sable et la production partagent la même URL : c'est la CLÉ qui
        détermine l'environnement. `SUPERPDP_ENV` n'est donc qu'un libellé, utile
        aux journaux et à l'affichage — s'y fier pour décider d'un comportement
        serait une erreur.
        """
        manquantes = [
            nom
            for nom in ("SUPERPDP_CLIENT_ID", "SUPERPDP_CLIENT_SECRET")
            if not os.environ.get(nom)
        ]
        if manquantes:
            raise ErreurPlateforme(
                f"Identifiants absents : {', '.join(manquantes)}. "
                "Ils se renseignent dans le .env de l'installation."
            )
        return cls(
            client_id=os.environ["SUPERPDP_CLIENT_ID"],
            client_secret=os.environ["SUPERPDP_CLIENT_SECRET"],
            env=os.environ.get("SUPERPDP_ENV", "sandbox"),
            base_url=os.environ.get("SUPERPDP_BASE_URL", BASE_URL_DEFAUT),
        )


class ClientPA:
    """Client asynchrone, jeton mis en cache.

    Usage :
        async with ClientPA.depuis_env() as pa:
            async for facture in pa.parcourir_recues(apres_id=dernier_traite):
                ...
    """

    def __init__(self, config: ConfigPA, http: httpx.AsyncClient | None = None):
        self._config = config
        self._http = http or httpx.AsyncClient(timeout=30.0)
        self._jeton: str | None = None
        self._expire_a: float = 0.0

    @classmethod
    def depuis_env(cls) -> Self:
        return cls(ConfigPA.depuis_env())

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_) -> None:
        await self._http.aclose()

    def _url(self, chemin: str) -> str:
        return f"{self._config.base_url}{PREFIXE_API}{chemin}"

    async def _obtenir_jeton(self) -> str:
        if self._jeton and time.time() < self._expire_a - MARGE_JETON_S:
            return self._jeton
        log.info("PA : demande d'un jeton (%s)", self._config.env)
        try:
            r = await self._http.post(
                f"{self._config.base_url}/oauth2/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._config.client_id,
                    "client_secret": self._config.client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            # Le message d'erreur ne doit jamais reproduire la requête : elle
            # porte le secret.
            raise ErreurPlateforme(f"Authentification refusée : {type(e).__name__}") from e
        charge = r.json()
        self._jeton = charge["access_token"]
        self._expire_a = time.time() + int(charge.get("expires_in", 1800))
        return self._jeton

    async def _get(self, chemin: str, params: dict[str, Any] | None = None) -> httpx.Response:
        jeton = await self._obtenir_jeton()
        try:
            r = await self._http.get(
                self._url(chemin),
                params=params or {},
                headers={"Authorization": f"Bearer {jeton}"},
            )
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            detail = e.response.text[:200]
            raise ErreurPlateforme(
                f"GET {chemin} → HTTP {e.response.status_code} : {detail}"
            ) from e
        except httpx.HTTPError as e:
            raise ErreurPlateforme(f"GET {chemin} : {type(e).__name__}") from e
        return r

    async def lister_factures(
        self,
        direction: str = "in",
        apres_id: int | str | None = None,
    ) -> tuple[list[dict], bool]:
        """Une page de factures, et s'il en reste après.

        `direction` est validé par la plateforme : une valeur inconnue rend un
        400 « invalid direction », pas une liste vide silencieuse.

        ⚠️ Le `count` de la réponse est le total correspondant au FILTRE, pas la
        taille de la page : avec un curseur qui épuise la liste, il vaut encore 1
        alors que `data` est vide. Boucler dessus tournerait sans fin — c'est
        `has_after` qui dit s'il faut continuer.
        """
        params: dict[str, Any] = {"direction": direction}
        if apres_id is not None:
            params["starting_after_id"] = apres_id
        charge = (await self._get("/invoices", params)).json()
        factures = charge.get("data") or []
        log.debug(
            "PA : %d facture(s) %s, has_after=%s",
            len(factures), direction, charge.get("has_after"),
        )
        return factures, bool(charge.get("has_after"))

    async def parcourir_recues(
        self, apres_id: int | str | None = None
    ) -> AsyncIterator[dict]:
        """Toutes les factures reçues depuis `apres_id`, page après page.

        `apres_id` est le dernier identifiant déjà traité : c'est lui qui rend la
        récupération incrémentale possible, et qui évite de tout relire à chaque
        appel du bouton.
        """
        curseur = apres_id
        while True:
            factures, encore = await self.lister_factures("in", curseur)
            if not factures:
                return
            for facture in factures:
                yield facture
            if not encore:
                return
            # Le curseur avance sur le dernier id vu, sans quoi la boucle
            # redemanderait indéfiniment la même page.
            curseur = factures[-1]["id"]

    async def obtenir_facture(self, facture_id: int | str) -> dict:
        """Détail d'une facture, `en_invoice` et `events[]` compris."""
        return (await self._get(f"/invoices/{facture_id}")).json()

    async def telecharger_facture(self, facture_id: int | str) -> bytes:
        """Le PDF Factur-X.

        Seule cette URL rend le fichier : l'en-tête `Accept` n'est pas honoré par
        la plateforme, et les variantes `/pdf`, `/xml`, `/file` rendent 404.
        """
        r = await self._get(f"/invoices/{facture_id}/download")
        contenu = r.content
        if not contenu.startswith(b"%PDF-"):
            raise ErreurPlateforme(
                f"Facture {facture_id} : contenu inattendu "
                f"({r.headers.get('content-type', '?')}, {len(contenu)} octets)"
            )
        return contenu

    async def lister_evenements(
        self, apres_id: int | str | None = None
    ) -> tuple[list[dict], bool]:
        """Événements de cycle de vie, paginés par curseur d'identifiant."""
        params: dict[str, Any] = {}
        if apres_id is not None:
            params["starting_after_id"] = apres_id
        charge = (await self._get("/invoice_events", params)).json()
        return charge.get("data") or [], bool(charge.get("has_after"))
