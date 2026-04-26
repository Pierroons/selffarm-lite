"""Route /backup — sauvegarde + restore de la DB compta SelfFarm-Lite."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from webapp import __version__

router = APIRouter(prefix="/backup", tags=["backup"])

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

log = logging.getLogger("selffarm-webapp.backup")


def _block_in_demo():
    """Le backup/restore n'a pas de sens sur la démo publique partagée."""
    if os.environ.get("SELFFARM_ENV", "prod") == "demo":
        raise HTTPException(
            status_code=404,
            detail="Backup/restore désactivé sur la démo publique. "
                   "Utilise une instance perso ou install Docker.",
        )


@router.get("", response_class=HTMLResponse)
async def backup_index(request: Request):
    _block_in_demo()
    from self_backup import _db_path, _stats_db
    db_path = _db_path()
    stats = _stats_db(db_path)
    db_exists = db_path.exists()
    db_size = db_path.stat().st_size if db_exists else 0
    return templates.TemplateResponse(
        "backup/index.html",
        {
            "request": request,
            "version": __version__,
            "db_path": str(db_path),
            "db_exists": db_exists,
            "db_size": db_size,
            "stats": stats,
        },
    )


@router.get("/download")
async def backup_download():
    _block_in_demo()
    from self_backup import make_backup
    try:
        zip_bytes, filename = make_backup(version=__version__)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Selffarm-Backup-Filename": filename,
        },
    )


@router.post("/restore")
async def backup_restore(request: Request, archive: UploadFile = File(...)):
    _block_in_demo()
    from self_backup import restore_from_bytes
    if not archive.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Fichier attendu : .zip")
    zip_bytes = await archive.read()
    if not zip_bytes:
        raise HTTPException(status_code=400, detail="Archive vide")
    try:
        result = restore_from_bytes(zip_bytes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # pragma: no cover
        log.exception("Restore failed")
        raise HTTPException(status_code=500, detail=f"Erreur restore : {e}")

    return templates.TemplateResponse(
        "backup/restore_ok.html",
        {
            "request": request,
            "version": __version__,
            "result": result,
        },
    )
