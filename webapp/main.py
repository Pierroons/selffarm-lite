"""
SelfFarm-Lite webapp — point d'entrée FastAPI.

Lancement :
    cd selffarm-lite
    PYTHONPATH=modules:. .venv/bin/uvicorn webapp.main:app --reload --port 8001

Puis http://localhost:8001
"""

from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

# Ajoute modules/ au path pour import self_dnja, self_aid
BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / "modules"))
sys.path.insert(0, str(BASE_DIR))

from webapp import __version__
from webapp.routes import home as home_module
from webapp.routes import dnja as dnja_module
from webapp.routes import aides as aides_module
from webapp.routes import parcelles as parcelles_module
from webapp.routes import invoice as invoice_module
from webapp.routes import compta as compta_module
from webapp.routes import backup as backup_module
from webapp.routes import onboarding as onboarding_module

from self_agri_book.exploitation import is_onboarding_done, get_exploitation
from webapp import modules_catalog
from webapp.icons import icon_svg
from webapp.modules_state import (
    is_module_active, is_module_visible, get_view_mode, get_active_ids,
    active_module_id, active_tab, first_visible_route, visible_tabs,
)

home_router = home_module.router
dnja_router = dnja_module.router
aides_router = aides_module.router
parcelles_router = parcelles_module.router
invoice_router = invoice_module.router
compta_router = compta_module.router
backup_router = backup_module.router
onboarding_router = onboarding_module.router

from webapp.routes import roadmap as roadmap_module
roadmap_router = roadmap_module.router

from webapp.routes import pos as pos_module
pos_router = pos_module.router

from webapp.routes import modules as modules_routes
modules_route_router = modules_routes.router

# Variable d'environnement injectée comme global Jinja2 (visible dans tous templates)
# - 'prod' (défaut) : pas de bandeau, comportement normal
# - 'dev'           : bandeau orange "ENV DEV — données purgeables"
ENV_NAME = os.environ.get("SELFFARM_ENV", "prod")


def _fmt_eur(value) -> str:
    """Formate un nombre en chaîne avec espaces fines pour milliers (ex: 1234 → '1 234')."""
    try:
        n = float(value or 0)
    except (TypeError, ValueError):
        return "0"
    return f"{n:,.0f}".replace(",", " ")


def _fmt_ha(value) -> str:
    try:
        return f"{float(value or 0):.2f}".replace(".", ",")
    except (TypeError, ValueError):
        return "0,00"


from self_backup import backup_health  # santé sauvegardes (B3c) → bandeau global

for _route_module in (home_module, dnja_module, aides_module, parcelles_module, invoice_module, compta_module, backup_module, onboarding_module, roadmap_module, pos_module, modules_routes):
    if hasattr(_route_module, "templates"):
        _route_module.templates.env.globals["env"] = ENV_NAME
        # Expose get_exploitation() comme global Jinja pour que tous les templates
        # puissent récupérer le profil actif (sidebar, pages, etc.).
        _route_module.templates.env.globals["get_exploitation"] = get_exploitation
        # Système modes/modules — sidebar dynamique + vue complète
        _route_module.templates.env.globals["modules_catalog"] = modules_catalog
        _route_module.templates.env.globals["is_module_active"] = is_module_active
        _route_module.templates.env.globals["is_module_visible"] = is_module_visible
        _route_module.templates.env.globals["get_view_mode"] = get_view_mode
        _route_module.templates.env.globals["get_active_modules"] = get_active_ids
        _route_module.templates.env.globals["active_module_id"] = active_module_id
        _route_module.templates.env.globals["active_tab"] = active_tab
        _route_module.templates.env.globals["first_visible_route"] = first_visible_route
        _route_module.templates.env.globals["visible_tabs"] = visible_tabs
        _route_module.templates.env.globals["icon"] = icon_svg
        _route_module.templates.env.globals["backup_alert"] = backup_health
        # Filters monnaie / surface — utilisés par home.html (dashboard)
        _route_module.templates.env.filters["eur"] = _fmt_eur
        _route_module.templates.env.filters["ha"] = _fmt_ha

log = logging.getLogger("selffarm-webapp")


def setup_logging():
    level = os.environ.get("SELFFARM_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    log.info("SelfFarm-Lite webapp v%s démarré", __version__)
    # Snapshot local automatique (B2) — best-effort, en arrière-plan (ne ralentit pas le boot)
    try:
        import threading
        from self_backup import auto_snapshot_if_due
        threading.Thread(
            target=lambda: auto_snapshot_if_due(version=__version__),
            daemon=True, name="auto-snapshot",
        ).start()
    except Exception as e:
        log.warning("Snapshot auto au démarrage impossible (%s) — non bloquant", e)
    # Rappel d'oubli (B3c) + watcher branchement à chaud — retry initial puis surveille
    # le rebranchement du DD pour rattraper une sauvegarde manquée sans redémarrer
    # l'app. Best-effort, thread de fond.
    try:
        import threading
        from self_backup import backup_watcher
        threading.Thread(
            target=lambda: backup_watcher(version=__version__),
            daemon=True, name="backup-watcher",
        ).start()
    except Exception as e:
        log.warning("Watcher sauvegardes impossible (%s) — non bloquant", e)
    yield
    log.info("SelfFarm-Lite webapp arrêt propre")


app = FastAPI(
    title="SelfFarm-Lite",
    version=__version__,
    description="Modules agricoles JA — AGPL-3.0-or-later — partie de l'écosystème MySelf",
    lifespan=lifespan,
)

# Session middleware (pour wizard d'onboarding multi-étapes)
# Secret depuis env, fallback dev (à override en prod via SELFFARM_SESSION_SECRET)
SESSION_SECRET = os.environ.get(
    "SELFFARM_SESSION_SECRET",
    "selffarm-dev-only-change-me-in-prod-via-env-var-please",
)
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="selffarm_session",
    max_age=14 * 24 * 3600,  # 14 jours
    same_site="lax",
)


# Middleware redirect onboarding : si profil exploitation pas créé et user n'est pas
# dans le flow /onboarding ou les assets statiques, redirige vers le wizard.
# Désactivé en env=demo (la démo publique n'a pas besoin de profil).
@app.middleware("http")
async def require_onboarding(request: Request, call_next):
    path = request.url.path
    # Routes exemptes : onboarding lui-même, assets, swagger, healthz, et la
    # SAUVEGARDE (/backup) — un PC neuf doit pouvoir RESTAURER avant l'onboarding
    # (scénario catastrophe : DD branché sur une install fraîche).
    EXEMPT_PREFIXES = ("/onboarding", "/static", "/docs", "/openapi.json", "/healthz", "/favicon", "/backup")
    if ENV_NAME == "demo" or any(path.startswith(p) for p in EXEMPT_PREFIXES):
        return await call_next(request)
    # Si onboarding pas terminé → redirect /onboarding/1
    try:
        if not is_onboarding_done():
            return RedirectResponse(url="/onboarding/1", status_code=302)
    except Exception as e:
        log.warning("Erreur check onboarding (%s) — bypass pour ne pas bloquer", e)
    return await call_next(request)


@app.middleware("http")
async def no_cache_service_worker(request: Request, call_next):
    """No-cache sur le service worker (et version.json) — garde-fou PWA #2 :
    le navigateur est forcé de re-fetcher le SW à chaque visite (pas de cache stale)."""
    resp = await call_next(request)
    p = request.url.path
    if p.endswith("sw-mobile.js") or p.endswith("sw.js") or p.endswith("version.json"):
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
    return resp


# Static
STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Routers
app.include_router(home_router)
app.include_router(dnja_router)
app.include_router(aides_router)
app.include_router(parcelles_router)
app.include_router(invoice_router)
app.include_router(compta_router)
app.include_router(backup_router)
app.include_router(onboarding_router)
app.include_router(roadmap_router)
app.include_router(pos_router)
app.include_router(modules_route_router)


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"status": "ok", "version": __version__, "env": ENV_NAME}


def main_cli():
    import uvicorn
    uvicorn.run(
        "webapp.main:app",
        host=os.environ.get("SELFFARM_HOST", "127.0.0.1"),
        port=int(os.environ.get("SELFFARM_PORT", "8001")),
        reload=False,
    )


if __name__ == "__main__":
    main_cli()
