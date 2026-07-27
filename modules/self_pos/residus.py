"""SelfPOS V0.3 — Résidus de marché (stock / invendu / transferé / consommé hors marché).

Une ligne par produit avec quantité restante.
- `stock` : gardé pour un futur marché → rappel hebdo si > N jours
- `invendu` : destination (poules, compost, don, poubelle, garde_maison, autre)
- `transfere` : status terminal quand la ligne est consommée par un autre marché
- `consomme_hors_marche` : vente AMAP, panier, voisin, etc.
"""

from __future__ import annotations

import logging
from typing import Any

from self_agri_book.storage import _conn, init_db

log = logging.getLogger(__name__)


VALID_STATUS = {"stock", "invendu", "transfere", "consomme_hors_marche"}
VALID_DESTINATIONS = {"poules", "compost", "don", "poubelle", "garde_maison", "autre"}


def list_residus(session_id: int | None = None, status: str | None = None,
                 active_only: bool = True) -> list[dict[str, Any]]:
    init_db()
    sql = "SELECT * FROM pos_residu_marche WHERE 1=1"
    params: list[Any] = []
    if session_id is not None:
        sql += " AND session_id = ?"
        params.append(session_id)
    if status is not None:
        sql += " AND status = ?"
        params.append(status)
    if active_only:
        sql += " AND archive = 0"
    sql += " ORDER BY created_at DESC, id DESC"
    with _conn() as c:
        rows = c.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def list_stock_a_reviewer(jours: int = 7) -> list[dict[str, Any]]:
    """Lignes status='stock' active dont la dernière revue date de > jours jours."""
    init_db()
    with _conn() as c:
        rows = c.execute(
            """
            SELECT * FROM pos_residu_marche
            WHERE status = 'stock'
              AND archive = 0
              AND julianday('now') - julianday(derniere_revue_at) > ?
            ORDER BY derniere_revue_at ASC
            """,
            (jours,),
        ).fetchall()
    return [dict(r) for r in rows]


def add_residu(
    session_id: int,
    produit_nom: str,
    quantite: float,
    status: str,
    produit_id: int | None = None,
    unite: str = "pièce",
    destination: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    init_db()
    if not produit_nom or not produit_nom.strip():
        raise ValueError("produit_nom requis")
    if quantite < 0:
        raise ValueError("quantite doit être >= 0")
    if status not in VALID_STATUS:
        raise ValueError(f"status '{status}' invalide — {VALID_STATUS}")
    if status == "invendu" and destination and destination not in VALID_DESTINATIONS:
        raise ValueError(f"destination '{destination}' invalide — {VALID_DESTINATIONS}")
    with _conn() as c:
        cur = c.execute(
            """
            INSERT INTO pos_residu_marche
                (session_id, produit_id, produit_nom, unite, quantite, status, destination, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, produit_id, produit_nom.strip(), unite, quantite, status, destination, notes),
        )
        new_id = cur.lastrowid
        row = c.execute("SELECT * FROM pos_residu_marche WHERE id = ?", (new_id,)).fetchone()
    log.info("Résidu #%s session=%s produit=%s qte=%s status=%s", new_id, session_id, produit_nom, quantite, status)
    return dict(row)


def replace_residus(session_id: int, residus: list[dict[str, Any]]) -> int:
    """Remplace tous les résidus d'une session par une nouvelle liste. Retourne nb créés."""
    init_db()
    with _conn() as c:
        c.execute("DELETE FROM pos_residu_marche WHERE session_id = ? AND archive = 0", (session_id,))
        nb = 0
        for r in residus:
            try:
                qte = float(r.get("quantite") or 0)
            except (TypeError, ValueError):
                continue
            if qte < 0:
                continue
            status = r.get("status")
            if status not in VALID_STATUS:
                continue
            nom = (r.get("produit_nom") or "").strip()
            if not nom:
                continue
            destination = r.get("destination")
            if destination and destination not in VALID_DESTINATIONS:
                destination = "autre"
            c.execute(
                """
                INSERT INTO pos_residu_marche
                    (session_id, produit_id, produit_nom, unite, quantite, status, destination, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, r.get("produit_id"), nom, r.get("unite") or "pièce",
                 qte, status, destination, r.get("notes")),
            )
            nb += 1
    log.info("Résidus session #%s remplacés : %d lignes", session_id, nb)
    return nb


def update_residu_status(residu_id: int, new_status: str, destination: str | None = None,
                         notes: str | None = None) -> dict[str, Any] | None:
    """Reclasse un résidu (typiquement stock → invendu lors d'une revue hebdo)."""
    init_db()
    if new_status not in VALID_STATUS:
        raise ValueError(f"status '{new_status}' invalide")
    with _conn() as c:
        cur = c.execute(
            """
            UPDATE pos_residu_marche
            SET status = ?, destination = ?, notes = COALESCE(?, notes),
                derniere_revue_at = datetime('now'),
                updated_at = datetime('now'),
                archive = CASE WHEN ? IN ('invendu','transfere','consomme_hors_marche') THEN 1 ELSE 0 END
            WHERE id = ?
            """,
            (new_status, destination, notes, new_status, residu_id),
        )
        if cur.rowcount == 0:
            return None
        row = c.execute("SELECT * FROM pos_residu_marche WHERE id = ?", (residu_id,)).fetchone()
    return dict(row) if row else None


def confirm_stock_revue(residu_id: int) -> bool:
    """Refresh derniere_revue_at — l'agri confirme que la ligne est toujours en stock OK."""
    init_db()
    with _conn() as c:
        cur = c.execute(
            "UPDATE pos_residu_marche SET derniere_revue_at = datetime('now'), updated_at = datetime('now') WHERE id = ? AND status = 'stock' AND archive = 0",
            (residu_id,),
        )
        return cur.rowcount > 0
