"""self_backup — export / import sauvegarde SelfFarm-Lite.

Format archive : ZIP contenant
- compta.db          : base SQLite hub compta
- manifest.json      : métadonnées (version app, date, sha256, stats)
- README.md          : notice utilisateur

L'archive est portable entre OS (Linux/macOS/Windows) et entre versions de
SelfFarm-Lite (les migrations versionnées s'appliquent automatiquement au
restore).
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import shutil
import sqlite3
import zipfile
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger("self_backup")

MANIFEST_VERSION = 1


def _db_path() -> Path:
    """Chemin courant de la DB compta (même résolution que self_agri_book.storage) :
    SELFFARM_COMPTA_DB, sinon SELFFARM_DATA_DIR/compta.db, sinon ~/.selffarm/compta.db."""
    explicit = os.environ.get("SELFFARM_COMPTA_DB")
    if explicit:
        return Path(explicit)
    data_dir = os.environ.get("SELFFARM_DATA_DIR", str(Path.home() / ".selffarm"))
    return Path(data_dir) / "compta.db"


def _factures_dir() -> Path:
    """Dossier d'archivage des PDF de factures émises (à côté de la DB)."""
    return _db_path().parent / "factures"


def _schema_version(db_path: Path) -> int:
    """N° de la dernière migration appliquée dans une DB (pour la compat au restore)."""
    if not db_path.exists():
        return 0
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute("SELECT MAX(version) AS v FROM _schema_migrations").fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()


def _app_schema_version() -> int | None:
    """Schéma max que CETTE version de l'app sait gérer (dernière migration définie).
    None si indéterminable → on ne bloque pas (fallback permissif)."""
    try:
        from self_agri_book.storage import MIGRATIONS
        return max((v for v, _, _ in MIGRATIONS), default=0)
    except Exception:  # noqa: BLE001 — module optionnel : absence ou erreur = pas de version
        return None


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _stats_db(db_path: Path) -> dict:
    """Lit quelques stats de la DB sans dépendre de self_agri_book."""
    if not db_path.exists():
        return {"nb_ecritures": 0, "first_date": None, "last_date": None, "sources": {}}
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        nb = conn.execute("SELECT COUNT(*) AS n FROM ecritures_comptables").fetchone()["n"]
        if nb > 0:
            dates = conn.execute(
                "SELECT MIN(date_operation) AS first, MAX(date_operation) AS last "
                "FROM ecritures_comptables"
            ).fetchone()
            first_date, last_date = dates["first"], dates["last"]
        else:
            first_date = last_date = None
        sources = {
            r["source_module"] or "manuel": r["n"]
            for r in conn.execute(
                "SELECT source_module, COUNT(*) AS n "
                "FROM ecritures_comptables GROUP BY source_module"
            )
        }
    except sqlite3.OperationalError:
        # Table inexistante (DB toute fraîche)
        nb = 0
        first_date = last_date = None
        sources = {}
    finally:
        conn.close()
    return {
        "nb_ecritures": nb,
        "first_date": first_date,
        "last_date": last_date,
        "sources": sources,
    }


def make_backup(version: str = "0.1.0-dev") -> tuple[bytes, str]:
    """Génère un ZIP archive contenant la DB + manifest + README.

    Retourne (zip_bytes, suggested_filename).
    """
    db_path = _db_path()
    if not db_path.exists():
        raise FileNotFoundError(
            f"DB compta absente : {db_path} — rien à sauvegarder. "
            f"Génère au moins une écriture avant le backup."
        )

    sha256 = _file_sha256(db_path)
    db_size = db_path.stat().st_size
    stats = _stats_db(db_path)
    now = datetime.now(UTC)

    # PDF de factures émises archivés (documents originaux — conformité 10 ans + restore fidèle)
    fdir = _factures_dir()
    facture_files = sorted(fdir.glob("*.pdf")) if fdir.exists() else []
    factures_size = sum(f.stat().st_size for f in facture_files)

    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "selffarm_version": version,
        "schema_version": _schema_version(db_path),
        "exported_at_utc": now.isoformat(),
        "exported_at_local": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "db_filename": "compta.db",
        "db_size_bytes": db_size,
        "db_sha256": sha256,
        "nb_factures": len(facture_files),
        "factures_size_bytes": factures_size,
        "stats": stats,
    }

    readme = f"""# Sauvegarde SelfFarm-Lite

Archive générée le {manifest['exported_at_local']} (UTC : {manifest['exported_at_utc']})

## Contenu

- `compta.db`        — base SQLite hub compta ({db_size:,} octets)
- `manifest.json`    — métadonnées du backup
- `README.md`        — ce fichier

## Stats

- Nombre d'écritures   : {stats['nb_ecritures']}
- Première écriture    : {stats['first_date'] or 'aucune'}
- Dernière écriture    : {stats['last_date'] or 'aucune'}
- Sources              : {', '.join(f'{k} ({v})' for k, v in stats['sources'].items()) or 'aucune'}
- SHA256 DB            : {sha256}

## Comment restaurer

### Via la webapp
1. Ouvre `http://localhost:8001/backup`
2. Bouton "Restaurer depuis un fichier"
3. Sélectionne ce ZIP
4. Redémarre l'app (recommandé)

### Manuellement (Linux / macOS)
```bash
unzip selffarm-backup-*.zip
cp compta.db ~/.selffarm/compta.db
```

### Vérification d'intégrité
```bash
sha256sum compta.db
# doit afficher : {sha256}
```

## Compatibilité

Ce backup est portable :
- Entre OS (Linux / macOS / Windows)
- Entre versions de SelfFarm-Lite (les migrations s'appliquent au restore)
- Format SQLite garanti standard et lisible avec n'importe quel client SQL

AGPL-3.0-or-later — partie de l'écosystème MySelf — my-self.fr
"""

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(db_path, arcname="compta.db")
        for fp in facture_files:
            zf.write(fp, arcname=f"factures/{fp.name}")
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        zf.writestr("README.md", readme)

    suggested_filename = (
        f"selffarm-backup-{now.strftime('%Y%m%d-%H%M%S')}-"
        f"{stats['nb_ecritures']}ecr.zip"
    )
    log.info(
        "Backup généré : %d écritures, %d octets DB, sha256 %s…",
        stats['nb_ecritures'], db_size, sha256[:12],
    )
    return buf.getvalue(), suggested_filename


def restore_from_bytes(zip_bytes: bytes, confirm_rollback: bool = False) -> dict:
    """Restaure depuis un ZIP via une restauration DIFFÉRENCIÉE (Partie E) :
    compta/facturation = union (jamais perdue), état = remplacé, anti-rétrogradage.

    Si le backup est plus ANCIEN que la base (rétro) et `confirm_rollback=False`,
    retourne {restored: False, needs_confirmation: True, gen_base, gen_backup} SANS
    rien toucher. L'ancienne base est copiée en .prediff-<ts> avant toute modif.
    """
    target = _db_path()
    target.parent.mkdir(parents=True, exist_ok=True)

    buf = io.BytesIO(zip_bytes)
    with zipfile.ZipFile(buf, "r") as zf:
        names = zf.namelist()
        if "compta.db" not in names:
            raise ValueError("Archive invalide : compta.db absent")
        if "manifest.json" not in names:
            raise ValueError("Archive invalide : manifest.json absent")

        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        if manifest.get("manifest_version", 0) > MANIFEST_VERSION:
            raise ValueError(
                f"Manifest version {manifest['manifest_version']} non supportée "
                f"(max supporté : {MANIFEST_VERSION})"
            )

        # Garde-fou anti-restore « descendant » : refuser un backup dont le schéma de
        # données est plus récent que ce que cette version de l'app sait gérer (sinon
        # incohérence : tables/colonnes inconnues). Les migrations ne savent que MONTER.
        backup_schema = manifest.get("schema_version")
        app_schema = _app_schema_version()
        if backup_schema is not None and app_schema is not None and backup_schema > app_schema:
            raise ValueError(
                f"Sauvegarde trop récente : elle provient d'une version de SelfFarm-Lite "
                f"plus avancée (schéma de données v{backup_schema}) que celle installée "
                f"(v{app_schema}). Mets d'abord l'application à jour, puis recommence la "
                f"restauration."
            )

        db_bytes = zf.read("compta.db")
        # PDF de factures archivés (optionnels, présents si backup B1+)
        facture_members = [n for n in names if n.startswith("factures/") and n.lower().endswith(".pdf")]
        factures_data = {n: zf.read(n) for n in facture_members}

    sha256_actual = hashlib.sha256(db_bytes).hexdigest()
    sha256_expected = manifest.get("db_sha256")
    sha256_match = (sha256_actual == sha256_expected) if sha256_expected else None

    # Écrit le backup extrait dans un fichier temporaire, puis applique la
    # restauration DIFFÉRENCIÉE (union compta/facturation, remplacement état,
    # anti-rétrogradage). cf self_agri_book.restore_diff.
    import tempfile

    from self_agri_book.restore_diff import restore_differential
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        tf.write(db_bytes)
        tmp_path = Path(tf.name)
    try:
        result = restore_differential(tmp_path, target, confirm_rollback=confirm_rollback)
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass

    # Rétrogradage détecté et NON confirmé → on ne touche à rien, on demande confirmation
    if result.get("needs_confirmation"):
        log.warning("Restore rétrogradant non confirmé (base gen %s > backup gen %s)",
                    result.get("gen_base"), result.get("gen_backup"))
        return {
            "restored": False,
            "needs_confirmation": True,
            "gen_base": result.get("gen_base"),
            "gen_backup": result.get("gen_backup"),
            "manifest": manifest,
            "sha256_match": sha256_match,
        }

    # Restaure les PDF de factures archivés (ne pas écraser les originaux déjà présents)
    nb_factures_restaurees = 0
    if factures_data:
        fdir = _factures_dir()
        fdir.mkdir(parents=True, exist_ok=True)
        for name, content in factures_data.items():
            fp = fdir / Path(name).name
            if not fp.exists():
                fp.write_bytes(content)
                nb_factures_restaurees += 1

    log.info(
        "Restore différencié (%s) terminé : %d factures restaurées, sha256 %s, match=%s",
        result.get("mode"), nb_factures_restaurees, sha256_actual[:12], sha256_match,
    )
    return {
        "restored": True,
        "mode": result.get("mode"),
        "manifest": manifest,
        "old_backup_path": result.get("prediff_bak"),
        "sha256_match": sha256_match,
        "target_path": str(target),
        "nb_factures_restaurees": nb_factures_restaurees,
        "gen_base": result.get("gen_base"),
        "gen_backup": result.get("gen_backup"),
    }


# ── Snapshots locaux automatiques (B2) ──────────────────────────────────────
def _backups_dir() -> Path:
    """Dossier des snapshots locaux (à côté de la DB)."""
    return _db_path().parent / "backups"


def _snapshots() -> list[Path]:
    d = _backups_dir()
    if not d.exists():
        return []
    return sorted(d.glob("selffarm-backup-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)


def _prune_snapshots(keep: int = 14) -> int:
    """Ne conserve que les `keep` snapshots les plus récents. Retourne le nb supprimé."""
    removed = 0
    for p in _snapshots()[keep:]:
        try:
            p.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def write_snapshot(version: str = "0.1.0-dev", keep: int = 14) -> Path | None:
    """Écrit un snapshot horodaté dans data_dir/backups/ + applique la rétention.
    Retourne le chemin, ou None si rien à sauvegarder (DB absente)."""
    try:
        zip_bytes, filename = make_backup(version=version)
    except FileNotFoundError:
        return None  # pas encore de DB (onboarding non fait) → rien à faire
    d = _backups_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / filename
    path.write_bytes(zip_bytes)
    _prune_snapshots(keep=keep)
    log.info("Snapshot local écrit : %s (%d octets)", path.name, len(zip_bytes))
    return path


def _last_snapshot_age_hours() -> float | None:
    """Âge (heures) du snapshot le plus récent, ou None si aucun."""
    snaps = _snapshots()
    if not snaps:
        return None
    return (datetime.now().timestamp() - snaps[0].stat().st_mtime) / 3600.0


def auto_snapshot_if_due(version: str = "0.1.0-dev", min_interval_hours: float = 20.0) -> Path | None:
    """Crée un snapshot si le dernier date de plus de `min_interval_hours` (ou aucun).
    Idempotent — sûr à appeler à chaque démarrage de l'app."""
    age = _last_snapshot_age_hours()
    if age is not None and age < min_interval_hours:
        return None
    return write_snapshot(version=version)


# ── Disque externe (B3a) — Linux ────────────────────────────────────────────
EXTERNAL_SUBDIR = "SelfFarm-Backups"


def _device_uuid(device: str) -> str | None:
    """UUID d'un device via /dev/disk/by-uuid (best-effort, pour identifier le disque)."""
    byuuid = Path("/dev/disk/by-uuid")
    if not byuuid.exists():
        return None
    try:
        dev_real = os.path.realpath(device)
        for link in byuuid.iterdir():
            if os.path.realpath(str(link)) == dev_real:
                return link.name
    except OSError:
        pass
    return None


def list_external_mounts() -> list[dict]:
    """Disques externes montés par l'utilisateur (Linux : /media/<user>/*, /run/media/<user>/*).
    Retourne [{path, label, device, free_bytes, total_bytes, uuid}]."""
    user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
    prefixes = tuple(p for p in (
        f"/media/{user}/", f"/run/media/{user}/", "/media/", "/run/media/",
    ) if p)
    out, seen = [], set()
    try:
        lines = Path("/proc/mounts").read_text().splitlines()
    except OSError:
        return out
    for line in lines:
        parts = line.split()
        if len(parts) < 2:
            continue
        device = parts[0]
        mountpoint = parts[1].replace("\\040", " ")
        if not any(mountpoint.startswith(p) for p in prefixes):
            continue
        if mountpoint in seen or not os.path.isdir(mountpoint):
            continue
        seen.add(mountpoint)
        try:
            u = shutil.disk_usage(mountpoint)
            free, total = u.free, u.total
        except OSError:
            free = total = 0
        out.append({
            "path": mountpoint,
            "label": os.path.basename(mountpoint.rstrip("/")) or mountpoint,
            "device": device,
            "free_bytes": free,
            "total_bytes": total,
            "uuid": _device_uuid(device),
            "writable": os.access(mountpoint, os.W_OK),
        })
    return out


def _ext_config_path() -> Path:
    return _db_path().parent / "backup_external.json"


def load_ext_config() -> dict:
    p = _ext_config_path()
    if p.exists():
        try:
            return json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_ext_config(cfg: dict) -> None:
    _ext_config_path().write_text(json.dumps(cfg, indent=2, ensure_ascii=False))


def backup_to_external(mount_path: str, version: str = "0.1.0-dev", keep: int = 30) -> dict:
    """Écrit un snapshot sur un disque externe monté (dans <mount>/SelfFarm-Backups/),
    applique la rétention, et mémorise la destination + la date du dernier backup externe."""
    mount = Path(mount_path)
    if not mount.is_dir():
        raise ValueError(f"Disque externe introuvable / démonté : {mount_path}")
    dest_dir = mount / EXTERNAL_SUBDIR
    dest_dir.mkdir(parents=True, exist_ok=True)

    zip_bytes, filename = make_backup(version=version)
    dest = dest_dir / filename
    dest.write_bytes(zip_bytes)

    # Rétention sur le disque externe
    snaps = sorted(dest_dir.glob("selffarm-backup-*.zip"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    for old in snaps[keep:]:
        try:
            old.unlink()
        except OSError:
            pass

    info = {m["path"]: m for m in list_external_mounts()}.get(mount_path, {})
    cfg = load_ext_config()
    cfg.update({
        "last_external_backup_utc": datetime.now(UTC).isoformat(),
        "last_external_path": str(dest),
        "disk_label": info.get("label"),
        "disk_uuid": info.get("uuid"),
    })
    save_ext_config(cfg)
    # Dépose la clé de coffre à côté (en clair) → permet de re-déchiffrer mobile/NAS
    # après une restauration depuis ce DD sur un PC neuf (filet de récup, cf Partie D).
    try:
        from self_backup.vault import has_vault_key, vault_key_b64
        if has_vault_key():
            (dest_dir / "vault.key").write_text(vault_key_b64())
    except Exception as e:  # noqa: BLE001
        log.warning("Dépôt vault.key sur le DD échoué (non bloquant) : %s", e)
    log.info("Backup externe écrit : %s (%d octets)", dest, len(zip_bytes))
    return {"path": str(dest), "size_bytes": len(zip_bytes),
            "disk_label": info.get("label"), "disk_uuid": info.get("uuid")}


# ── Restauration depuis un support : DD, plus tard mobile (Lot B) ────────────
def list_backups_on_mount(mount_path: str) -> list[dict]:
    """Backups présents sur un support (DD), tous ciphers confondus, plus récent d'abord."""
    from self_backup.vault import cipher_of_filename
    d = Path(mount_path) / EXTERNAL_SUBDIR
    if not d.is_dir():
        return []
    out = []
    for p in d.glob("selffarm-backup-*.zip*"):
        try:
            st = p.stat()
        except OSError:
            continue
        out.append({
            "name": p.name, "path": str(p), "size_bytes": st.st_size,
            "mtime": st.st_mtime, "cipher": cipher_of_filename(p.name),
        })
    return sorted(out, key=lambda x: x["mtime"], reverse=True)


def restore_from_path(path: str, confirm_rollback: bool = False) -> dict:
    """Restaure un backup depuis un fichier sur disque (déchiffre selon l'extension)."""
    from self_backup.vault import cipher_of_filename, decrypt_blob
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Backup introuvable : {path}")
    cipher = cipher_of_filename(p.name)
    if cipher == "unknown":
        raise ValueError(f"Format de backup non reconnu : {p.name}")
    return restore_from_bytes(decrypt_blob(p.read_bytes(), cipher), confirm_rollback=confirm_rollback)


def restore_from_support(mount_path: str, name: str, confirm_rollback: bool = False) -> dict:
    """Restaure un backup nommé depuis un support + récupère la clé de coffre déposée
    à côté (vault.key) → re-synchroniser mobile/NAS après un crash PC."""
    d = Path(mount_path) / EXTERNAL_SUBDIR
    # Garde-fou anti-traversée : nom de fichier simple uniquement.
    if Path(name).name != name:
        raise ValueError(f"Nom de backup invalide : {name}")
    target = d / name
    if not target.exists():
        raise FileNotFoundError(f"Backup introuvable sur le support : {name}")
    result = restore_from_path(str(target), confirm_rollback=confirm_rollback)
    if result.get("needs_confirmation"):
        return result  # rétro non confirmé : rien appliqué, pas de récupération de clé
    result["vault_recovered"] = False
    keyfile = d / "vault.key"
    if keyfile.exists():
        try:
            from self_backup.vault import import_vault_key
            import_vault_key(keyfile.read_text())
            result["vault_recovered"] = True
            log.info("Clé de coffre récupérée depuis le support : %s", keyfile)
        except Exception as e:  # noqa: BLE001
            log.warning("vault.key sur le support illisible : %s", e)
    return result


# ── Planification cron de la sauvegarde externe (B3b) ────────────────────────
CRON_MARKER = "# SELFFARM-AUTO-BACKUP"


def _crontab_read() -> list[str]:
    import subprocess
    try:
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True, check=False)
        return r.stdout.splitlines() if r.returncode == 0 else []
    except (FileNotFoundError, OSError):
        return []


def _crontab_write(lines: list[str]) -> None:
    import subprocess
    content = ("\n".join(l for l in lines if l.strip()).rstrip() + "\n") if lines else "\n"
    subprocess.run(["crontab", "-"], input=content, text=True, check=True)


def get_cron_schedule() -> dict | None:
    """Planif SELFFARM existante : {minute, hour, dow} ; sinon None."""
    for line in _crontab_read():
        if CRON_MARKER in line:
            p = line.split()
            try:
                return {"minute": int(p[0]), "hour": int(p[1]), "dow": p[4]}
            except (IndexError, ValueError):
                return {"raw": line}
    return None


def set_cron_schedule(hour: int, dow: str = "*", minute: int = 0) -> str:
    """Pose/remplace la ligne cron de sauvegarde auto vers le DD.
    dow : '*' (tous les jours) ou '0'..'6' (0 = dimanche). Retourne la ligne posée."""
    import sys
    python = sys.executable
    base_dir = Path(__file__).resolve().parents[2]  # racine du projet
    data_dir = os.environ.get("SELFFARM_DATA_DIR", str(Path.home() / ".selffarm"))
    log_path = str(Path(data_dir) / "autobackup.log")
    cmd = (f"cd {base_dir} && SELFFARM_DATA_DIR={data_dir} PYTHONPATH=modules:. "
           f"{python} -m self_backup.autobackup >> {log_path} 2>&1")
    cron_line = f"{int(minute)} {int(hour)} * * {dow}  {cmd}  {CRON_MARKER}"
    lines = [l for l in _crontab_read() if CRON_MARKER not in l]
    lines.append(cron_line)
    _crontab_write(lines)
    log.info("Cron sauvegarde auto posé : %s", cron_line)
    return cron_line


def clear_cron_schedule() -> None:
    """Retire la planif SELFFARM du crontab (laisse le reste intact)."""
    lines = [l for l in _crontab_read() if CRON_MARKER not in l]
    _crontab_write(lines)
    log.info("Cron sauvegarde auto retiré")


# ── Santé des sauvegardes + rappel d'oubli (B3c) ─────────────────────────────
def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return None


def backup_health(late_after_days: float = 2.0) -> dict:
    """État des sauvegardes externes/distantes pour le rappel d'oubli (B3c).
    Une cible « activée » est en alerte si sa dernière sauvegarde a échoué (manquée)
    ou date de plus de `late_after_days` jours (ou n'a jamais eu lieu)."""
    now = datetime.now(UTC)

    def _target(enabled, last_ok_s, last_missed_s, label, extra=None):
        last_ok = _parse_iso(last_ok_s)
        last_missed = _parse_iso(last_missed_s)
        age_days = (now - last_ok).total_seconds() / 86400.0 if last_ok else None
        missed = bool(last_missed and (last_ok is None or last_missed > last_ok))
        late = bool(enabled and (age_days is None or age_days > late_after_days))
        return {
            "enabled": bool(enabled), "last_ok_utc": last_ok_s, "age_days": age_days,
            "missed": missed, "late": late, "alert": bool(enabled and (missed or late)),
            "label": label, **(extra or {}),
        }

    ext = load_ext_config()
    external = _target(
        enabled=bool(ext.get("disk_uuid")),
        last_ok_s=ext.get("last_external_backup_utc"),
        last_missed_s=ext.get("last_missed_utc"),
        label=ext.get("disk_label") or "disque externe",
    )

    try:
        from self_backup.remote import load_sftp_config
        sc = load_sftp_config()
    except Exception:  # noqa: BLE001 — sauvegarde distante facultative : on dégrade sans bloquer
        sc = {}
    sftp = _target(
        enabled=bool(sc.get("enabled")),
        last_ok_s=sc.get("last_sftp_backup_utc"),
        last_missed_s=sc.get("last_sftp_missed_utc"),
        label=(f"{sc.get('username')}@{sc.get('host')}" if sc.get("host") else "serveur distant"),
        extra={"error": sc.get("last_sftp_error")},
    )

    messages = []
    for t, kind in ((external, "disque externe"), (sftp, "serveur distant")):
        if not t["alert"]:
            continue
        if t["age_days"] is None:
            messages.append(f"Aucune sauvegarde sur {kind} ({t['label']}) pour l'instant.")
        elif t["missed"]:
            messages.append(f"Dernière sauvegarde {kind} ({t['label']}) manquée — cible injoignable.")
        else:
            messages.append(f"Sauvegarde {kind} ({t['label']}) en retard ({t['age_days']:.0f} j).")

    return {"external": external, "sftp": sftp,
            "alert": external["alert"] or sftp["alert"], "messages": messages}


def retry_missed_backups(version: str = "0.1.0-dev", targets: tuple = ("external", "sftp")) -> dict:
    """Retente les cibles activées en retard/manquées si elles sont de nouveau
    joignables. `targets` limite le périmètre — le watcher ne retente que le DD pour
    ne PAS marteler le serveur distant (anti-bruteforce). Best-effort, non bloquant."""
    health = backup_health()
    out = {"external": None, "sftp": None}

    if "external" in targets and health["external"]["alert"]:
        uuid = load_ext_config().get("disk_uuid")
        m = next((x for x in list_external_mounts()
                  if x.get("uuid") == uuid and x.get("writable")), None)
        if m:
            try:
                r = backup_to_external(m["path"], version=version)
                out["external"] = r.get("path")
                log.info("Rappel : sauvegarde externe rattrapée → %s", r.get("path"))
            except Exception as e:  # noqa: BLE001
                log.warning("Rappel externe : échec retry : %s", e)

    if "sftp" in targets and health["sftp"]["alert"]:
        try:
            from self_backup.remote import backup_to_sftp
            r = backup_to_sftp(version=version)
            out["sftp"] = r.get("path")
            log.info("Rappel : sauvegarde distante rattrapée → %s", r.get("path"))
        except Exception as e:  # noqa: BLE001
            log.warning("Rappel distant : échec retry (cible injoignable ?) : %s", e)

    return out


def backup_watcher(version: str = "0.1.0-dev", interval_s: float = 45.0) -> None:
    """Boucle de fond (polish B3c) : retry initial (DD + SFTP) au démarrage, puis
    surveille le rebranchement du DD pour rattraper À CHAUD une sauvegarde manquée,
    sans redémarrer l'app. Le SFTP n'est PAS retenté en boucle (réseau → on évite de
    marteler le serveur distant ; il reste couvert par le retry initial + le cron)."""
    import time
    interval_s = float(os.environ.get("SELFFARM_BACKUP_WATCH_INTERVAL", interval_s))
    wlog = logging.getLogger("self_backup.watcher")
    try:
        retry_missed_backups(version=version)
    except Exception as e:  # noqa: BLE001
        wlog.warning("retry initial : %s", e)
    while True:
        time.sleep(interval_s)
        try:
            if backup_health()["external"]["alert"]:
                r = retry_missed_backups(version=version, targets=("external",))
                if r.get("external"):
                    wlog.info("DD rebranché → sauvegarde rattrapée à chaud : %s", r["external"])
            # Réplication continue du ledger (outbox) vers les supports présents (Partie E)
            try:
                from self_backup.replicator import replicate_all
                replicate_all()
            except Exception as e:  # noqa: BLE001
                wlog.warning("réplication ledger : %s", e)
        except Exception as e:  # noqa: BLE001
            wlog.warning("watcher : %s", e)
