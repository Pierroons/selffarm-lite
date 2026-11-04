"""Le dossier DNJA est du HTML que WeasyPrint rend, ressources `file://` comprises :
un texte saisi (commune, candidat, nom d'activité) ne doit pas y devenir une balise."""

from __future__ import annotations

from pathlib import Path

import yaml

from self_dnja.engine import calculer
from self_dnja.models import Hypotheses
from self_dnja.pdf import render_html

EXEMPLE = Path(__file__).parents[3] / "examples" / "hypotheses-demo-publique.yaml"
PIEGE = '<img src="file:///etc/hostname">'


def _rendu_avec(**champs) -> str:
    donnees = yaml.safe_load(EXEMPLE.read_text(encoding="utf-8"))
    donnees.update(champs)
    return render_html(calculer(Hypotheses(**donnees)))


def test_un_texte_saisi_ressort_echappe():
    donnees = yaml.safe_load(EXEMPLE.read_text(encoding="utf-8"))
    donnees["activites"][0]["nom"] = PIEGE
    html = _rendu_avec(commune=PIEGE, candidat=PIEGE, activites=donnees["activites"])

    assert PIEGE not in html
    assert "&lt;img src=&#34;file:///etc/hostname&#34;&gt;" in html


def test_le_gabarit_rend_encore_ses_propres_balises():
    html = _rendu_avec()
    assert "<table" in html
    assert "&lt;table" not in html
