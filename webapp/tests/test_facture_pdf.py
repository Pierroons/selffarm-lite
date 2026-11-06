"""La facture est du HTML que WeasyPrint rend. `POST /invoice/creer` n'a ni compte ni garde
de démo : un champ saisi (vendeur, client, ligne) ne doit y devenir ni une balise, ni une
pièce jointe tirée d'un fichier du serveur, ni une requête vers une autre adresse."""

from __future__ import annotations

import http.server
import re
import socketserver
import threading
import zlib
from pathlib import Path

import pytest
from rendu_pdf import html_vers_pdf

from webapp.facture_pdf import facture_html

RACINE = Path(__file__).resolve().parents[2]


def _flux_du_pdf(pdf: bytes) -> bytes:
    morceaux = []
    for flux in re.findall(rb"stream\r?\n(.*?)\r?\nendstream", pdf, re.DOTALL):
        try:
            morceaux.append(zlib.decompress(flux))
        except zlib.error:
            morceaux.append(flux)
    return b"".join(morceaux) + pdf


def test_la_creation_ne_joint_aucun_fichier_du_serveur(client, tmp_path):
    """L'attaque de la relecture du 06/11, rejouée telle quelle."""
    canari = tmp_path / "canari.txt"
    canari.write_text("TEMOIN-SERVEUR-7f3a")
    r = client.post("/invoice/creer", data={
        "vendeur_nom": f'Ferme <b>gras</b> <link rel="attachment" href="file://{canari}">',
        "client_nom": "Client", "regime": "reel",
        "ligne_0_nom": "Tisane", "ligne_0_qte": "1", "ligne_0_pu_ht": "10", "ligne_0_tva_pct": "5.5",
    })
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert b"/EmbeddedFile" not in r.content
    assert b"TEMOIN-SERVEUR-7f3a" not in _flux_du_pdf(r.content)


def test_le_gabarit_de_facture_echappe_les_champs():
    from webapp.routes.invoice import _generer_facture_data
    data = _generer_facture_data("reel")
    data["vendeur"]["nom"] = data["vendeur"]["nom_commercial"] = "<b>gras</b>"
    data["client"]["nom"] = '<img src="file:///etc/hostname">'
    html = facture_html(data)
    assert "<b>gras</b>" not in html
    assert "&lt;b&gt;gras&lt;/b&gt;" in html
    assert '<img src="file:///etc/hostname">' not in html


@pytest.fixture
def temoin():
    recues: list[str] = []

    class Gestion(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            recues.append(self.path)
            self.send_response(404)
            self.end_headers()

        def log_message(self, *_):
            pass

    serveur = socketserver.TCPServer(("127.0.0.1", 0), Gestion)
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    yield serveur.server_address[1], recues
    serveur.shutdown()


def test_le_rendu_commun_ne_charge_aucune_ressource(temoin, tmp_path):
    port, recues = temoin
    canari = tmp_path / "canari.txt"
    canari.write_text("TEMOIN-LOCAL-91c2")
    pdf = html_vers_pdf(f'<p>x</p><img src="http://127.0.0.1:{port}/image.png">'
                        f'<link rel="attachment" href="file://{canari}">')
    assert recues == []
    assert b"/EmbeddedFile" not in pdf
    assert b"TEMOIN-LOCAL-91c2" not in _flux_du_pdf(pdf)


def test_aucun_rendu_weasyprint_hors_du_rendu_commun():
    """La règle écrite, vérifiée appliquée : tout PDF passe par `rendu_pdf`."""
    fautifs = [
        str(p.relative_to(RACINE))
        for dossier in ("webapp", "modules")
        for p in (RACINE / dossier).rglob("*.py")
        if "/tests/" not in str(p) and p.parent.name != "rendu_pdf"
        and re.search(r"\bHTML\s*\(\s*string\s*=", p.read_text(encoding="utf-8"))
    ]
    assert fautifs == []
