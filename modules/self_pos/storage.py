"""SelfPOS storage — CRUD produits / sessions / ventes.

S'appuie sur la BDD partagée self_agri_book (hub compta unique).
Les migrations 7-9 sont définies dans self_agri_book.storage.MIGRATIONS.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from self_agri_book.storage import _conn, init_db

log = logging.getLogger(__name__)


# ============================================================
# CRUD Produits
# ============================================================

PRODUIT_FIELDS = {"nom", "prix_unitaire", "unite", "categorie", "emoji", "actif", "ordre"}


def list_produits(actifs_only: bool = True) -> list[dict[str, Any]]:
    init_db()
    sql = "SELECT * FROM pos_produit"
    if actifs_only:
        sql += " WHERE actif = 1"
    sql += " ORDER BY ordre, nom"
    with _conn() as c:
        rows = c.execute(sql).fetchall()
    return [dict(r) for r in rows]


def get_produit(produit_id: int) -> dict[str, Any] | None:
    init_db()
    with _conn() as c:
        row = c.execute("SELECT * FROM pos_produit WHERE id = ?", (produit_id,)).fetchone()
    return dict(row) if row else None


def save_produit(data: dict[str, Any]) -> dict[str, Any]:
    """UPSERT produit. `id` présent → UPDATE, sinon INSERT."""
    init_db()
    if not data.get("nom"):
        raise ValueError("save_produit : 'nom' requis")
    prix = data.get("prix_unitaire")
    if prix is None or float(prix) < 0:
        raise ValueError("save_produit : 'prix_unitaire' doit être ≥ 0")
    payload = {k: v for k, v in data.items() if k in PRODUIT_FIELDS}
    produit_id = data.get("id")
    with _conn() as c:
        if produit_id:
            set_clause = ", ".join(f"{k} = ?" for k in payload)
            c.execute(
                f"UPDATE pos_produit SET {set_clause}, updated_at = datetime('now') WHERE id = ?",
                list(payload.values()) + [produit_id],
            )
            log.info("Produit POS #%s mis à jour : %s", produit_id, payload.get("nom"))
            return get_produit(produit_id)
        cols = ", ".join(payload.keys())
        placeholders = ", ".join("?" for _ in payload)
        cur = c.execute(
            f"INSERT INTO pos_produit ({cols}) VALUES ({placeholders})",
            list(payload.values()),
        )
        new_id = cur.lastrowid
        log.info("Produit POS créé #%s : %s", new_id, payload.get("nom"))
        return get_produit(new_id)


def toggle_produit(produit_id: int) -> bool:
    """Inverse actif. Retourne le nouvel état."""
    init_db()
    with _conn() as c:
        row = c.execute("SELECT actif FROM pos_produit WHERE id = ?", (produit_id,)).fetchone()
        if not row:
            return False
        new_actif = 0 if row["actif"] else 1
        c.execute(
            "UPDATE pos_produit SET actif = ?, updated_at = datetime('now') WHERE id = ?",
            (new_actif, produit_id),
        )
    return bool(new_actif)


def delete_produit(produit_id: int) -> bool:
    """Soft delete = actif=0. Hard delete possible via force=True."""
    init_db()
    with _conn() as c:
        cur = c.execute(
            "UPDATE pos_produit SET actif = 0, updated_at = datetime('now') WHERE id = ?",
            (produit_id,),
        )
        return cur.rowcount > 0


# ============================================================
# CRUD Sessions
# ============================================================

def list_sessions(limit: int = 50) -> list[dict[str, Any]]:
    init_db()
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM pos_session ORDER BY date_marche DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_session(session_id: int) -> dict[str, Any] | None:
    init_db()
    with _conn() as c:
        row = c.execute("SELECT * FROM pos_session WHERE id = ?", (session_id,)).fetchone()
    return dict(row) if row else None


def get_session_ouverte() -> dict[str, Any] | None:
    """Récupère la session ouverte la plus récente (max 1 normalement)."""
    init_db()
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM pos_session WHERE statut = 'ouverte' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def create_session(date_marche: str, lieu: str, notes: str | None = None) -> dict[str, Any]:
    init_db()
    if not date_marche or not lieu:
        raise ValueError("create_session : date_marche et lieu requis")
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO pos_session (date_marche, lieu, notes) VALUES (?, ?, ?)",
            (date_marche, lieu.strip(), notes),
        )
        new_id = cur.lastrowid
    log.info("Session POS créée #%s — %s à %s", new_id, date_marche, lieu)
    return get_session(new_id)


def mark_session_cloturee(session_id: int, ecriture_id: int | None) -> dict[str, Any] | None:
    init_db()
    with _conn() as c:
        cur = c.execute(
            """
            UPDATE pos_session
            SET statut = 'cloturee',
                cloture_at = datetime('now'),
                ecriture_id = ?
            WHERE id = ? AND statut = 'ouverte'
            """,
            (ecriture_id, session_id),
        )
        if cur.rowcount == 0:
            return None
    log.info("Session POS #%s clôturée (écriture compta #%s)", session_id, ecriture_id)
    return get_session(session_id)


def _refresh_session_totaux(session_id: int) -> None:
    """Recalcule total_ttc + ventilation modes paiement + nb_ventes depuis pos_vente."""
    with _conn() as c:
        agg = c.execute(
            """
            SELECT
                COALESCE(SUM(total_ttc), 0) AS total_ttc,
                COALESCE(SUM(CASE WHEN mode_paiement = 'especes' THEN total_ttc ELSE 0 END), 0) AS especes,
                COALESCE(SUM(CASE WHEN mode_paiement = 'cb' THEN total_ttc ELSE 0 END), 0) AS cb,
                COALESCE(SUM(CASE WHEN mode_paiement = 'cheque' THEN total_ttc ELSE 0 END), 0) AS cheque,
                COUNT(*) AS nb
            FROM pos_vente
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
        c.execute(
            """
            UPDATE pos_session
            SET total_ttc = ?, total_especes = ?, total_cb = ?, total_cheque = ?, nb_ventes = ?
            WHERE id = ?
            """,
            (agg["total_ttc"], agg["especes"], agg["cb"], agg["cheque"], agg["nb"], session_id),
        )


# ============================================================
# CRUD Ventes
# ============================================================

def list_ventes(session_id: int) -> list[dict[str, Any]]:
    init_db()
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM pos_vente WHERE session_id = ? ORDER BY id DESC",
            (session_id,),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        try:
            d["lignes"] = json.loads(d.get("lignes_json") or "[]")
        except json.JSONDecodeError:
            d["lignes"] = []
        out.append(d)
    return out


def save_vente(
    session_id: int,
    lignes: list[dict[str, Any]],
    total_ttc: float,
    mode_paiement: str,
    details_paiement: dict[str, float] | None = None,
    client_libelle: str | None = None,
    offline_uuid: str | None = None,
) -> dict[str, Any]:
    """Crée une vente. Dédup via `offline_uuid` UNIQUE si fourni."""
    init_db()
    if mode_paiement not in {"especes", "cb", "cheque", "mixte"}:
        raise ValueError(f"mode_paiement '{mode_paiement}' invalide")
    if total_ttc < 0:
        raise ValueError("total_ttc doit être ≥ 0")

    session = get_session(session_id)
    if not session:
        raise ValueError(f"Session #{session_id} introuvable")
    if session["statut"] != "ouverte":
        raise ValueError(f"Session #{session_id} déjà clôturée")

    # Dédup offline_uuid (idempotence sync queue)
    if offline_uuid:
        with _conn() as c:
            existing = c.execute(
                "SELECT * FROM pos_vente WHERE offline_uuid = ?",
                (offline_uuid,),
            ).fetchone()
            if existing:
                log.info("Vente offline_uuid=%s déjà enregistrée → dédup", offline_uuid)
                d = dict(existing)
                try:
                    d["lignes"] = json.loads(d.get("lignes_json") or "[]")
                except json.JSONDecodeError:
                    d["lignes"] = []
                return d

    lignes_json = json.dumps(lignes, ensure_ascii=False)
    details_json = json.dumps(details_paiement, ensure_ascii=False) if details_paiement else None

    with _conn() as c:
        cur = c.execute(
            """
            INSERT INTO pos_vente
                (session_id, lignes_json, total_ttc, mode_paiement,
                 details_paiement_json, client_libelle, offline_uuid)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, lignes_json, total_ttc, mode_paiement,
             details_json, client_libelle, offline_uuid),
        )
        new_id = cur.lastrowid

    _refresh_session_totaux(session_id)

    log.info("Vente POS #%s session=%s total=%.2f mode=%s", new_id, session_id, total_ttc, mode_paiement)
    return {"id": new_id, "session_id": session_id, "total_ttc": total_ttc, "mode_paiement": mode_paiement, "lignes": lignes}


def delete_vente(vente_id: int) -> bool:
    init_db()
    with _conn() as c:
        row = c.execute("SELECT session_id FROM pos_vente WHERE id = ?", (vente_id,)).fetchone()
        if not row:
            return False
        session_id = row["session_id"]
        c.execute("DELETE FROM pos_vente WHERE id = ?", (vente_id,))
    _refresh_session_totaux(session_id)
    return True
