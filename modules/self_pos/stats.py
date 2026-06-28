"""SelfPOS V0.4 — Statistiques produits (ventes, CA, invendus, évolution).

Agrège les données de toutes les sessions clôturées :
- Top produits vendus (quantité + CA)
- Répartition CA par produit
- Évolution ventes par semaine
- Taux invendu par produit (chargé vs vendu vs jeté)
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import date, datetime
from typing import Any

from self_agri_book.storage import _conn, init_db

log = logging.getLogger(__name__)


def _iter_ventes_lignes() -> list[dict[str, Any]]:
    """Retourne toutes les lignes de vente (1 dict par produit vendu) avec date session."""
    init_db()
    out: list[dict[str, Any]] = []
    with _conn() as c:
        rows = c.execute(
            """
            SELECT v.lignes_json, v.total_ttc, v.created_at, s.date_marche, s.lieu
            FROM pos_vente v
            JOIN pos_session s ON s.id = v.session_id
            """
        ).fetchall()
    for r in rows:
        try:
            lignes = json.loads(r["lignes_json"] or "[]")
        except json.JSONDecodeError:
            continue
        for ligne in lignes:
            out.append({
                "produit_id": ligne.get("produit_id"),
                "nom": ligne.get("nom") or "?",
                "emoji": ligne.get("emoji") or "🌿",
                "qte": float(ligne.get("qte") or 0),
                "total": float(ligne.get("total") or 0),
                "unite": ligne.get("unite") or "",
                "date_marche": r["date_marche"],
                "created_at": r["created_at"],
            })
    return out


def stats_produits(limit: int = 10) -> dict[str, Any]:
    """Top produits par CA + quantité. Pour bar chart + donut."""
    lignes = _iter_ventes_lignes()
    agg: dict[str, dict[str, Any]] = {}
    for l in lignes:
        key = l["nom"]
        if key not in agg:
            agg[key] = {"nom": key, "emoji": l["emoji"], "unite": l["unite"], "qte": 0.0, "ca": 0.0}
        agg[key]["qte"] += l["qte"]
        agg[key]["ca"] += l["total"]
    produits = sorted(agg.values(), key=lambda x: x["ca"], reverse=True)
    top = produits[:limit]
    return {
        "produits": [
            {"nom": p["nom"], "emoji": p["emoji"], "unite": p["unite"],
             "qte": round(p["qte"], 2), "ca": round(p["ca"], 2)}
            for p in top
        ],
        "ca_total": round(sum(p["ca"] for p in produits), 2),
        "nb_produits_distincts": len(produits),
    }


def stats_ventes_par_semaine(nb_semaines: int = 12) -> dict[str, Any]:
    """Série temporelle CA par semaine (ISO). Pour line/bar chart."""
    lignes = _iter_ventes_lignes()
    par_semaine: dict[str, float] = defaultdict(float)
    for l in lignes:
        d = l["date_marche"] or l["created_at"]
        if not d or len(d) < 10:
            continue
        try:
            dt = datetime.fromisoformat(d[:10])
            iso_year, iso_week, _ = dt.isocalendar()
            key = f"{iso_year}-S{iso_week:02d}"
        except ValueError:
            continue
        par_semaine[key] += l["total"]
    # Trie + limite aux nb_semaines dernières
    items = sorted(par_semaine.items())[-nb_semaines:]
    return {
        "labels": [k for k, _ in items],
        "data": [round(v, 2) for _, v in items],
    }


def stats_invendus() -> dict[str, Any]:
    """Pour chaque produit : quantité chargée vs vendue vs invendue. Taux de perte."""
    init_db()
    # Chargé par produit (toutes sessions)
    charge: dict[str, dict[str, Any]] = {}
    with _conn() as c:
        rows = c.execute(
            "SELECT produit_nom, unite, COALESCE(SUM(quantite_chargee),0) AS q FROM pos_chargement GROUP BY produit_nom"
        ).fetchall()
        for r in rows:
            charge[r["produit_nom"]] = {"unite": r["unite"], "charge": float(r["q"] or 0), "invendu": 0.0, "vendu": 0.0}
        # Invendu par produit
        rows = c.execute(
            "SELECT produit_nom, COALESCE(SUM(quantite),0) AS q FROM pos_residu_marche WHERE status='invendu' GROUP BY produit_nom"
        ).fetchall()
        for r in rows:
            charge.setdefault(r["produit_nom"], {"unite": "", "charge": 0.0, "invendu": 0.0, "vendu": 0.0})
            charge[r["produit_nom"]]["invendu"] = float(r["q"] or 0)
    # Vendu par produit (depuis lignes)
    for l in _iter_ventes_lignes():
        charge.setdefault(l["nom"], {"unite": l["unite"], "charge": 0.0, "invendu": 0.0, "vendu": 0.0})
        charge[l["nom"]]["vendu"] += l["qte"]

    out = []
    for nom, d in charge.items():
        total_ref = d["charge"] if d["charge"] > 0 else (d["vendu"] + d["invendu"])
        taux_invendu = round(d["invendu"] / total_ref * 100, 1) if total_ref > 0 else 0
        out.append({
            "nom": nom, "unite": d["unite"],
            "charge": round(d["charge"], 1),
            "vendu": round(d["vendu"], 1),
            "invendu": round(d["invendu"], 1),
            "taux_invendu": taux_invendu,
        })
    # Trie par taux invendu décroissant (les plus problématiques en haut)
    out.sort(key=lambda x: x["taux_invendu"], reverse=True)
    return {"produits": out}


def stats_globales_pos() -> dict[str, Any]:
    """KPIs généraux : CA total, nb marchés clôturés, panier moyen, produit star."""
    init_db()
    with _conn() as c:
        nb_marches = c.execute("SELECT COUNT(*) AS n FROM pos_session WHERE statut='cloturee'").fetchone()["n"]
        nb_ventes = c.execute("SELECT COUNT(*) AS n FROM pos_vente").fetchone()["n"]
        ca_total = c.execute("SELECT COALESCE(SUM(total_ttc),0) AS t FROM pos_vente").fetchone()["t"]
    panier_moyen = round(ca_total / nb_ventes, 2) if nb_ventes > 0 else 0
    top = stats_produits(limit=1)["produits"]
    produit_star = top[0]["nom"] if top else "—"
    return {
        "ca_total": round(ca_total, 2),
        "nb_marches": nb_marches,
        "nb_ventes": nb_ventes,
        "panier_moyen": panier_moyen,
        "produit_star": produit_star,
    }


def get_all_stats() -> dict[str, Any]:
    return {
        "kpis": stats_globales_pos(),
        "top_produits": stats_produits(limit=10),
        "ventes_semaine": stats_ventes_par_semaine(12),
        "invendus": stats_invendus(),
        "saison": date.today().year,
    }
