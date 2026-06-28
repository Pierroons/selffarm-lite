"""SelfPOS V0.3 — CRUD chargement camion.

Le chargement = produits prévus pour un marché (ponctuel ou collectif).
Quantité optionnelle (NULL = juste coché, pas de comptage).
"""

from __future__ import annotations

import logging
from typing import Any

from self_agri_book.storage import _conn, init_db

log = logging.getLogger(__name__)


def list_chargement(session_id: int) -> list[dict[str, Any]]:
    init_db()
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM pos_chargement WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def add_chargement_line(
    session_id: int,
    produit_id: int | None,
    produit_nom: str,
    unite: str = "pièce",
    quantite_chargee: float | None = None,
) -> dict[str, Any]:
    """Ajoute une ligne de chargement à une session."""
    init_db()
    if not produit_nom or not produit_nom.strip():
        raise ValueError("produit_nom requis")
    if quantite_chargee is not None and quantite_chargee < 0:
        raise ValueError("quantite_chargee doit être >= 0")
    with _conn() as c:
        cur = c.execute(
            """
            INSERT INTO pos_chargement (session_id, produit_id, produit_nom, unite, quantite_chargee)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, produit_id, produit_nom.strip(), unite, quantite_chargee),
        )
        new_id = cur.lastrowid
        row = c.execute("SELECT * FROM pos_chargement WHERE id = ?", (new_id,)).fetchone()
    return dict(row)


def replace_chargement(session_id: int, lignes: list[dict[str, Any]]) -> int:
    """Remplace tout le chargement d'une session par une nouvelle liste. Retourne nb créés."""
    init_db()
    with _conn() as c:
        c.execute("DELETE FROM pos_chargement WHERE session_id = ?", (session_id,))
        nb = 0
        for ligne in lignes:
            nom = (ligne.get("produit_nom") or "").strip()
            if not nom:
                continue
            qte = ligne.get("quantite_chargee")
            try:
                qte = float(qte) if qte is not None else None
            except (TypeError, ValueError):
                qte = None
            c.execute(
                """
                INSERT INTO pos_chargement (session_id, produit_id, produit_nom, unite, quantite_chargee)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, ligne.get("produit_id"), nom, ligne.get("unite") or "pièce", qte),
            )
            nb += 1
    log.info("Chargement session #%s remplacé : %d lignes", session_id, nb)
    return nb


def delete_chargement_line(chargement_id: int) -> bool:
    init_db()
    with _conn() as c:
        cur = c.execute("DELETE FROM pos_chargement WHERE id = ?", (chargement_id,))
        return cur.rowcount > 0
