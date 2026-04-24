"""Route parcellaire IGN — intégration de la démo carto existante."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates

from webapp import __version__

router = APIRouter(prefix="/parcelles", tags=["parcelles"])

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
DEMO_CARTO = Path(__file__).parent.parent.parent / "docs" / "demo-carto-[commune].html"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("", response_class=HTMLResponse)
async def parcelles_index(request: Request):
    return templates.TemplateResponse(
        "parcelles/index.html",
        {"request": request, "version": __version__},
    )


@router.get("/carto", response_class=HTMLResponse)
async def parcelles_carto():
    """Sert la démo carto Leaflet + IGN directement (intégration iframe)."""
    if DEMO_CARTO.exists():
        return FileResponse(DEMO_CARTO, media_type="text/html")
    return HTMLResponse("<h1>Démo carto introuvable</h1>", status_code=404)
