"""
Route Production — Parcelles + Plan de culture.

Inclut :
- GET  /parcelles                   → liste parcelles + plan culture saison courante
- POST /parcelles/new               → créer une parcelle
- POST /parcelles/{id}/delete       → supprimer une parcelle (+ cultures cascade)
- POST /parcelles/{id}/culture/new  → ajouter une culture sur une parcelle
- POST /parcelles/culture/{id}/delete → supprimer un plan de culture
- GET  /parcelles/carto             → vue carto IGN dans le layout SelfFarm (iframe embed)
- GET  /parcelles/carto/embed       → HTML Leaflet standalone (servi dans l'iframe)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from self_culture.cultures import (
    delete_parcelle,
    delete_plan_culture,
    get_varietes_for_datalist,
    list_parcelles,
    list_plan_culture,
    rename_parcelle,
    save_parcelle,
    save_plan_culture,
    stats_parcelles_saison,
)
from self_agri_book.exploitation import get_exploitation
from webapp import __version__

log = logging.getLogger(__name__)

router = APIRouter(prefix="/parcelles", tags=["parcelles"])

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
DEMO_CARTO = Path(__file__).parent.parent.parent / "docs" / "demo-carto.html"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _current_saison() -> int:
    """Saison courante depuis le profil exploitation, sinon année courante."""
    exp = get_exploitation()
    if exp and exp.get("saison_courante"):
        return int(exp["saison_courante"])
    from datetime import date
    return date.today().year


@router.get("", response_class=HTMLResponse)
async def parcelles_index(request: Request):
    """Page principale Production : liste parcelles + plan culture saison."""
    saison = _current_saison()
    return templates.TemplateResponse(
        "parcelles/index.html",
        {
            "request": request,
            "version": __version__,
            "parcelles": list_parcelles(),
            "plans": list_plan_culture(saison=saison),
            "catalog": get_varietes_for_datalist(),
            "stats": stats_parcelles_saison(saison),
            "saison": saison,
        },
    )


@router.get("/carto", response_class=HTMLResponse)
async def parcelles_carto(request: Request):
    """Page Carte parcellaire dans le layout SelfFarm (iframe sur /embed)."""
    return templates.TemplateResponse(
        "parcelles/carto.html",
        {"request": request, "version": __version__},
    )


@router.get("/carto/embed", response_class=HTMLResponse)
async def parcelles_carto_embed():
    """Sert le HTML Leaflet + IGN brut (chargé en iframe par /carto)."""
    if DEMO_CARTO.exists():
        return FileResponse(DEMO_CARTO, media_type="text/html")
    return HTMLResponse("<h1>Démo carto introuvable</h1>", status_code=404)


# ============ POST : ajouter parcelle ============

@router.post("/new")
async def parcelle_new(
    request: Request,
    nom: str = Form(...),
    commune: str = Form(...),
    code_postal: str = Form(""),
    surface_ha: float = Form(...),
    statut: str = Form("conventionnel"),
    ref_cadastrale: str = Form(""),
    notes: str = Form(""),
):
    """Crée une nouvelle parcelle."""
    try:
        save_parcelle({
            "nom": nom.strip(),
            "commune": commune.strip(),
            "code_postal": code_postal.strip() or None,
            "surface_ha": float(surface_ha),
            "statut": statut.strip(),
            "ref_cadastrale": ref_cadastrale.strip() or None,
            "notes": notes.strip() or None,
        })
    except ValueError as e:
        log.warning("Erreur création parcelle : %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    return RedirectResponse(url="/parcelles", status_code=303)


@router.post("/{parcelle_id}/rename")
async def parcelle_rename(parcelle_id: int, nom: str = Form(...)):
    """Renomme une parcelle (édition inline depuis le tableau)."""
    try:
        result = rename_parcelle(parcelle_id, nom)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if result is None:
        raise HTTPException(status_code=404, detail="Parcelle introuvable")
    return {"ok": True, "id": parcelle_id, "nom": result["nom"]}


@router.post("/{parcelle_id}/delete")
async def parcelle_delete(parcelle_id: int):
    """Supprime une parcelle (cascade plan_culture)."""
    delete_parcelle(parcelle_id)
    return RedirectResponse(url="/parcelles", status_code=303)


# ============ POST : ajouter une culture sur une parcelle ============

@router.post("/{parcelle_id}/culture/new")
async def culture_new(
    request: Request,
    parcelle_id: int,
    culture: str = Form(...),
    variete: str = Form(""),
    surface_ha: Optional[float] = Form(None),
    date_semis_prev: str = Form(""),
    date_recolte_prev: str = Form(""),
    rendement_kg_attendu: Optional[float] = Form(None),
    mode_production: str = Form("ab"),
    notes: str = Form(""),
):
    """Crée un plan de culture sur la parcelle indiquée."""
    saison = _current_saison()
    try:
        save_plan_culture({
            "parcelle_id": parcelle_id,
            "saison": saison,
            "culture": culture.strip(),
            "culture_label": culture.strip(),  # libellé = saisie user (datalist value)
            "variete": variete.strip() or None,
            "surface_ha": float(surface_ha) if surface_ha else None,
            "date_semis_prev": date_semis_prev.strip() or None,
            "date_recolte_prev": date_recolte_prev.strip() or None,
            "rendement_kg_attendu": float(rendement_kg_attendu) if rendement_kg_attendu else None,
            "mode_production": mode_production.strip(),
            "statut": "prevu",
            "notes": notes.strip() or None,
        })
    except ValueError as e:
        log.warning("Erreur création plan_culture : %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    return RedirectResponse(url="/parcelles", status_code=303)


@router.post("/culture/{plan_id}/delete")
async def culture_delete(plan_id: int):
    delete_plan_culture(plan_id)
    return RedirectResponse(url="/parcelles", status_code=303)
