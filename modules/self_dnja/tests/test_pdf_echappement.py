"""Le dossier DNJA est du HTML que WeasyPrint rend : un texte saisi (commune, candidat,
nom d'activité) ne doit y devenir ni une balise, ni une règle de style, et le rendu ne
va chercher aucune ressource — ni réseau, ni fichier local."""

from __future__ import annotations

import http.server
import io
import socketserver
import threading
from pathlib import Path

import pdfplumber
import pytest
import yaml

from self_dnja import pdf as module_pdf
from self_dnja.engine import calculer
from self_dnja.models import Hypotheses
from self_dnja.pdf import AucuneRessource, pdf_bytes, render_html

EXEMPLE = Path(__file__).parents[3] / "examples" / "hypotheses-demo-publique.yaml"
PIEGE = '<img src="file:///etc/hostname">'


def _donnees(**champs) -> dict:
    donnees = yaml.safe_load(EXEMPLE.read_text(encoding="utf-8"))
    donnees.update(champs)
    return donnees


def _rendu_avec(**champs) -> str:
    return render_html(calculer(Hypotheses(**_donnees(**champs))))


def test_un_texte_saisi_ressort_echappe():
    donnees = _donnees()
    donnees["activites"][0]["nom"] = PIEGE
    html = _rendu_avec(commune=PIEGE, candidat=PIEGE, activites=donnees["activites"])

    assert PIEGE not in html
    assert "&lt;img src=&#34;file:///etc/hostname&#34;&gt;" in html


def test_le_gabarit_rend_encore_ses_propres_balises():
    html = _rendu_avec()
    assert "<table" in html
    assert "&lt;table" not in html


def test_aucune_valeur_du_scenario_dans_la_feuille_de_style():
    html = _rendu_avec(candidat="CANDIDAT-TEMOIN")
    style = html.split("<style>", 1)[1].split("</style>", 1)[0]
    assert "CANDIDAT-TEMOIN" not in style
    assert "CANDIDAT-TEMOIN" in html


@pytest.fixture
def temoin():
    """Un serveur HTTP local qui note chaque requête reçue."""
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


@pytest.mark.parametrize("fin_de_chaine", ["\n", "\r", "\f"])
def test_un_retour_a_la_ligne_dans_le_candidat_ne_devient_pas_du_css(temoin, fin_de_chaine):
    """La charge des deux relectures : fermer la chaîne, puis une feuille de style."""
    port, recues = temoin
    charge = (f"Jean{fin_de_chaine};}} }} @page {{ size: 100mm 100mm }} "
              f"body {{ background: url(http://127.0.0.1:{port}/balise) }} "
              f"@page {{ @top-right {{ content: x")
    contenu = pdf_bytes(calculer(Hypotheses(**_donnees(candidat=charge))))

    with pdfplumber.open(io.BytesIO(contenu)) as document:
        pages = len(document.pages)
        largeur, hauteur = document.pages[0].width, document.pages[0].height
    assert recues == []
    assert (round(largeur), round(hauteur)) == (595, 842)
    with pdfplumber.open(io.BytesIO(pdf_bytes(calculer(Hypotheses(**_donnees()))))) as temoin_pdf:
        assert pages == len(temoin_pdf.pages)


def test_le_candidat_s_affiche_dans_la_marge():
    contenu = pdf_bytes(calculer(Hypotheses(**_donnees(candidat="Marie TÉMOIN-MARGE"))))
    with pdfplumber.open(io.BytesIO(contenu)) as document:
        page = document.pages[0]
        haut = page.crop((page.width / 2, 0, page.width, 60)).extract_text() or ""
    assert "TÉMOIN-MARGE" in haut


@pytest.mark.parametrize("url", ["http://127.0.0.1:9/x.png", "file:///etc/hostname",
                                 "data:image/png;base64,iVBORw0KGgo="])
def test_le_filtre_refuse_toute_ressource(url):
    with pytest.raises(ValueError):
        AucuneRessource().fetch(url)


def test_le_rendu_passe_par_le_filtre(temoin, monkeypatch):
    """Même si un jour une valeur atteint le HTML sous forme de ressource."""
    port, recues = temoin
    monkeypatch.setattr(module_pdf, "render_html",
                        lambda _: f'<p>x</p><img src="http://127.0.0.1:{port}/image.png">')
    pdf_bytes(calculer(Hypotheses(**_donnees())))
    assert recues == []


def test_le_dossier_ne_demande_aucune_ressource(monkeypatch):
    demandes: list[str] = []
    monkeypatch.setattr(module_pdf.AucuneRessource, "fetch",
                        lambda self, url, headers=None: demandes.append(url))
    pdf_bytes(calculer(Hypotheses(**_donnees())))
    assert demandes == []
