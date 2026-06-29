"""Seed catalogue AGRI générique (10 produits standard) + activité de DÉMO.

- `seed_if_empty()` : catalogue par défaut si `pos_produit` vide (idempotent).
- `seed_demo_activity()` : 3 marchés clôturés avec ventes / chargements / invendus
  / stock à revoir, pour que les pages Stats et Stock résiduel ne soient pas vides
  en démo. Idempotent (ne fait rien si des sessions existent déjà).
- `seed_demo_if_needed()` : n'agit QU'EN mode démo (`SELFFARM_ENV=demo`), jamais
  en prod/perso — pas de pollution des vraies données.
"""

from __future__ import annotations

import logging
import os
from datetime import date, timedelta

from self_agri_book.storage import _conn, init_db

log = logging.getLogger(__name__)


SEED_PRODUITS_AGRI_GENERIQUE = [
    # (nom, prix_unitaire, unite, categorie, emoji, ordre)
    ("Tomate",         3.50, "kg",          "legume",          "🍅", 10),
    ("Salade",         1.20, "pièce",       "legume",          "🥬", 20),
    ("Courgette",      2.80, "kg",          "legume",          "🥒", 30),
    ("Carotte",        2.00, "kg",          "legume",          "🥕", 40),
    ("Pomme de terre", 1.80, "kg",          "legume",          "🥔", 50),
    ("Pomme",          2.50, "kg",          "fruit",           "🍎", 60),
    ("Fraise",         9.00, "kg",          "fruit",           "🍓", 70),
    ("Œufs",           4.50, "douzaine",    "produit_animal",  "🥚", 80),
    ("Miel",           8.00, "pot 250g",    "produit_animal",  "🍯", 90),
    ("Pain de campagne", 5.50, "miche",     "transforme",      "🍞", 100),
]


def seed_if_empty() -> int:
    """Insère le catalogue par défaut si pos_produit est vide. Retourne nb créés."""
    init_db()
    with _conn() as c:
        nb = c.execute("SELECT COUNT(*) AS n FROM pos_produit").fetchone()["n"]
        if nb > 0:
            return 0
        log.info("Catalogue POS vide — seed AGRI générique (%d produits)", len(SEED_PRODUITS_AGRI_GENERIQUE))
        for nom, prix, unite, cat, emoji, ordre in SEED_PRODUITS_AGRI_GENERIQUE:
            c.execute(
                """
                INSERT INTO pos_produit (nom, prix_unitaire, unite, categorie, emoji, ordre)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (nom, prix, unite, cat, emoji, ordre),
            )
    return len(SEED_PRODUITS_AGRI_GENERIQUE)


# ── Activité de démonstration (lieux neutres, aucune commune réelle) ──────────
# Chaque marché : (jours_avant, lieu, chargements{nom:qté}, ventes[(panier, mode)],
# résidus[(nom, qté, status, destination)])  — panier = [(nom, qté), ...]
_DEMO_MARCHES = [
    (
        21, "Marché hebdomadaire",
        {"Tomate": 15, "Salade": 24, "Courgette": 10, "Carotte": 14, "Pomme de terre": 20,
         "Pomme": 12, "Fraise": 8, "Œufs": 10, "Miel": 6, "Pain de campagne": 12},
        [
            ([("Tomate", 2), ("Salade", 1), ("Pain de campagne", 1)], "especes"),
            ([("Courgette", 1.5), ("Carotte", 2), ("Œufs", 1)], "cb"),
            ([("Pomme", 2), ("Fraise", 2)], "especes"),
            ([("Miel", 1), ("Pain de campagne", 1)], "cheque"),
            ([("Tomate", 3), ("Pomme de terre", 2)], "especes"),
            ([("Salade", 2), ("Courgette", 1)], "cb"),
            ([("Œufs", 2), ("Pomme", 1.5)], "especes"),
        ],
        [("Fraise", 1, "invendu", "compost"), ("Salade", 3, "invendu", "poules"),
         ("Miel", 2, "stock", None)],
    ),
    (
        14, "Marché bio du samedi",
        {"Tomate": 18, "Salade": 20, "Courgette": 12, "Carotte": 12, "Pomme de terre": 22,
         "Pomme": 14, "Fraise": 6, "Œufs": 12, "Miel": 5, "Pain de campagne": 14},
        [
            ([("Tomate", 2.5), ("Courgette", 2)], "cb"),
            ([("Pain de campagne", 2), ("Œufs", 1), ("Miel", 1)], "especes"),
            ([("Pomme", 3), ("Carotte", 1)], "especes"),
            ([("Pomme de terre", 4), ("Salade", 2)], "cheque"),
            ([("Tomate", 1.5), ("Fraise", 1), ("Salade", 1)], "cb"),
            ([("Courgette", 1), ("Œufs", 2)], "especes"),
            ([("Pain de campagne", 1), ("Pomme", 2)], "especes"),
            ([("Miel", 2)], "cb"),
        ],
        [("Courgette", 2, "invendu", "don"), ("Pain de campagne", 1, "invendu", "garde_maison"),
         ("Pomme de terre", 5, "stock", None)],
    ),
    (
        7, "AMAP du village",
        {"Tomate": 16, "Salade": 18, "Courgette": 9, "Carotte": 16, "Pomme de terre": 18,
         "Pomme": 12, "Fraise": 7, "Œufs": 10, "Miel": 6, "Pain de campagne": 12},
        [
            ([("Tomate", 3), ("Salade", 2), ("Œufs", 1)], "especes"),
            ([("Carotte", 2), ("Pomme de terre", 3)], "cb"),
            ([("Fraise", 2), ("Pomme", 2)], "especes"),
            ([("Pain de campagne", 2), ("Miel", 1)], "cheque"),
            ([("Courgette", 2), ("Tomate", 1.5)], "cb"),
            ([("Œufs", 2), ("Salade", 1)], "especes"),
        ],
        [("Carotte", 2, "invendu", "compost"), ("Tomate", 1.5, "invendu", "poules"),
         ("Pomme", 3, "stock", None)],
    ),
]


def seed_demo_activity() -> int:
    """Crée des marchés clôturés de démo (ventes/chargements/résidus). Idempotent.

    Ne fait rien si des sessions existent déjà. Retourne le nb de marchés créés.
    """
    init_db()
    from self_pos import chargement as chg
    from self_pos import residus as res
    from self_pos import storage

    with _conn() as c:
        if c.execute("SELECT COUNT(*) AS n FROM pos_session").fetchone()["n"] > 0:
            return 0

    seed_if_empty()
    produits = {p["nom"]: p for p in storage.list_produits(actifs_only=True)}
    if not produits:
        return 0

    def _ligne(nom: str, qte: float) -> dict:
        p = produits[nom]
        return {
            "produit_id": p["id"], "nom": p["nom"], "emoji": p.get("emoji") or "🌿",
            "qte": qte, "unite": p.get("unite") or "", "total": round(qte * p["prix_unitaire"], 2),
        }

    today = date.today()
    for jours, lieu, charges, ventes, resids in _DEMO_MARCHES:
        d = (today - timedelta(days=jours)).isoformat()
        sess = storage.create_session(d, lieu, "Marché de démonstration")
        sid = sess["id"]
        for nom, qte in charges.items():
            p = produits.get(nom)
            chg.add_chargement_line(sid, p["id"] if p else None, nom,
                                    p.get("unite") if p else "pièce", float(qte))
        for panier, mode in ventes:
            lignes = [_ligne(nom, qte) for nom, qte in panier]
            total = round(sum(l["total"] for l in lignes), 2)
            storage.save_vente(sid, lignes, total, mode)
        for nom, qte, status, dest in resids:
            p = produits.get(nom)
            res.add_residu(sid, nom, float(qte), status,
                           produit_id=p["id"] if p else None,
                           unite=p.get("unite") if p else "pièce", destination=dest)
        storage.mark_session_cloturee(sid, None)

    # Vieillit le stock résiduel pour qu'il remonte dans la revue hebdo (> seuil jours)
    with _conn() as c:
        c.execute(
            "UPDATE pos_residu_marche "
            "SET derniere_revue_at = datetime('now','-10 days'), created_at = datetime('now','-10 days') "
            "WHERE status = 'stock'"
        )

    log.info("Activité POS de démo seedée : %d marchés", len(_DEMO_MARCHES))
    return len(_DEMO_MARCHES)


def seed_demo_if_needed() -> None:
    """En mode démo uniquement : catalogue + activité de démo (idempotent)."""
    if os.environ.get("SELFFARM_ENV", "prod") != "demo":
        return
    seed_if_empty()
    seed_demo_activity()


def reset_demo_activity() -> int:
    """Bac à sable : efface l'activité POS (sessions/ventes/chargements/résidus)
    et régénère les marchés d'exemple. Mode démo STRICT (no-op sinon).
    Le catalogue produits est préservé. Retourne le nb de marchés régénérés."""
    if os.environ.get("SELFFARM_ENV", "prod") != "demo":
        return 0
    init_db()
    with _conn() as c:
        for table in ("pos_vente", "pos_chargement", "pos_residu_marche", "pos_session"):
            c.execute(f"DELETE FROM {table}")
    log.info("Bac à sable POS réinitialisé")
    return seed_demo_activity()
