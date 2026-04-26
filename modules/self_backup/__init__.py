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
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("self_backup")

MANIFEST_VERSION = 1


def _db_path() -> Path:
    """Chemin courant de la DB compta (même résolution que self_agri_book.storage)."""
    default = Path.home() / ".selffarm" / "compta.db"
    return Path(os.environ.get("SELFFARM_COMPTA_DB", str(default)))


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
    now = datetime.now(timezone.utc)

    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "selffarm_version": version,
        "exported_at_utc": now.isoformat(),
        "exported_at_local": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "db_filename": "compta.db",
        "db_size_bytes": db_size,
        "db_sha256": sha256,
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


def restore_from_bytes(zip_bytes: bytes) -> dict:
    """Restaure la DB depuis un ZIP archive précédemment exporté.

    Sauvegarde l'ancienne DB en .bak-YYYYMMDD-HHMMSS avant de l'écraser.
    Vérifie le SHA256 du fichier extrait contre le manifest.

    Retourne un dict {restored, manifest, old_backup_path, sha256_match}.
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

        db_bytes = zf.read("compta.db")

    sha256_actual = hashlib.sha256(db_bytes).hexdigest()
    sha256_expected = manifest.get("db_sha256")
    sha256_match = (sha256_actual == sha256_expected) if sha256_expected else None

    # Backup de l'existant
    old_backup_path: Optional[Path] = None
    if target.exists():
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        old_backup_path = target.with_suffix(f".db.bak-{ts}")
        shutil.copy2(target, old_backup_path)
        log.warning("Ancien %s sauvegardé en %s", target, old_backup_path)

    # Écrit la nouvelle DB
    with open(target, "wb") as f:
        f.write(db_bytes)

    log.info(
        "Restore terminé : %d écritures attendues, sha256 %s, match=%s",
        manifest.get("stats", {}).get("nb_ecritures", "?"),
        sha256_actual[:12], sha256_match,
    )
    return {
        "restored": True,
        "manifest": manifest,
        "old_backup_path": str(old_backup_path) if old_backup_path else None,
        "sha256_match": sha256_match,
        "target_path": str(target),
    }
