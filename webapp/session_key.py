"""Secret qui signe le cookie de session (wizard d'onboarding).

`SELFFARM_SESSION_SECRET` s'il est posé. Sinon une clé tirée au premier
démarrage et gardée à côté de la base (`session.key`, perms 600) : chaque
installation a la sienne, et l'image Docker démarre sans rien à configurer.
Si la clé ne peut être ni lue ni créée, l'application refuse de démarrer.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from self_backup import _db_path
from self_backup.vault import write_key_file

SESSION_KEY_FILENAME = "session.key"


def session_key_path() -> Path:
    return _db_path().parent / SESSION_KEY_FILENAME


def session_secret() -> str:
    env = os.environ.get("SELFFARM_SESSION_SECRET")
    if env:
        return env
    p = session_key_path()
    try:
        if not p.exists():
            write_key_file(p, secrets.token_hex(32).encode("ascii"))
        key = p.read_text(encoding="ascii").strip()
    except OSError as e:
        raise RuntimeError(
            f"Clé de session impossible à lire ou à créer ({p} : {e}). "
            "Pose SELFFARM_SESSION_SECRET, ou rends ce dossier inscriptible."
        ) from e
    if not key:
        raise RuntimeError(f"Clé de session vide : {p}. Supprime-la, elle sera régénérée.")
    return key

