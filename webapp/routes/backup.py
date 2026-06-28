"""Route /backup — sauvegarde + restore de la DB compta SelfFarm-Lite."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from webapp import __version__

router = APIRouter(prefix="/backup", tags=["backup"])

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

log = logging.getLogger("selffarm-webapp.backup")


def _is_demo() -> bool:
    return os.environ.get("SELFFARM_ENV", "prod") == "demo"


def _block_in_demo():
    """Bloque les ACTIONS backup/restore (POST) sur la démo publique partagée.

    La page GET /backup, elle, reste consultable en mode vitrine lecture seule
    (cf. backup_index) — on montre l'interface, on interdit juste d'agir.
    """
    if _is_demo():
        raise HTTPException(
            status_code=404,
            detail="Backup/restore désactivé sur la démo publique. "
                   "Utilise une instance perso ou install Docker.",
        )


# Données d'exemple pour la vitrine démo — AUCUNE donnée réelle du serveur
# (pas de chemin disque, montage, ni config SFTP de l'instance de démo).
_DEMO_CONTEXT = {
    "demo_readonly": True,
    "db_path": "~/.selffarm/compta.db",
    "db_exists": True,
    "db_size": 245760,
    "stats": {
        "nb_ecritures": 128,
        "first_date": "2026-01-05",
        "last_date": "2026-06-20",
        "sources": {"factures": 42, "saisie": 64, "import": 22},
    },
    "external_mounts": [],
    "ext_config": {},
    "nb_snapshots": 3,
    "last_snapshot_age_h": 6,
    "cron_schedule": None,
    "sftp_config": {},
}


@router.get("", response_class=HTMLResponse)
async def backup_index(request: Request):
    if _is_demo():
        # Vitrine publique : on affiche l'UI complète en lecture seule, sans
        # toucher à l'état réel du serveur (OPSEC) ni autoriser la moindre action.
        return templates.TemplateResponse(
            "backup/index.html",
            {"request": request, "version": __version__, **_DEMO_CONTEXT},
        )
    from self_backup import (
        _db_path, _stats_db, list_external_mounts, load_ext_config,
        _snapshots, _last_snapshot_age_hours, get_cron_schedule,
    )
    from self_backup.remote import load_sftp_config
    db_path = _db_path()
    stats = _stats_db(db_path)
    db_exists = db_path.exists()
    db_size = db_path.stat().st_size if db_exists else 0
    return templates.TemplateResponse(
        "backup/index.html",
        {
            "request": request,
            "version": __version__,
            "demo_readonly": False,
            "db_path": str(db_path),
            "db_exists": db_exists,
            "db_size": db_size,
            "stats": stats,
            "external_mounts": list_external_mounts(),
            "ext_config": load_ext_config(),
            "nb_snapshots": len(_snapshots()),
            "last_snapshot_age_h": _last_snapshot_age_hours(),
            "cron_schedule": get_cron_schedule(),
            "sftp_config": load_sftp_config(),
        },
    )


@router.get("/health")
async def backup_health_json():
    """État des sauvegardes (JSON) pour le bandeau live. Si une cible est en alerte,
    tente un rattrapage immédiat du DD (s'il est revenu) → le bandeau se résout vite."""
    _block_in_demo()
    from self_backup import backup_health, retry_missed_backups
    h = backup_health()
    if h["alert"] and h["external"]["alert"]:
        try:
            retry_missed_backups(version=__version__, targets=("external",))
        except Exception:  # noqa: BLE001
            pass
        h = backup_health()
    return JSONResponse({
        "alert": h["alert"],
        "messages": h["messages"],
        "external_ok": not h["external"]["alert"],
        "sftp_ok": not h["sftp"]["alert"],
    })


@router.get("/demarrage", response_class=HTMLResponse)
async def backup_demarrage(request: Request):
    """Disclaimer install : choix d'une cible de sauvegarde (clé USB recommandée)."""
    _block_in_demo()
    from self_backup import list_external_mounts
    mounts = [m for m in list_external_mounts() if m.get("writable")]
    return templates.TemplateResponse(
        "backup/demarrage.html",
        {"request": request, "version": __version__, "mounts": mounts},
    )


@router.post("/demarrage/utiliser")
async def backup_demarrage_utiliser(mount_path: str = Form(...)):
    """Configure la clé comme cible par défaut : 1ère sauvegarde + cron quotidien 20h."""
    _block_in_demo()
    from self_backup import backup_to_external, set_cron_schedule
    try:
        backup_to_external(mount_path, version=__version__)
        set_cron_schedule(hour=20)
    except Exception as e:  # noqa: BLE001
        log.warning("Démarrage backup échoué : %s", e)
        return RedirectResponse(url="/backup/demarrage?err=1", status_code=303)
    return RedirectResponse(url="/?backup_ok=1", status_code=303)


@router.post("/demarrage/plus-tard")
async def backup_demarrage_plus_tard():
    """L'utilisateur reporte → pas de cible (le rappel d'oubli s'en chargera)."""
    _block_in_demo()
    return RedirectResponse(url="/", status_code=303)


@router.post("/distant/config")
async def backup_distant_config(
    host: str = Form(...),
    port: int = Form(22),
    username: str = Form(...),
    key_path: str = Form(...),
    remote_dir: str = Form(...),
    gpg_recipient: str = Form(...),
    retention: int = Form(30),
    enabled: str = Form(""),
):
    """Enregistre la config de la sauvegarde distante SFTP chiffrée (B4)."""
    _block_in_demo()
    from self_backup.remote import load_sftp_config, save_sftp_config
    cfg = load_sftp_config()
    cfg.update({
        "host": host.strip(),
        "port": int(port),
        "username": username.strip(),
        "key_path": key_path.strip(),
        "remote_dir": remote_dir.strip(),
        "gpg_recipient": gpg_recipient.strip(),
        "retention": int(retention),
        "enabled": enabled == "on",
    })
    save_sftp_config(cfg)
    return RedirectResponse(url="/backup", status_code=303)


@router.post("/distant/test")
async def backup_distant_test():
    """Teste la connexion SFTP + le droit d'écriture, mémorise le résultat."""
    _block_in_demo()
    from self_backup.remote import load_sftp_config, save_sftp_config, test_sftp
    cfg = load_sftp_config()
    res = test_sftp(cfg)
    cfg["last_test"] = {
        "ok": res["ok"], "message": res["message"],
        "at": datetime.now(timezone.utc).isoformat(),
    }
    save_sftp_config(cfg)
    return RedirectResponse(url="/backup", status_code=303)


@router.post("/distant/maintenant")
async def backup_distant_now():
    """Lance immédiatement une sauvegarde chiffrée vers le serveur distant."""
    _block_in_demo()
    from self_backup.remote import backup_to_sftp, load_sftp_config, save_sftp_config
    try:
        backup_to_sftp(version=__version__)
    except Exception as e:  # noqa: BLE001
        log.warning("Backup distant échoué : %s", e)
        cfg = load_sftp_config()
        cfg["last_test"] = {
            "ok": False, "message": f"Échec sauvegarde : {e}",
            "at": datetime.now(timezone.utc).isoformat(),
        }
        save_sftp_config(cfg)
        return RedirectResponse(url="/backup?sftp_err=1", status_code=303)
    return RedirectResponse(url="/backup?sftp_ok=1", status_code=303)


@router.post("/distant/desactiver")
async def backup_distant_off():
    """Désactive la sauvegarde distante (garde la config, coupe juste l'auto)."""
    _block_in_demo()
    from self_backup.remote import load_sftp_config, save_sftp_config
    cfg = load_sftp_config()
    cfg["enabled"] = False
    save_sftp_config(cfg)
    return RedirectResponse(url="/backup", status_code=303)


@router.post("/externe")
async def backup_externe(request: Request, mount_path: str = Form(...)):
    """Sauvegarde manuelle sur un disque externe (B3a)."""
    _block_in_demo()
    from self_backup import backup_to_external
    try:
        backup_to_external(mount_path, version=__version__)
    except Exception as e:
        log.warning("Backup externe échoué (%s) : %s", mount_path, e)
        return RedirectResponse(url="/backup?ext_err=1", status_code=303)
    return RedirectResponse(url="/backup?ext_ok=1", status_code=303)


@router.post("/planifier")
async def backup_planifier(hour: int = Form(20), dow: str = Form("*")):
    """Active/MAJ la sauvegarde auto vers le DD (écrit une ligne dans le crontab user)."""
    _block_in_demo()
    from self_backup import set_cron_schedule
    try:
        set_cron_schedule(hour=int(hour), dow=dow)
    except Exception as e:
        log.warning("Planif cron échouée : %s", e)
        return RedirectResponse(url="/backup?cron_err=1", status_code=303)
    return RedirectResponse(url="/backup?cron_ok=1", status_code=303)


@router.post("/deplanifier")
async def backup_deplanifier():
    """Retire la sauvegarde auto du crontab (laisse le reste intact)."""
    _block_in_demo()
    from self_backup import clear_cron_schedule
    clear_cron_schedule()
    return RedirectResponse(url="/backup", status_code=303)


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
async def backup_restore(request: Request, archive: UploadFile = File(...), confirm_rollback: str = Form("")):
    _block_in_demo()
    from self_backup import restore_from_bytes
    if not archive.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Fichier attendu : .zip")
    zip_bytes = await archive.read()
    if not zip_bytes:
        raise HTTPException(status_code=400, detail="Archive vide")
    try:
        result = restore_from_bytes(zip_bytes, confirm_rollback=(confirm_rollback == "on"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # pragma: no cover
        log.exception("Restore failed")
        raise HTTPException(status_code=500, detail=f"Erreur restore : {e}")

    if result.get("needs_confirmation"):
        raise HTTPException(status_code=409, detail=(
            f"Ce backup est plus ANCIEN que tes données (sauvegarde gén. {result['gen_backup']} "
            f"< base gén. {result['gen_base']}). Ta compta et tes factures seraient préservées, "
            f"mais l'état métier reculerait. Pour confirmer : coche « Autoriser le retour en arrière » "
            f"et re-soumets le fichier."
        ))
    return templates.TemplateResponse(
        "backup/restore_ok.html",
        {
            "request": request,
            "version": __version__,
            "result": result,
        },
    )


@router.get("/restaurer", response_class=HTMLResponse)
async def backup_restaurer_page(request: Request):
    """Écran de restauration depuis un support détecté (DD) — scénario catastrophe."""
    _block_in_demo()
    from self_backup import list_external_mounts, list_backups_on_mount
    supports = []
    for m in list_external_mounts():
        backups = list_backups_on_mount(m["path"])
        if backups:
            supports.append({"mount": m, "backups": backups})
    return templates.TemplateResponse(
        "backup/restaurer.html",
        {"request": request, "version": __version__, "supports": supports},
    )


@router.post("/restaurer")
async def backup_restaurer(request: Request, mount_path: str = Form(...), name: str = Form(...), confirm_rollback: str = Form("")):
    """Restaure le backup choisi depuis le support + récupère la clé de coffre."""
    _block_in_demo()
    from self_backup import restore_from_support
    try:
        result = restore_from_support(mount_path, name, confirm_rollback=(confirm_rollback == "on"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:  # noqa: BLE001
        log.exception("Restore depuis support échoué")
        raise HTTPException(status_code=500, detail=f"Erreur restore : {e}")
    if result.get("needs_confirmation"):
        return templates.TemplateResponse(
            "backup/restore_confirm.html",
            {"request": request, "version": __version__,
             "gen_base": result["gen_base"], "gen_backup": result["gen_backup"],
             "confirm_action": "/backup/restaurer",
             "confirm_fields": {"mount_path": mount_path, "name": name}},
        )
    return templates.TemplateResponse(
        "backup/restore_ok.html",
        {"request": request, "version": __version__, "result": result},
    )
