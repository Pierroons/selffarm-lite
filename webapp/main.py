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

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

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

home_router = home_module.router
dnja_router = dnja_module.router
aides_router = aides_module.router
parcelles_router = parcelles_module.router
invoice_router = invoice_module.router
compta_router = compta_module.router

# Variable d'environnement injectée comme global Jinja2 (visible dans tous templates)
# - 'prod' (défaut) : pas de bandeau, comportement normal
# - 'dev'           : bandeau orange "ENV DEV — données purgeables"
ENV_NAME = os.environ.get("SELFFARM_ENV", "prod")
for _route_module in (home_module, dnja_module, aides_module, parcelles_module, invoice_module, compta_module):
    if hasattr(_route_module, "templates"):
        _route_module.templates.env.globals["env"] = ENV_NAME

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
    yield
    log.info("SelfFarm-Lite webapp arrêt propre")


app = FastAPI(
    title="SelfFarm-Lite",
    version=__version__,
    description="Modules agricoles JA — AGPL-3.0-or-later — partie de l'écosystème MySelf",
    lifespan=lifespan,
)

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
