"""Route d'accueil + endpoint stats dashboard."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from webapp import __version__
from webapp.services.dashboard_stats import get_dashboard_stats

log = logging.getLogger(__name__)

router = APIRouter()

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Dashboard principal — KPI + 4 charts + dernières écritures."""
    try:
        stats = get_dashboard_stats()
    except Exception:
        log.exception("get_dashboard_stats a échoué — fallback vide")
        stats = {
            "saison": 2026,
            "kpis": {
                "parcelles": {"count": 0, "surface_ha": 0},
                "cultures": {"count": 0, "actives": 0},
                "factures": {"count": 0, "volume": 0},
                "resultat": {"recettes": 0, "charges": 0, "solde": 0},
                "aides": {"percu": 0, "plafond": 0, "reste": 0, "count_actives": 0},
                "banking": {"imports": 0},
                "ecritures_total": 0,
            },
            "chart_revenus": {"labels": [], "recettes": [], "charges": []},
            "chart_cultures": {"labels": [], "data": []},
            "chart_aides": {"labels": [], "percu": [], "plafond": [],
                            "total_percu": 0, "total_plafond": 0, "reste": 0},
            "gauge": {"pct": 0, "nb_ecritures": 0, "target": 40},
            "dernieres_ecritures": [],
        }

    return templates.TemplateResponse(
        "home.html",
        {
            "request": request,
            "version": __version__,
            "active_page": "home",
            "stats": stats,
        },
    )


@router.get("/api/dashboard/stats")
async def api_dashboard_stats():
    """Endpoint JSON pour les stats du dashboard (réutilisable côté JS / mobile)."""
    return JSONResponse(get_dashboard_stats())
