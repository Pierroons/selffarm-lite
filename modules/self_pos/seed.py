"""Seed catalogue AGRI générique (10 produits standard).

Auto-appliqué si la table pos_produit est vide à l'init.
Idempotent — relancable sans risque (vérifie vide avant insert).
"""

from __future__ import annotations

import logging

from self_agri_book.storage import _conn, init_db

log = logging.getLogger(__name__)


SEED_PRODUITS_AGRI_GENERIQUE = [
    # (nom, prix_unitaire, unite, categorie, emoji, ordre)
    ("Tomate",         3.50, "kg",          "legume",          "🍅", 10),
    ("Salade",         1.20, "pièce",       "legume",          "🥬", 20),
    ("Courgette",      2.80, "kg",          "legume",          "🥒", 30),
    ("Carotte",        1.50, "botte",       "legume",          "🥕", 40),
    ("Pomme de terre", 1.80, "kg",          "legume",          "🥔", 50),
    ("Pomme",          2.50, "kg",          "fruit",           "🍎", 60),
    ("Fraise",         4.00, "barquette",   "fruit",           "🍓", 70),
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
