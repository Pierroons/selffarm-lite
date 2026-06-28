"""self_pos.devices — appairage des supports mobiles (coffre de sauvegarde).

Modèle (Partie D du plan backup) : à l'appairage (scan d'un QR portant un jeton
one-time), le PC confie au tel la clé de coffre + un identifiant d'appareil. Le tel
devient un « support de confiance » : il reçoit des backups chiffrés et peut les
rendre à un PC (neuf ou non) pour restauration. Zéro clé à gérer pour l'utilisateur.

- Jetons d'appairage : one-time, en mémoire, TTL court (anti-rejeu).
- Registre des appareils appairés : persisté (`pos_devices.json` dans le data dir).
"""
from __future__ import annotations

import json
import secrets
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _data_dir() -> Path:
    from self_backup import _db_path
    return _db_path().parent


def _devices_path() -> Path:
    return _data_dir() / "pos_devices.json"


# ── Jetons d'appairage one-time (mémoire) ─────────────────────────────────────
PAIR_TTL_S = 300  # 5 minutes
_PAIR_TOKENS: dict[str, float] = {}  # token → epoch d'expiration


def new_pair_token(ttl_s: float = PAIR_TTL_S) -> str:
    """Crée un jeton d'appairage à durée de vie courte (à encoder dans le QR)."""
    now = time.time()
    for k in [k for k, exp in _PAIR_TOKENS.items() if exp < now]:
        _PAIR_TOKENS.pop(k, None)
    tok = secrets.token_urlsafe(24)
    _PAIR_TOKENS[tok] = now + ttl_s
    return tok


def consume_pair_token(tok: str) -> bool:
    """Valide ET consomme un jeton (one-time). False si inconnu/expiré/déjà utilisé."""
    if not tok:
        return False
    exp = _PAIR_TOKENS.pop(tok, None)
    return exp is not None and exp >= time.time()


# ── Registre des appareils appairés (persisté) ────────────────────────────────
def load_devices() -> dict:
    p = _devices_path()
    if p.exists():
        try:
            return json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_devices(d: dict) -> None:
    _devices_path().write_text(json.dumps(d, indent=2, ensure_ascii=False))


def register_device(label: str = "") -> str:
    """Enregistre un nouvel appareil appairé, retourne son device_id."""
    device_id = uuid.uuid4().hex
    d = load_devices()
    d[device_id] = {
        "paired_at": datetime.now(timezone.utc).isoformat(),
        "label": (label or "Téléphone").strip()[:60],
        "last_seen": None,
    }
    save_devices(d)
    return device_id


def touch_device(device_id: str) -> bool:
    """Met à jour last_seen d'un appareil connu. False si inconnu."""
    d = load_devices()
    if device_id not in d:
        return False
    d[device_id]["last_seen"] = datetime.now(timezone.utc).isoformat()
    save_devices(d)
    return True
