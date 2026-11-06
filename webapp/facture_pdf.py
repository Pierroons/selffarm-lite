"""Le PDF d'une facture, depuis `invoice/facture.html.j2` : un seul rendu pour la création,
la démonstration et la facture tirée du journal.

Le gabarit finit en `.j2` : l'échappement par défaut de starlette (`select_autoescape`)
n'y échapperait rien. Il a donc son environnement, échappé, et son rendu ne charge
aucune ressource (`rendu_pdf`).
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from rendu_pdf import html_vers_pdf

GABARITS = Path(__file__).parent / "templates"
_environnement = Environment(loader=FileSystemLoader(str(GABARITS)), autoescape=True)


def facture_html(data: dict) -> str:
    return _environnement.get_template("invoice/facture.html.j2").render(**data)


def facture_pdf(data: dict) -> bytes:
    return html_vers_pdf(facture_html(data))
