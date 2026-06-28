"""
Routes du système de modules :
- GET  /parametres/vue/{mode}              → bascule view_mode (mine|full)
- GET  /parametres/modules                  → écran de gestion (toggles on/off)
- POST /parametres/modules/{id}/activer     → active un module
- POST /parametres/modules/{id}/desactiver  → désactive (UI uniquement, données conservées)
- GET  /m/{module_id}/bientot               → page placeholder d'un module à venir

⚠️ Désactiver = masquer l'interface. Les données ne sont JAMAIS supprimées.
Les modules core (compta, backup, parcelles, modules) ne sont pas désactivables.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from webapp import __version__
from webapp import modules_catalog as cat
from webapp import modules_state as state

router = APIRouter()

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/parametres/vue/{mode}")
async def set_view(mode: str, request: Request):
    if mode in cat.VALID_VIEW_MODES:
        state.set_view_mode(mode)
    back = request.headers.get("referer") or "/"
    return RedirectResponse(url=back, status_code=303)


@router.get("/parametres/modules", response_class=HTMLResponse)
async def modules_index(request: Request):
    return templates.TemplateResponse(
        "modules/index.html", {"request": request, "version": __version__}
    )


@router.post("/parametres/modules/{module_id}/activer")
async def module_activer(module_id: str):
    state.toggle_module(module_id, True)
    return RedirectResponse(url="/parametres/modules", status_code=303)


@router.post("/parametres/modules/{module_id}/desactiver")
async def module_desactiver(module_id: str):
    state.toggle_module(module_id, False)  # core/soon ignorés par toggle_module
    return RedirectResponse(url="/parametres/modules", status_code=303)


@router.get("/m/{module_id}/bientot", response_class=HTMLResponse)
async def module_soon(module_id: str, request: Request):
    module = cat.module_by_id(module_id)
    return templates.TemplateResponse(
        "modules/bientot.html",
        {"request": request, "module": module, "version": __version__},
    )
