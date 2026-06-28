"""SelfPOS V0.3 — Points de vente collectifs (magasins producteurs).

Modèle métier différent du marché ponctuel :
- L'agri dépose ses produits chez le magasin
- Le magasin tient la caisse (rotation producteurs ou salarié)
- Récap périodique (semaine/mois) avec ventes constatées
- Compta selon convention :
  - depot_vente : magasin commissionne, agri reste propriétaire stock
  - achat_direct : magasin achète au prix grossiste, revend à son prix

Pas de PWA mobile pour ce flux — tout côté SelfFarm Windows.
"""

from __future__ import annotations

import logging
from typing import Any

from self_agri_book.storage import _conn, init_db

log = logging.getLogger(__name__)

CONVENTION_VALUES = {"depot_vente", "achat_direct"}


def list_collectifs(active_only: bool = True) -> list[dict[str, Any]]:
    init_db()
    sql = "SELECT * FROM pos_point_vente_collectif"
    if active_only:
        sql += " WHERE active = 1"
    sql += " ORDER BY nom"
    with _conn() as c:
        rows = c.execute(sql).fetchall()
    return [dict(r) for r in rows]


def get_collectif(collectif_id: int) -> dict[str, Any] | None:
    init_db()
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM pos_point_vente_collectif WHERE id = ?",
            (collectif_id,),
        ).fetchone()
    return dict(row) if row else None


def save_collectif(data: dict[str, Any]) -> dict[str, Any]:
    """UPSERT magasin collectif."""
    init_db()
    if not data.get("nom"):
        raise ValueError("nom requis")
    convention = data.get("convention", "depot_vente")
    if convention not in CONVENTION_VALUES:
        raise ValueError(f"convention '{convention}' invalide — {CONVENTION_VALUES}")
    commission = data.get("commission_pct")
    if commission is not None:
        try:
            commission = float(commission)
            if commission < 0 or commission > 100:
                raise ValueError("commission_pct doit être entre 0 et 100")
        except (TypeError, ValueError) as e:
            raise ValueError(f"commission_pct invalide : {e}")

    collectif_id = data.get("id")
    with _conn() as c:
        if collectif_id:
            c.execute(
                """
                UPDATE pos_point_vente_collectif
                SET nom = ?, adresse = ?, convention = ?, commission_pct = ?,
                    jour_recap = ?, contact = ?, notes = ?, active = ?,
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (data["nom"].strip(), data.get("adresse"), convention, commission,
                 data.get("jour_recap"), data.get("contact"), data.get("notes"),
                 1 if data.get("active", True) else 0, collectif_id),
            )
            log.info("Collectif #%s mis à jour : %s", collectif_id, data["nom"])
        else:
            cur = c.execute(
                """
                INSERT INTO pos_point_vente_collectif
                    (nom, adresse, convention, commission_pct, jour_recap, contact, notes, active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (data["nom"].strip(), data.get("adresse"), convention, commission,
                 data.get("jour_recap"), data.get("contact"), data.get("notes"),
                 1 if data.get("active", True) else 0),
            )
            collectif_id = cur.lastrowid
            log.info("Collectif créé #%s : %s", collectif_id, data["nom"])
    return get_collectif(collectif_id)


def deactivate_collectif(collectif_id: int) -> bool:
    init_db()
    with _conn() as c:
        cur = c.execute(
            "UPDATE pos_point_vente_collectif SET active = 0, updated_at = datetime('now') WHERE id = ?",
            (collectif_id,),
        )
        return cur.rowcount > 0


def list_sessions_collectif(collectif_id: int | None = None,
                            statut: str | None = None,
                            limit: int = 50) -> list[dict[str, Any]]:
    """Sessions de type point_vente_collectif, optionnellement filtrées par magasin."""
    init_db()
    sql = """
        SELECT s.*, c.nom AS collectif_nom, c.convention, c.commission_pct
        FROM pos_session s
        LEFT JOIN pos_point_vente_collectif c ON c.id = s.point_vente_id
        WHERE s.type_vente = 'point_vente_collectif'
    """
    params: list[Any] = []
    if collectif_id is not None:
        sql += " AND s.point_vente_id = ?"
        params.append(collectif_id)
    if statut is not None:
        sql += " AND s.statut = ?"
        params.append(statut)
    sql += " ORDER BY s.date_marche DESC, s.id DESC LIMIT ?"
    params.append(limit)
    with _conn() as c:
        rows = c.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def create_depot(collectif_id: int, date_depot: str, notes: str | None = None) -> dict[str, Any]:
    """Crée une session 'point_vente_collectif' = nouveau dépôt chez un magasin."""
    init_db()
    collectif = get_collectif(collectif_id)
    if not collectif:
        raise ValueError(f"Collectif #{collectif_id} introuvable")
    lieu = collectif["nom"]
    with _conn() as c:
        cur = c.execute(
            """
            INSERT INTO pos_session
                (date_marche, lieu, statut, type_vente, point_vente_id, notes)
            VALUES (?, ?, 'ouverte', 'point_vente_collectif', ?, ?)
            """,
            (date_depot, lieu, collectif_id, notes),
        )
        session_id = cur.lastrowid
        row = c.execute("SELECT * FROM pos_session WHERE id = ?", (session_id,)).fetchone()
    log.info("Dépôt collectif créé : session #%s magasin=%s", session_id, lieu)
    return dict(row)
