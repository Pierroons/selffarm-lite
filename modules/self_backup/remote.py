"""self_backup.remote — sauvegarde distante chiffrée vers un serveur SSH (SFTP).

Principe (souverain / zero-knowledge) :
  make_backup() → ZIP → chiffrement GPG vers la clé publique de l'utilisateur →
  envoi SFTP sur SA cible (NAS, serveur, Pi...). Le serveur distant ne stocke
  QUE du `.zip.gpg` illisible ; seule la clé privée (hors app) peut déchiffrer.

Auth SSH par clé uniquement (jamais de mot de passe en config).
Calqué sur le connecteur disque externe (backup_to_external) — même rétention,
même mémoire de config JSON (backup_sftp.json à côté de la DB).
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from self_backup import _db_path, make_backup

log = logging.getLogger("self_backup.remote")

REMOTE_SUFFIX = ".gpg"


# ── Config ───────────────────────────────────────────────────────────────────
def _sftp_config_path() -> Path:
    return _db_path().parent / "backup_sftp.json"


def load_sftp_config() -> dict:
    p = _sftp_config_path()
    if p.exists():
        try:
            return json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_sftp_config(cfg: dict) -> None:
    _sftp_config_path().write_text(json.dumps(cfg, indent=2, ensure_ascii=False))


# ── Chiffrement GPG (clé publique → la machine chiffre mais ne déchiffre pas) ──
def _encrypt_gpg(data: bytes, recipient: str) -> bytes:
    """Chiffre `data` vers la clé publique `recipient` (key-id, fingerprint ou email).
    Non interactif (--batch). --trust-model always : on assume la clé du user.
    """
    if not recipient:
        raise ValueError("Destinataire GPG manquant (clé publique de chiffrement).")
    proc = subprocess.run(
        ["gpg", "--batch", "--yes", "--trust-model", "always",
         "--encrypt", "--recipient", recipient, "--output", "-"],
        input=data, capture_output=True,
    )
    if proc.returncode != 0 or not proc.stdout:
        err = proc.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"Chiffrement GPG échoué (recipient={recipient}) : {err}")
    return proc.stdout


def gpg_recipient_ok(recipient: str) -> bool:
    """Vérifie qu'une clé publique correspond au destinataire (sinon chiffrement impossible)."""
    if not recipient:
        return False
    r = subprocess.run(["gpg", "--list-keys", recipient],
                       capture_output=True, text=True)
    return r.returncode == 0


# ── Transport SFTP (paramiko) ─────────────────────────────────────────────────
def _connect(cfg: dict):
    """Ouvre (ssh, sftp) vers la cible. Auth par clé SSH uniquement."""
    import paramiko

    host = (cfg.get("host") or "").strip()
    if not host:
        raise ValueError("Hôte SSH manquant.")
    port = int(cfg.get("port") or 22)
    username = (cfg.get("username") or "").strip()
    if not username:
        raise ValueError("Utilisateur SSH manquant.")
    key_path = os.path.expanduser((cfg.get("key_path") or "").strip())
    # Clé explicite si fournie ET présente ; sinon on s'appuie sur l'agent SSH.
    key_filename = key_path if (key_path and Path(key_path).exists()) else None

    ssh = paramiko.SSHClient()
    ssh.load_system_host_keys()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        hostname=host, port=port, username=username,
        key_filename=key_filename, look_for_keys=True, allow_agent=True,
        timeout=15,
    )
    sftp = ssh.open_sftp()
    return ssh, sftp


def _sftp_makedirs(sftp, remote_dir: str) -> None:
    """mkdir -p distant (paramiko ne le fait pas nativement)."""
    absolute = remote_dir.startswith("/")
    cur = ""
    for part in (p for p in remote_dir.split("/") if p):
        cur = (cur + "/" + part) if cur else (("/" + part) if absolute else part)
        try:
            sftp.stat(cur)
        except IOError:
            sftp.mkdir(cur)


def test_sftp(cfg: dict) -> dict:
    """Teste connexion + droit d'écriture dans le dossier distant.
    Retourne {ok: bool, message: str}."""
    remote_dir = (cfg.get("remote_dir") or "").strip()
    if not remote_dir:
        return {"ok": False, "message": "Dossier distant manquant."}
    if not gpg_recipient_ok(cfg.get("gpg_recipient", "")):
        return {"ok": False,
                "message": f"Clé GPG '{cfg.get('gpg_recipient')}' introuvable dans ton trousseau."}
    ssh = sftp = None
    try:
        ssh, sftp = _connect(cfg)
        _sftp_makedirs(sftp, remote_dir)
        probe = f"{remote_dir.rstrip('/')}/.selffarm_wtest"
        with sftp.open(probe, "w") as fh:
            fh.write("ok")
        sftp.remove(probe)
        return {"ok": True,
                "message": f"Connexion OK — écriture validée dans {remote_dir}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": f"{type(e).__name__} : {e}"}
    finally:
        if sftp:
            sftp.close()
        if ssh:
            ssh.close()


def _prune_remote(sftp, remote_dir: str, keep: int) -> int:
    """Ne garde que les `keep` archives les plus récentes (tri par nom = tri chrono)."""
    try:
        names = [n for n in sftp.listdir(remote_dir)
                 if n.startswith("selffarm-backup-") and n.endswith(".zip" + REMOTE_SUFFIX)]
    except IOError:
        return 0
    removed = 0
    for n in sorted(names, reverse=True)[keep:]:
        try:
            sftp.remove(f"{remote_dir.rstrip('/')}/{n}")
            removed += 1
        except IOError:
            pass
    return removed


def backup_to_sftp(version: str = "0.1.0-dev", keep: Optional[int] = None) -> dict:
    """Crée le backup, le chiffre (GPG), l'envoie en SFTP, applique la rétention,
    et mémorise la date/destination. Lève une exception en cas d'échec."""
    cfg = load_sftp_config()
    remote_dir = (cfg.get("remote_dir") or "").strip()
    if not remote_dir:
        raise ValueError("Dossier distant non configuré.")
    keep = int(cfg.get("retention", 30)) if keep is None else keep
    recipient = cfg.get("gpg_recipient", "")

    zip_bytes, filename = make_backup(version=version)
    enc = _encrypt_gpg(zip_bytes, recipient)
    remote_name = filename + REMOTE_SUFFIX
    remote_path = f"{remote_dir.rstrip('/')}/{remote_name}"

    ssh = sftp = None
    try:
        ssh, sftp = _connect(cfg)
        _sftp_makedirs(sftp, remote_dir)
        with sftp.open(remote_path, "wb") as fh:
            fh.write(enc)
        pruned = _prune_remote(sftp, remote_dir, keep)
    finally:
        if sftp:
            sftp.close()
        if ssh:
            ssh.close()

    cfg.update({
        "last_sftp_backup_utc": datetime.now(timezone.utc).isoformat(),
        "last_sftp_path": remote_path,
        "last_sftp_size": len(enc),
        "last_sftp_error": None,
    })
    save_sftp_config(cfg)
    log.info("Backup SFTP chiffré envoyé : %s (%d octets, %d purgés)",
             remote_path, len(enc), pruned)
    return {"path": remote_path, "size_bytes": len(enc),
            "host": cfg.get("host"), "pruned": pruned}
