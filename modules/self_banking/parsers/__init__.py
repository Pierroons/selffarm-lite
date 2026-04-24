"""Parsers spécifiques par banque."""

from __future__ import annotations

from pathlib import Path

from self_banking.models import Releve
from self_banking.parsers.societe_generale import parse_sg_pdf


def parse_pdf(path: Path) -> Releve:
    """Dispatcher : détecte la banque et appelle le parser adapté."""
    import pdfplumber

    with pdfplumber.open(str(path)) as pdf:
        first_page_text = pdf.pages[0].extract_text() or ""

    if "particuliers.sg.fr" in first_page_text or "SOCIETE GENERALE" in first_page_text.upper():
        return parse_sg_pdf(path)

    raise NotImplementedError(
        "Banque non reconnue. Parsers supportés : SG. "
        "Marqueurs attendus dans le PDF : 'particuliers.sg.fr' ou 'SOCIETE GENERALE'."
    )
