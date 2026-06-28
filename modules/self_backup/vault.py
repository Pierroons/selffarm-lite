"""self_backup.vault — clé de coffre symétrique (Fernet), gérée par le PC.

Principe (Partie D du plan backup) : zéro friction utilisateur. Le PC génère et
stocke une clé localement, l'utilise pour chiffrer les copies mobile/NAS. La clé
voyage avec le DD externe (déposée en clair) pour permettre une récupération
« from scratch » sur un PC neuf — le paysan n'a JAMAIS de clé à gérer ni à retenir.

Modèle de menace faible assumé : le chiffrement empêche la lecture triviale
(autre app, fichier baladé, sauvegarde cloud du tel), pas un vol ciblé du support
déverrouillé. cf [[project_selffarm_modes_modulaires]].

Trois « ciphers » coexistent selon la destination :
- ``none``  : DD externe (ZIP en clair) — filet de récup zéro-clé
- ``vault`` : mobile + NAS produit (Fernet, clé auto)
- ``gpg``   : NAS, option avancée (clé asymétrique de l'utilisateur)
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from self_backup import _db_path

log = logging.getLogger("self_backup.vault")

VAULT_KEY_FILENAME = "vault.key"

# Extension de fichier ↔ cipher (sert au listing/restore multi-support)
CIPHER_EXT = {"none": ".zip", "vault": ".zip.vault", "gpg": ".zip.gpg"}


def _vault_key_path() -> Path:
    return _db_path().parent / VAULT_KEY_FILENAME


def has_vault_key() -> bool:
    return _vault_key_path().exists()


def get_or_create_vault_key() -> bytes:
    """Clé Fernet (base64url, 44 octets). Générée + persistée au 1er appel (perms 600)."""
    from cryptography.fernet import Fernet

    p = _vault_key_path()
    if p.exists():
        return p.read_bytes().strip()
    key = Fernet.generate_key()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(key)
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    log.info("Clé de coffre générée : %s", p)
    return key


def vault_key_b64() -> str:
    """Clé de coffre en texte (à transmettre au support de confiance / déposer sur le DD)."""
    return get_or_create_vault_key().decode("ascii")


def import_vault_key(key_b64) -> None:
    """Réinjecte une clé reçue d'un support (restauration). Valide le format avant d'écrire."""
    from cryptography.fernet import Fernet

    key = key_b64.strip().encode("ascii") if isinstance(key_b64, str) else key_b64.strip()
    Fernet(key)  # lève ValueError si le format est invalide
    p = _vault_key_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(key)
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    log.info("Clé de coffre importée : %s", p)


def encrypt(data: bytes) -> bytes:
    """Chiffre avec la clé de coffre (génère la clé si absente)."""
    from cryptography.fernet import Fernet

    return Fernet(get_or_create_vault_key()).encrypt(data)


def decrypt(token: bytes) -> bytes:
    """Déchiffre avec la clé de coffre. Lève InvalidToken si clé absente/mauvaise."""
    from cryptography.fernet import Fernet

    return Fernet(get_or_create_vault_key()).decrypt(token)


# ── Dispatcher cipher (utilisé par les destinations de backup, lots B→E) ──────
def cipher_of_filename(name: str) -> str:
    """Devine le cipher d'un fichier de backup d'après son extension."""
    if name.endswith(".zip.vault"):
        return "vault"
    if name.endswith(".zip.gpg"):
        return "gpg"
    if name.endswith(".zip"):
        return "none"
    return "unknown"


def encrypt_for(data: bytes, cipher: str, gpg_recipient: str = "") -> bytes:
    """Chiffre `data` selon le cipher demandé (none = passthrough)."""
    if cipher == "none":
        return data
    if cipher == "vault":
        return encrypt(data)
    if cipher == "gpg":
        from self_backup.remote import _encrypt_gpg
        return _encrypt_gpg(data, gpg_recipient)
    raise ValueError(f"Cipher inconnu : {cipher}")


def decrypt_blob(data: bytes, cipher: str) -> bytes:
    """Déchiffre un blob selon son cipher (none = passthrough ; gpg = délégué à GnuPG)."""
    if cipher == "none":
        return data
    if cipher == "vault":
        return decrypt(data)
    if cipher == "gpg":
        import subprocess
        proc = subprocess.run(
            ["gpg", "--batch", "--yes", "--decrypt"],
            input=data, capture_output=True,
        )
        if proc.returncode != 0 or not proc.stdout:
            err = proc.stderr.decode("utf-8", "replace").strip()
            raise RuntimeError(f"Déchiffrement GPG échoué : {err}")
        return proc.stdout
    raise ValueError(f"Cipher inconnu : {cipher}")
