"""
Job de sauvegarde automatique (lancé par cron, B3b/B4).

Autonome : ne dépend PAS de la webapp en cours d'exécution. Pousse vers les
destinations configurées, chacune indépendante (l'échec de l'une n'empêche pas
l'autre) :
  1. Disque externe mémorisé (par UUID dans backup_external.json) — B3a/B3b
  2. Serveur SSH distant chiffré (backup_sftp.json, si activé) — B4

Lancement (typiquement par cron) :
    SELFFARM_DATA_DIR=~/.selffarm-perso PYTHONPATH=modules python -m self_backup.autobackup
"""
from __future__ import annotations

import logging
import os
import urllib.request
from datetime import UTC, datetime

from self_backup import (
    backup_to_external,
    list_external_mounts,
    load_ext_config,
    save_ext_config,
)


def _notify(log, body: str) -> None:
    """Push ntfy optionnel (si SELFFARM_NTFY_URL défini) — rappel d'oubli (B3c)."""
    url = os.environ.get("SELFFARM_NTFY_URL")
    if not url:
        return
    try:
        req = urllib.request.Request(
            url, data=body.encode("utf-8"),
            headers={"Title": "SelfFarm - sauvegarde manquee", "Priority": "high", "Tags": "warning"},
        )
        urllib.request.urlopen(req, timeout=8)
    except Exception as e:  # noqa: BLE001
        log.warning("ntfy non envoyé : %s", e)


def _backup_external(log, version: str) -> int:
    """Disque externe (B3a/B3b). Retourne 0 si OK/non configuré, 1 si manqué."""
    cfg = load_ext_config()
    target_uuid = cfg.get("disk_uuid")
    if not target_uuid:
        log.info("Disque externe : aucun mémorisé — ignoré.")
        return 0

    mounts = {m.get("uuid"): m for m in list_external_mounts() if m.get("uuid")}
    m = mounts.get(target_uuid)
    if m and m.get("writable"):
        r = backup_to_external(m["path"], version=version)
        log.info("Disque externe OK : %s (%d octets)", r.get("path"), r.get("size_bytes", 0))
        return 0

    cfg["last_missed_utc"] = datetime.now(UTC).isoformat()
    save_ext_config(cfg)
    log.warning("Disque externe %s absent/non inscriptible → manqué (noté).", target_uuid)
    _notify(log, "Disque externe de sauvegarde absent ou non inscriptible — branche-le pour rattraper.")
    return 1


def _backup_sftp(log, version: str) -> int:
    """Serveur SSH distant chiffré (B4). Retourne 0 si OK/désactivé, 2 si échec."""
    try:
        from self_backup.remote import backup_to_sftp, load_sftp_config, save_sftp_config
    except Exception as e:  # noqa: BLE001 — paramiko absent, etc.
        log.warning("SFTP distant indisponible : %s", e)
        return 0

    scfg = load_sftp_config()
    if not scfg.get("enabled"):
        log.info("SFTP distant : non activé — ignoré.")
        return 0

    try:
        res = backup_to_sftp(version=version)
        log.info("SFTP distant OK : %s (%d octets)", res.get("path"), res.get("size_bytes", 0))
        return 0
    except Exception as e:  # noqa: BLE001
        scfg["last_sftp_error"] = str(e)
        scfg["last_sftp_missed_utc"] = datetime.now(UTC).isoformat()
        save_sftp_config(scfg)
        log.warning("SFTP distant échoué → manqué (noté) : %s", e)
        _notify(log, f"Sauvegarde distante chiffrée échouée — serveur injoignable ? ({e})")
        return 2


def run(version: str = "0.1.0-dev") -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    log = logging.getLogger("selffarm.autobackup")

    rc = 0
    rc |= _backup_external(log, version)
    rc |= _backup_sftp(log, version)
    return rc


if __name__ == "__main__":
    raise SystemExit(run())
