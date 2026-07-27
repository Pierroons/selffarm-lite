"""self_agri_book.outbox — journal append-only des événements immuables du ledger.

À chaque écriture/facture (point central `save_ecriture`), un événement est appendé
ici. Le réplicateur (self_backup, lot suivant) pousse ces événements vers les supports
présents (DD/NAS/mobile) → sauvegarde continue du ledger (RPO≈0). cf Partie E du plan.

Append-only : on n'UPDATE/DELETE JAMAIS un événement ; seul `replicated_to` s'enrichit.
La `seq` (auto-incrément monotone) sert aussi de compteur de génération anti-rétrogradage.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from self_agri_book.storage import _conn, init_db

log = logging.getLogger("self_agri_book.outbox")


def append_event(
    event_type: str,
    payload: dict,
    hash_data: str,
    ecriture_id: int | None = None,
    numero_piece: str | None = None,
) -> int:
    """Append un événement immuable dans le journal. Retourne sa `seq`."""
    init_db()
    created_utc = datetime.now(UTC).isoformat()
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO ledger_outbox
                 (created_utc, event_type, ecriture_id, numero_piece, hash_data, payload_json, replicated_to)
               VALUES (?, ?, ?, ?, ?, ?, '[]')""",
            (created_utc, event_type, ecriture_id, numero_piece, hash_data, payload_json),
        )
        seq = cur.lastrowid
    log.info("Outbox +1 : seq=%d type=%s piece=%s hash=%s",
             seq, event_type, numero_piece, (hash_data or "")[:12])
    return seq


def last_seq() -> int:
    """Plus haute `seq` du journal = compteur de génération monotone du ledger."""
    init_db()
    with _conn() as c:
        row = c.execute("SELECT MAX(seq) AS m FROM ledger_outbox").fetchone()
    return int(row["m"]) if row and row["m"] is not None else 0


def count() -> int:
    """Nombre total d'événements dans le journal."""
    init_db()
    with _conn() as c:
        row = c.execute("SELECT COUNT(*) AS n FROM ledger_outbox").fetchone()
    return int(row["n"]) if row else 0


def pending_for(support_id: str, limit: int = 1000) -> list[dict]:
    """Événements pas encore répliqués sur `support_id` (ordre `seq` croissant)."""
    init_db()
    out: list[dict] = []
    with _conn() as c:
        rows = c.execute(
            "SELECT seq, created_utc, event_type, ecriture_id, numero_piece, "
            "       hash_data, payload_json, replicated_to "
            "FROM ledger_outbox ORDER BY seq ASC"
        ).fetchall()
    for r in rows:
        reps = json.loads(r["replicated_to"] or "[]")
        if support_id in reps:
            continue
        out.append({
            "seq": r["seq"],
            "created_utc": r["created_utc"],
            "event_type": r["event_type"],
            "ecriture_id": r["ecriture_id"],
            "numero_piece": r["numero_piece"],
            "hash_data": r["hash_data"],
            "payload": json.loads(r["payload_json"]),
        })
        if len(out) >= limit:
            break
    return out


def mark_replicated(seq: int, support_id: str) -> None:
    """Marque un événement comme répliqué sur `support_id` (enrichit la liste, append-only)."""
    init_db()
    with _conn() as c:
        row = c.execute("SELECT replicated_to FROM ledger_outbox WHERE seq=?", (seq,)).fetchone()
        if not row:
            return
        reps = json.loads(row["replicated_to"] or "[]")
        if support_id not in reps:
            reps.append(support_id)
            c.execute("UPDATE ledger_outbox SET replicated_to=? WHERE seq=?",
                      (json.dumps(reps), seq))


def to_ndjson(events: list[dict]) -> str:
    """Sérialise des événements en NDJSON (1 ligne = 1 événement) pour la réplication."""
    return "".join(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n" for e in events)
