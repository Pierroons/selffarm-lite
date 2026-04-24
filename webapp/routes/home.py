"""Route d'accueil."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from webapp import __version__
from self_aid.loader import load_all, total_enveloppe

router = APIRouter()

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    # Stats pour les tuiles du dashboard
    aides = load_all()
    mn, mx = total_enveloppe(aides)

    examples_dir = Path(__file__).parent.parent.parent / "examples"
    dnja_examples_count = len(list(examples_dir.glob("hypotheses-*.yaml")))

    return templates.TemplateResponse(
        "home.html",
        {
            "request": request,
            "version": __version__,
            "stats": {
                "aides_count": len(aides),
                "aides_min": f"{mn:,.0f}".replace(",", " "),
                "aides_max": f"{mx:,.0f}".replace(",", " "),
                "dnja_examples": dnja_examples_count,
            },
        },
    )
