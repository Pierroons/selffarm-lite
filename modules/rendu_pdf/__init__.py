"""Rendu PDF par WeasyPrint, sans aucune ressource externe.

Les gabarits de SelfFarm (dossier DNJA, facture) ne chargent rien : ni image, ni feuille,
ni police par URL. WeasyPrint ne reçoit donc aucune ressource — ni réseau, ni fichier
local, ni `data:` —, et une valeur saisie qui en demanderait une échoue au lieu de faire
lire un fichier du serveur ou de lui faire appeler une adresse.
"""

from __future__ import annotations

import logging

from weasyprint import HTML, URLFetcher

log = logging.getLogger("rendu_pdf")


class AucuneRessource(URLFetcher):
    def fetch(self, url, headers=None):
        log.warning("Ressource refusée au rendu PDF : %.120s", url)
        raise ValueError("ressource externe refusée")


def html_vers_pdf(html: str, base_url: str | None = None) -> bytes:
    """Le PDF du HTML donné, en mémoire, sans charger aucune ressource."""
    return HTML(string=html, base_url=base_url, url_fetcher=AucuneRessource()).write_pdf()
