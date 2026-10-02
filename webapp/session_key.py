"""Secret qui signe le cookie de session (wizard d'onboarding).

`SELFFARM_SESSION_SECRET` s'il est posé. Sinon une clé tirée au premier
démarrage et gardée à côté de la base (`session.key`, perms 600) : chaque
installation a la sienne, et l'image Docker démarre sans rien à configurer.
Si la clé ne peut être ni lue ni créée, l'application refuse de démarrer.
"""
from __future__ import annotations

import os
import secrets
import tempfile
from pathlib import Path

from self_backup import _db_path

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
            _create(p)
        key = p.read_text(encoding="ascii").strip()
    except OSError as e:
        raise RuntimeError(
            f"Clé de session impossible à lire ou à créer ({p} : {e}). "
            "Pose SELFFARM_SESSION_SECRET, ou rends ce dossier inscriptible."
        ) from e
    if not key:
        raise RuntimeError(f"Clé de session vide : {p}. Supprime-la, elle sera régénérée.")
    return key


def _create(p: Path) -> None:
    """Écrit la clé dans un fichier temporaire (600), puis la lie sous son nom.
    Le lien échoue si un autre worker a gagné la course : sa clé vaut pour tous,
    et aucun ne lit un fichier à moitié écrit."""
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=f".{p.name}.")
    try:
        with os.fdopen(fd, "w", encoding="ascii") as f:
            f.write(secrets.token_hex(32))
        try:
            os.link(tmp, p)
        except FileExistsError:
            pass
    finally:
        os.unlink(tmp)
