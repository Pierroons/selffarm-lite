"""
Agrégation des stats pour le tableau de bord home (KPI + 4 charts + dernières écritures).

Lecture seule, branche directement les tables SQLite :
- `parcelle`, `plan_culture` (via self_culture.cultures)
- `ecritures_comptables` (via self_agri_book.storage)

V1 stub : plafonds aides hardcodés (cohérents profil JA bio).
V2 prévu : catalogue self_aid dynamique par profil JA / NA / AGRI / PME.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from self_culture.cultures import list_plan_culture, stats_parcelles_saison
from self_agri_book.exploitation import get_exploitation
from self_agri_book.storage import _conn, init_db

log = logging.getLogger(__name__)

MONTH_LABELS = [
    "Jan", "Fév", "Mar", "Avr", "Mai", "Juin",
    "Juil", "Août", "Sept", "Oct", "Nov", "Déc",
]

# Plafonds aides référence JA bio (mémoire project_aides_agri_pierroons.md)
# Filtre auto-appliqué : plafond=0 → exclu du chart (règle "ligne jamais à 0")
DEFAULT_AIDES_PLAFOND: dict[str, float] = {
    "DNJA Trésorerie": 24500,
    "ACJA 2026": 5300,
    "CI Agri-Bio": 4500,
    "Écorégime bio": 660,
    "Chanvre couplé": 144,
}

# Heuristique gauge : 40 écritures sur la saison = 100 % de saisie estimée
GAUGE_TARGET = 40


def _saison_courante() -> int:
    exp = get_exploitation()
    if exp and exp.get("saison_courante"):
        return int(exp["saison_courante"])
    return date.today().year


def _ecritures_par_mois(saison: int) -> dict[str, list[float]]:
    """Recettes / charges agrégées par mois (1-12) sur la saison."""
    recettes = [0.0] * 12
    charges = [0.0] * 12
    init_db()
    with _conn() as c:
        rows = c.execute(
            """
            SELECT date_operation, journal, compte_credit, compte_debit, montant_ttc
            FROM ecritures_comptables
            WHERE strftime('%Y', date_operation) = ?
            """,
            (str(saison),),
        ).fetchall()
    for r in rows:
        try:
            mois_idx = int(r["date_operation"][5:7]) - 1
            if not (0 <= mois_idx < 12):
                continue
            montant = float(r["montant_ttc"] or 0)
            cc = (r["compte_credit"] or "")
            cd = (r["compte_debit"] or "")
            # Classe 7 en crédit = produit → recette
            if cc.startswith("7"):
                recettes[mois_idx] += montant
            # Classe 6 en débit = charge
            elif cd.startswith("6"):
                charges[mois_idx] += montant
        except (ValueError, TypeError, KeyError):
            continue
    return {"recettes": recettes, "charges": charges}


def _cultures_repartition(saison: int) -> dict[str, Any]:
    """Répartition des surfaces (ha) par culture sur la saison. Fallback parcelle si plan sans surface."""
    plans = list_plan_culture(saison=saison)
    by_culture: dict[str, float] = {}
    for p in plans:
        key = (p.get("culture_label") or p.get("culture") or "—").strip() or "—"
        surf = p.get("surface_ha")
        if not surf:
            # fallback : surface de la parcelle entière
            surf = p.get("parcelle_surface_ha") or 0
        try:
            by_culture[key] = by_culture.get(key, 0.0) + float(surf or 0)
        except (TypeError, ValueError):
            continue
    return {
        "labels": list(by_culture.keys()),
        "data": [round(v, 2) for v in by_culture.values()],
    }


def _aides_combo(saison: int) -> dict[str, Any]:
    """Pour le combo bar+line : perçu (depuis écritures compte 74xx) vs plafond stub."""
    plafond = DEFAULT_AIDES_PLAFOND.copy()
    percu = {k: 0.0 for k in plafond}
    init_db()
    with _conn() as c:
        rows = c.execute(
            """
            SELECT libelle, montant_ttc
            FROM ecritures_comptables
            WHERE compte_credit LIKE '74%'
              AND strftime('%Y', date_operation) = ?
            """,
            (str(saison),),
        ).fetchall()
    for r in rows:
        lib = (r["libelle"] or "").lower()
        try:
            montant = float(r["montant_ttc"] or 0)
        except (ValueError, TypeError):
            continue
        # Heuristique simple : matching premier mot-clé du libellé d'aide
        for key in plafond:
            kw = key.lower().split()[0]
            if kw in lib:
                percu[key] += montant
                break

    # Règle "ligne plafond jamais à 0" → filtre aides où plafond > 0
    labels = [k for k, p in plafond.items() if p > 0]
    data_percu = [round(percu[k], 2) for k in labels]
    data_plafond = [plafond[k] for k in labels]
    total_percu = sum(data_percu)
    total_plafond = sum(data_plafond)
    return {
        "labels": labels,
        "percu": data_percu,
        "plafond": data_plafond,
        "total_percu": total_percu,
        "total_plafond": total_plafond,
        "reste": total_plafond - total_percu,
    }


def _dernieres_ecritures(limit: int = 5) -> list[dict[str, Any]]:
    """Les n dernières écritures (date desc) avec metadata pour le tableau dashboard."""
    init_db()
    out: list[dict[str, Any]] = []
    with _conn() as c:
        rows = c.execute(
            """
            SELECT date_operation, libelle, compte_debit, compte_credit,
                   montant_ttc, source_module
            FROM ecritures_comptables
            ORDER BY date_operation DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    for r in rows:
        try:
            montant = float(r["montant_ttc"] or 0)
        except (ValueError, TypeError):
            montant = 0.0
        cc = (r["compte_credit"] or "")
        est_recette = cc.startswith("7") or cc.startswith("411")
        d_iso = r["date_operation"] or ""
        date_short = f"{d_iso[8:10]}/{d_iso[5:7]}" if len(d_iso) >= 10 else d_iso
        src = (r["source_module"] or "manuel").lower()
        if "invoice" in src or "selfpos" in src or "auto" in src:
            tag, tag_class = "Auto", "tag-auto"
        elif "banking" in src or "import" in src or "pdf" in src:
            tag, tag_class = src.upper()[:8], "tag-import"
        else:
            tag, tag_class = "Manuel", "tag-manuel"
        out.append({
            "date_short": date_short,
            "libelle": r["libelle"],
            "compte": f"{r['compte_debit']} / {r['compte_credit']}",
            "montant": round(montant, 2),
            "signe": "+" if est_recette else "−",
            "amount_class": "pos" if est_recette else "neg",
            "tag": tag,
            "tag_class": tag_class,
        })
    return out


def _nb_ecritures_saison(saison: int) -> int:
    init_db()
    with _conn() as c:
        row = c.execute(
            "SELECT COUNT(*) AS n FROM ecritures_comptables WHERE strftime('%Y', date_operation) = ?",
            (str(saison),),
        ).fetchone()
    return int(row["n"] if row else 0)


def _nb_factures_emises_saison(saison: int) -> int:
    """Compte des écritures issues du module self_invoice cette saison."""
    init_db()
    with _conn() as c:
        row = c.execute(
            """
            SELECT COUNT(*) AS n FROM ecritures_comptables
            WHERE source_module = 'self_invoice'
              AND strftime('%Y', date_operation) = ?
            """,
            (str(saison),),
        ).fetchone()
    return int(row["n"] if row else 0)


def get_dashboard_stats() -> dict[str, Any]:
    """Dict complet prêt à passer au template ou retourner via /api/dashboard/stats."""
    saison = _saison_courante()
    parc_stats = stats_parcelles_saison(saison)
    plans = list_plan_culture(saison=saison)

    ecr_mois = _ecritures_par_mois(saison)
    total_recettes = round(sum(ecr_mois["recettes"]), 2)
    total_charges = round(sum(ecr_mois["charges"]), 2)
    solde = round(total_recettes - total_charges, 2)

    aides = _aides_combo(saison)
    nb_ecr = _nb_ecritures_saison(saison)
    nb_fact = _nb_factures_emises_saison(saison)
    gauge_pct = min(100, round(nb_ecr / GAUGE_TARGET * 100)) if GAUGE_TARGET else 0

    return {
        "saison": saison,
        "kpis": {
            "parcelles": {
                "count": parc_stats.get("count", 0),
                "surface_ha": parc_stats.get("surface_total_ha", 0),
            },
            "cultures": {
                "count": len(plans),
                "actives": len({(p.get("culture_label") or p.get("culture") or "") for p in plans if p}),
            },
            "factures": {
                "count": nb_fact,
                "volume": total_recettes,
            },
            "resultat": {
                "recettes": total_recettes,
                "charges": total_charges,
                "solde": solde,
            },
            "aides": {
                "percu": aides["total_percu"],
                "plafond": aides["total_plafond"],
                "reste": aides["reste"],
                "count_actives": len(aides["labels"]),
            },
            "banking": {
                "imports": int((parc_stats.get("count", 0) > 0) and 0),
            },
            "ecritures_total": nb_ecr,
        },
        "chart_revenus": {
            "labels": MONTH_LABELS,
            "recettes": [round(v, 2) for v in ecr_mois["recettes"]],
            "charges": [round(v, 2) for v in ecr_mois["charges"]],
        },
        "chart_cultures": _cultures_repartition(saison),
        "chart_aides": aides,
        "gauge": {
            "pct": gauge_pct,
            "nb_ecritures": nb_ecr,
            "target": GAUGE_TARGET,
        },
        "dernieres_ecritures": _dernieres_ecritures(5),
    }
