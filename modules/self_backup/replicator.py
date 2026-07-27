"""self_backup.replicator — réplication continue du ledger (outbox) vers les supports.

Consomme `self_agri_book.outbox.pending_for(support_id)` → écrit les événements en
NDJSON (append-only) sur le support → `mark_replicated`. Opportuniste : ne pousse
QUE vers les supports présents, et seulement s'il y a du nouveau (pas de connexion
inutile). cf Partie E du plan (log shipping du ledger).

Le ledger est écrit EN CLAIR sur le DD (déjà filet de récup en clair) et sur le NAS
perso de Pierroons. Le chiffrement par batch pour le cloud = étape 5.
"""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("self_backup.replicator")

LEDGER_SUBDIR = "SelfFarm-Ledger"
LEDGER_FILE = "ledger.ndjson"


def _push(support_id: str, write_fn) -> dict:
    """Squelette commun : récupère le pending du support, écrit, marque répliqué.
    `write_fn(ndjson_str)` n'est appelé QUE s'il y a des événements à pousser."""
    from self_agri_book.outbox import mark_replicated, pending_for, to_ndjson
    pending = pending_for(support_id)
    if not pending:
        return {"support": support_id, "pushed": 0}
    write_fn(to_ndjson(pending))
    for e in pending:
        mark_replicated(e["seq"], support_id)
    log.info("Ledger répliqué : %d événement(s) → %s", len(pending), support_id)
    return {"support": support_id, "pushed": len(pending), "last_seq": pending[-1]["seq"]}


def replicate_to_mount(mount_path: str, uuid: str) -> dict:
    """Append les événements non répliqués du ledger sur un DD monté (en clair)."""
    d = Path(mount_path) / LEDGER_SUBDIR

    def _write(ndjson: str):
        d.mkdir(parents=True, exist_ok=True)
        with open(d / LEDGER_FILE, "a", encoding="utf-8") as f:
            f.write(ndjson)

    return _push(f"dd-{uuid}", _write)


def replicate_to_sftp(cfg: dict) -> dict:
    """Append les événements non répliqués vers le serveur SFTP (NAS perso, en clair)."""
    from self_backup.remote import _connect, _sftp_makedirs
    remote_dir = (cfg.get("remote_dir") or "").rstrip("/") + "/" + LEDGER_SUBDIR

    def _write(ndjson: str):
        ssh, sftp = _connect(cfg)
        try:
            _sftp_makedirs(sftp, remote_dir)
            with sftp.open(remote_dir + "/" + LEDGER_FILE, "a") as fh:
                fh.write(ndjson.encode("utf-8"))
        finally:
            sftp.close()
            ssh.close()

    return _push(f"sftp-{cfg.get('host')}", _write)


def replicate_all() -> dict:
    """Réplique le ledger vers tous les supports PRÉSENTS (DD mémorisé + SFTP activé).
    Best-effort : un support injoignable n'empêche pas les autres."""
    from self_backup import list_external_mounts, load_ext_config
    from self_backup.remote import load_sftp_config
    out: dict = {}

    uuid = load_ext_config().get("disk_uuid")
    if uuid:
        m = next((x for x in list_external_mounts()
                  if x.get("uuid") == uuid and x.get("writable")), None)
        if m:
            try:
                out["dd"] = replicate_to_mount(m["path"], uuid)
            except Exception as e:  # noqa: BLE001
                log.warning("Réplication DD échouée : %s", e)

    sftp_cfg = load_sftp_config()
    if sftp_cfg.get("enabled"):
        try:
            out["sftp"] = replicate_to_sftp(sftp_cfg)
        except Exception as e:  # noqa: BLE001
            log.warning("Réplication SFTP échouée : %s", e)

    return out
