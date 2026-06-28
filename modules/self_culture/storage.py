"""
Persistance SQLite pour self_culture (DRAFT — non wirée à webapp).

Migrations versionnées (4 → 9) qui s'enchaînent à partir des migrations
existantes du hub compta self_agri_book. Tant que ce module n'est pas câblé
dans `webapp/main.py`, ces migrations ne sont pas appliquées et le hub compta
reste sur ses 3 migrations actuelles.

L'activation se fera lors de la **Phase 1 officielle (11/05/2026)** par
import du module dans `webapp/main.py` et appel de `init_db()` au boot.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

log = logging.getLogger("self-culture")

# Les migrations 1, 2, 3 sont gérées par self_agri_book/storage.py.
# self_culture poursuit la séquence avec 4-9.
MIGRATIONS: list[tuple[int, str, str]] = [
    (
        4,
        "create_varietes_user",
        """
        CREATE TABLE IF NOT EXISTS varietes_user (
            id TEXT PRIMARY KEY,                  -- slug de la variété
            nom_commun TEXT NOT NULL,
            nom_botanique TEXT NOT NULL,
            famille TEXT NOT NULL,
            categorie TEXT NOT NULL,
            mode_production_principal TEXT DEFAULT 'ab',
            calendrier_json TEXT NOT NULL,        -- CalendrierCulture sérialisé
            rendement_json TEXT NOT NULL,         -- RendementReference sérialisé
            saisons_json TEXT DEFAULT '[]',
            fournisseurs_json TEXT DEFAULT '[]',
            notes TEXT DEFAULT '',
            source TEXT DEFAULT 'user',           -- 'user' ou 'catalog' (héritage YAML)
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_varietes_famille ON varietes_user(famille);
        CREATE INDEX IF NOT EXISTS idx_varietes_categorie ON varietes_user(categorie);
        """,
    ),
    (
        5,
        "create_parcelles",
        """
        CREATE TABLE IF NOT EXISTS parcelles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL,
            code_insee TEXT NOT NULL,
            commune_nom TEXT NOT NULL,
            section_cadastre TEXT DEFAULT '',
            parcelle_cadastre TEXT DEFAULT '',
            surface_m2 REAL NOT NULL CHECK (surface_m2 >= 0),
            geometry_geojson TEXT,                -- Polygon GeoJSON (cf. self_parcelles roadmap)
            metadata_json TEXT DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_parcelles_insee ON parcelles(code_insee);
        CREATE UNIQUE INDEX IF NOT EXISTS uniq_parcelle_cadastre
            ON parcelles(code_insee, section_cadastre, parcelle_cadastre)
            WHERE section_cadastre != '' AND parcelle_cadastre != '';
        """,
    ),
    (
        6,
        "create_planches",
        """
        CREATE TABLE IF NOT EXISTS planches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parcelle_id INTEGER NOT NULL,
            nom TEXT NOT NULL,
            surface_m2 REAL NOT NULL CHECK (surface_m2 >= 0),
            largeur_m REAL,
            longueur_m REAL,
            abri INTEGER NOT NULL DEFAULT 0,      -- 0/1 booléen
            metadata_json TEXT DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (parcelle_id) REFERENCES parcelles(id)
        );
        CREATE INDEX IF NOT EXISTS idx_planches_parcelle ON planches(parcelle_id);
        """,
    ),
    (
        7,
        "create_plan_culture",
        """
        CREATE TABLE IF NOT EXISTS plan_culture (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            annee INTEGER NOT NULL CHECK (annee >= 2020 AND annee <= 2100),
            planche_id INTEGER NOT NULL,
            variete_id TEXT NOT NULL,
            date_semis_prev TEXT,                 -- ISO 8601
            date_repiquage_prev TEXT,
            date_recolte_prev TEXT,
            densite_plants_m2 REAL,
            rendement_kg_attendu REAL,
            notes TEXT DEFAULT '',
            metadata_json TEXT DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (planche_id) REFERENCES planches(id),
            FOREIGN KEY (variete_id) REFERENCES varietes_user(id)
        );
        CREATE INDEX IF NOT EXISTS idx_plan_culture_annee ON plan_culture(annee);
        CREATE INDEX IF NOT EXISTS idx_plan_culture_planche ON plan_culture(planche_id);
        """,
    ),
    (
        8,
        "create_assolement_cycle",
        """
        CREATE TABLE IF NOT EXISTS assolement_cycle (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parcelle_id INTEGER NOT NULL,
            annee INTEGER NOT NULL CHECK (annee >= 2020 AND annee <= 2100),
            famille_botanique TEXT NOT NULL,
            culture_principale TEXT DEFAULT '',
            engrais_vert_intercalaire TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (parcelle_id) REFERENCES parcelles(id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS uniq_assolement_parcelle_annee
            ON assolement_cycle(parcelle_id, annee);
        CREATE INDEX IF NOT EXISTS idx_assolement_famille
            ON assolement_cycle(famille_botanique);
        """,
    ),
    (
        9,
        "create_taches_planning",
        """
        CREATE TABLE IF NOT EXISTS taches_planning (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            semaine_iso TEXT NOT NULL,            -- AAAA-Wnn (ex: 2026-W22)
            date_prevue TEXT NOT NULL,            -- ISO 8601
            type TEXT NOT NULL,                   -- semis, repiquage, désherbage, etc.
            libelle TEXT NOT NULL,
            plan_culture_id INTEGER,
            duree_min_estimee_min INTEGER,
            duree_min_reelle_min INTEGER,
            affectation TEXT DEFAULT '',
            statut TEXT NOT NULL DEFAULT 'prevue',
            done_at TEXT,
            notes TEXT DEFAULT '',
            metadata_json TEXT DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (plan_culture_id) REFERENCES plan_culture(id)
        );
        CREATE INDEX IF NOT EXISTS idx_taches_semaine ON taches_planning(semaine_iso);
        CREATE INDEX IF NOT EXISTS idx_taches_statut ON taches_planning(statut);
        CREATE INDEX IF NOT EXISTS idx_taches_date ON taches_planning(date_prevue);
        """,
    ),
]


def get_db_path() -> Path:
    """Retourne le chemin de la DB compta SelfFarm.

    Réutilise la même DB que self_agri_book (hub central, schema unifié).
    Variable d'environnement SELFFARM_COMPTA_DB ou défaut ~/.selffarm/compta.db.
    """
    import os

    env_path = os.environ.get("SELFFARM_COMPTA_DB")
    if env_path:
        return Path(env_path)
    return Path.home() / ".selffarm" / "compta.db"


@contextmanager
def get_connection(db_path: Path | None = None):
    """Connexion SQLite avec foreign_keys ON et row_factory dict."""
    path = db_path or get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | None = None) -> None:
    """Applique les migrations 4→9 sur la DB compta.

    Réutilise la table `_schema_migrations` du hub self_agri_book si elle
    existe déjà, sinon la crée. Les migrations sont idempotentes via
    `IF NOT EXISTS` et tracées dans `_schema_migrations`.
    """
    with get_connection(db_path) as conn:
        # Crée _schema_migrations si absent (sera no-op si self_agri_book l'a déjà)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS _schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )

        applied = {row["version"] for row in conn.execute("SELECT version FROM _schema_migrations")}
        for version, name, sql in MIGRATIONS:
            if version in applied:
                continue
            log.info("Application migration self_culture %d : %s", version, name)
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO _schema_migrations (version, name) VALUES (?, ?)",
                (version, name),
            )


# ---- Fonctions de base (à étoffer en Phase 1) ----


def upsert_variete_user(
    variete_dict: dict[str, Any],
    db_path: Path | None = None,
) -> str:
    """Insère ou met à jour une variété dans `varietes_user`.

    Pour Phase 1 : INSERT minimal pour préseed depuis le YAML. Les UPDATE et
    formulaires de saisie viendront dans la Phase 1 webapp.
    """
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO varietes_user (
                id, nom_commun, nom_botanique, famille, categorie,
                mode_production_principal, calendrier_json, rendement_json,
                saisons_json, fournisseurs_json, notes, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                nom_commun = excluded.nom_commun,
                nom_botanique = excluded.nom_botanique,
                famille = excluded.famille,
                categorie = excluded.categorie,
                mode_production_principal = excluded.mode_production_principal,
                calendrier_json = excluded.calendrier_json,
                rendement_json = excluded.rendement_json,
                saisons_json = excluded.saisons_json,
                fournisseurs_json = excluded.fournisseurs_json,
                notes = excluded.notes,
                updated_at = datetime('now')
            """,
            (
                variete_dict["id"],
                variete_dict["nom_commun"],
                variete_dict["nom_botanique"],
                variete_dict["famille"],
                variete_dict["categorie"],
                variete_dict.get("mode_production_principal", "ab"),
                json.dumps(variete_dict["calendrier"]),
                json.dumps(variete_dict["rendement"]),
                json.dumps(variete_dict.get("saisons_principales", [])),
                json.dumps(variete_dict.get("fournisseurs_recommandes", [])),
                variete_dict.get("notes", ""),
                variete_dict.get("source", "catalog"),
            ),
        )
        return variete_dict["id"]


def list_varietes_user(db_path: Path | None = None) -> list[dict[str, Any]]:
    """Liste toutes les variétés présentes dans la table user."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM varietes_user ORDER BY famille, nom_commun"
        ).fetchall()
        return [dict(r) for r in rows]
