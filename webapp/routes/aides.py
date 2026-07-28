"""Route catalogue des aides — liste filtrable + détail."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from self_aid.loader import filter_aides, load_all, total_enveloppe
from self_aid.models import CategorieAide, FiltreRecherche

from webapp import __version__

router = APIRouter(prefix="/aides", tags=["aides"])

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _fmt_num(x: float) -> str:
    return f"{x:,.0f}".replace(",", " ")


@router.get("", response_class=HTMLResponse)
async def aides_index(request: Request):
    aides = load_all()
    mn, mx = total_enveloppe(aides)
    return templates.TemplateResponse(
        "aides/list.html",
        {
            "request": request,
            "version": __version__,
            "aides": [a.model_dump(mode="json") for a in aides],
            "count_total": len(aides),
            "enveloppe_min": _fmt_num(mn),
            "enveloppe_max": _fmt_num(mx),
            "cumul_min": _fmt_num(mn),
            "cumul_max": _fmt_num(mx),
            "categories": [c.value for c in CategorieAide],
        },
    )


@router.get("/filter", response_class=HTMLResponse)
async def aides_filter(
    request: Request,
    mot_cle: str | None = None,
    categorie: str | None = None,
    statut: str | None = None,
    zone: str | None = None,
):
    """Fragment HTMX : liste filtrée."""
    all_aides = load_all()
    f = FiltreRecherche(
        mot_cle=mot_cle or None,
        categorie=CategorieAide(categorie) if categorie else None,
        statut=statut or None,
        zone=zone or None,
    )
    filtered = filter_aides(all_aides, f)
    mn, mx = total_enveloppe(filtered)
    return templates.TemplateResponse(
        "aides/_fragment.html",
        {
            "request": request,
            "aides": [a.model_dump(mode="json") for a in filtered],
            "cumul_min": _fmt_num(mn),
            "cumul_max": _fmt_num(mx),
        },
    )


@router.get("/{aide_id}", response_class=HTMLResponse)
async def aide_detail(request: Request, aide_id: str):
    aides = load_all()
    found = next((a for a in aides if a.id == aide_id), None)
    if not found:
        raise HTTPException(404, f"Aide inconnue : {aide_id}")
    return templates.TemplateResponse(
        "aides/detail.html",
        {
            "request": request,
            "version": __version__,
            "aide": found.model_dump(mode="json"),
        },
    )
