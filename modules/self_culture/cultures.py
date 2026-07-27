"""
self_culture.cultures — CRUD parcelle + plan_culture + catalogue variétés.

Verticale agricole : les tables `parcelle` + `plan_culture` sont PORTÉES par ce
module (CULTURE_MIGRATIONS, namespace "self_culture"), créées paresseusement sur
la base partagée du hub `self_agri_book`. Le noyau compta reste agnostique du métier.
Catalogue variétés : YAML `modules/self_culture/data/varietes-references.yaml`
                     (variétés AB courantes + chanvre + engrais verts).

API :
- list_parcelles() → list[dict]
- get_parcelle(parcelle_id) → dict | None
- save_parcelle(data) → dict (UPSERT, retourne version persistée)
- delete_parcelle(parcelle_id) → bool
- list_plan_culture(saison=None, parcelle_id=None) → list[dict] (filtres optionnels)
- get_plan_culture(plan_id) → dict | None
- save_plan_culture(data) → dict
- delete_plan_culture(plan_id) → bool

Catalogue (couche typée self_culture.catalog, loader Pydantic unique) :
- get_varietes_for_datalist() → list[dict] (format optimisé pour <datalist>)
"""

from __future__ import annotations

import logging
from typing import Any

from self_agri_book.storage import _conn, apply_module_migrations

from self_culture.catalog import load_catalog
from self_culture.models import ModeProduction

log = logging.getLogger(__name__)

# ============================================================
# Schéma porté par la verticale (hors du noyau compta agnostique)
# ============================================================
# Les tables parcelle/plan_culture sont du vocabulaire agricole : elles vivent
# dans cette verticale, pas dans le noyau self_agri_book. Versionnées à partir de 1
# sous le namespace "self_culture" (cf. _schema_migrations clé composite).
CULTURE_MIGRATIONS: list[tuple[int, str, str]] = [
    (1, "create_parcelle", """
        -- Parcelles déclarées de l'exploitation.
        CREATE TABLE IF NOT EXISTS parcelle (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL,                       -- libellé court (ex: "Champ du haut")
            ref_cadastrale TEXT,                     -- ex: "ZA 0042" (optionnel)
            commune TEXT NOT NULL,
            code_postal TEXT,
            surface_ha REAL NOT NULL CHECK (surface_ha > 0),
            statut TEXT NOT NULL DEFAULT 'bio' CHECK (statut IN ('bio','conversion','conventionnel')),
            date_acquisition TEXT,                   -- ISO YYYY-MM-DD (optionnel)
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_parcelle_commune ON parcelle(commune);
        CREATE INDEX IF NOT EXISTS idx_parcelle_statut ON parcelle(statut);
        CREATE TRIGGER IF NOT EXISTS trg_parcelle_updated_at
            AFTER UPDATE ON parcelle
            FOR EACH ROW
            BEGIN
                UPDATE parcelle SET updated_at = datetime('now') WHERE id = NEW.id;
            END;
    """),
    (2, "create_plan_culture", """
        -- Plan de culture saisonnier : une culture sur une parcelle pour une année donnée.
        -- Multi-culture possible sur 1 parcelle (sous-surface ha) à condition que la somme
        -- soit ≤ surface parcelle (validation côté code, pas BDD pour souplesse).
        CREATE TABLE IF NOT EXISTS plan_culture (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parcelle_id INTEGER NOT NULL,
            saison INTEGER NOT NULL CHECK (saison >= 2020 AND saison <= 2100),
            culture TEXT NOT NULL,                   -- slug culture (chanvre_kompolti, maraichage_diversifie, verger_pommiers, etc.)
            culture_label TEXT,                      -- libellé lisible (ex: "Chanvre Kompolti")
            variete TEXT,                            -- variété précise (ex: "Kompolti FBS")
            surface_ha REAL CHECK (surface_ha IS NULL OR surface_ha > 0),
            date_semis_prev TEXT,                    -- ISO YYYY-MM-DD prévue
            date_recolte_prev TEXT,                  -- ISO YYYY-MM-DD prévue
            date_semis_reel TEXT,                    -- ISO YYYY-MM-DD constaté (post-semis)
            date_recolte_reel TEXT,                  -- ISO YYYY-MM-DD constaté
            rendement_kg_attendu REAL,
            mode_production TEXT DEFAULT 'ab' CHECK (mode_production IN ('ab','nt','conv','hve')),
            statut TEXT NOT NULL DEFAULT 'prevu' CHECK (statut IN ('prevu','en_cours','recolte','annule')),
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (parcelle_id) REFERENCES parcelle(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_plan_culture_saison ON plan_culture(saison);
        CREATE INDEX IF NOT EXISTS idx_plan_culture_parcelle ON plan_culture(parcelle_id);
        CREATE INDEX IF NOT EXISTS idx_plan_culture_statut ON plan_culture(statut);
        CREATE TRIGGER IF NOT EXISTS trg_plan_culture_updated_at
            AFTER UPDATE ON plan_culture
            FOR EACH ROW
            BEGIN
                UPDATE plan_culture SET updated_at = datetime('now') WHERE id = NEW.id;
            END;
    """),
]


def _ensure_schema() -> None:
    """Crée paresseusement le schéma de la verticale (parcelle/plan_culture).

    Appelé au début de chaque opération CRUD. Tant que la verticale n'est pas
    sollicitée, ses tables ne sont jamais créées (noyau agnostique préservé).
    """
    apply_module_migrations("self_culture", CULTURE_MIGRATIONS)


# mode_production a un enum métier dédié → source de vérité = models.ModeProduction.
VALID_MODES_PRODUCTION = tuple(m.value for m in ModeProduction)
# Les statuts parcelle/plan n'ont pas d'enum (valeurs propres au schéma SQL) : ces
# littéraux reflètent les contraintes CHECK des tables parcelle.statut / plan_culture.statut
# (migrations create_parcelle / create_plan_culture) — pas d'enum inventé « au cas où ».
VALID_PARCELLE_STATUTS = ("bio", "conversion", "conventionnel")
VALID_PLAN_STATUTS = ("prevu", "en_cours", "recolte", "annule")

PARCELLE_FIELDS = (
    "nom", "ref_cadastrale", "commune", "code_postal",
    "surface_ha", "statut", "date_acquisition", "notes",
)
PLAN_CULTURE_FIELDS = (
    "parcelle_id", "saison", "culture", "culture_label", "variete",
    "surface_ha", "date_semis_prev", "date_recolte_prev",
    "date_semis_reel", "date_recolte_reel",
    "rendement_kg_attendu", "mode_production", "statut", "notes",
)


# ============================================================
# Catalogue variétés — couche typée self_culture.catalog
# ============================================================
# Source de vérité = data/varietes-references.yaml, chargé et validé en objets
# Pydantic `Variete` par catalog.load_catalog(). Un seul loader pour tout le module.


# Émojis indicatifs par famille botanique (visuel datalist)
FAMILLE_EMOJI = {
    "Solanaceae": "🍅",
    "Brassicaceae": "🥬",
    "Apiaceae": "🥕",
    "Amaryllidaceae": "🧅",
    "Fabaceae": "🌱",
    "Cucurbitaceae": "🥒",
    "Amaranthaceae": "🌿",
    "Asteraceae": "🥗",
    "Poaceae": "🌾",
    "Lamiaceae": "🌿",
    "Boraginaceae": "💜",
    "Polygonaceae": "🌾",
    "Cannabaceae": "🌿",
}


def get_varietes_for_datalist() -> list[dict[str, str]]:
    """Format optimisé pour balise <datalist> du formulaire.

    Chaque option a :
    - `value` : libellé affiché et stocké (ex: "🍅 Tomate Marmande (AB)")
    - `label_attr` : info hover (mois semis/récolte, famille)
    - `slug` : id technique (slug catalog, pour ref backend)
    """
    out = []
    for v in load_catalog():
        emoji = FAMILLE_EMOJI.get(v.famille.value, "•")
        mode_suffix = " (AB)" if v.mode_production_principal == ModeProduction.AB else ""
        cal = v.calendrier
        out.append({
            "value": f"{emoji} {v.nom_commun}{mode_suffix}",
            "label_attr": f"{v.famille.value} · semis {cal.semis_mois_min}-{cal.semis_mois_max} · récolte {cal.recolte_mois_min}-{cal.recolte_mois_max}",
            "slug": v.id,
            "famille": v.famille.value,
            "categorie": v.categorie.value,
        })
    # Tri par catégorie puis nom (regroupement visuel naturel)
    out.sort(key=lambda x: (x["categorie"], x["value"]))
    return out


# ============================================================
# CRUD Parcelle
# ============================================================

def list_parcelles() -> list[dict[str, Any]]:
    """Retourne toutes les parcelles, triées par nom."""
    _ensure_schema()
    with _conn() as c:
        rows = c.execute("SELECT * FROM parcelle ORDER BY nom").fetchall()
        return [dict(r) for r in rows]


def get_parcelle(parcelle_id: int) -> dict[str, Any] | None:
    _ensure_schema()
    with _conn() as c:
        row = c.execute("SELECT * FROM parcelle WHERE id = ?", (parcelle_id,)).fetchone()
        return dict(row) if row else None


def save_parcelle(data: dict[str, Any]) -> dict[str, Any]:
    """UPSERT parcelle. Si `id` présent dans data → UPDATE, sinon INSERT.

    Validation :
    - `nom` et `commune` obligatoires
    - `surface_ha` > 0
    - `statut` dans VALID_PARCELLE_STATUTS si fourni
    """
    _ensure_schema()

    # Validation
    if not data.get("nom") or not data.get("commune"):
        raise ValueError("save_parcelle : 'nom' et 'commune' requis")
    surface = data.get("surface_ha")
    if surface is None or float(surface) <= 0:
        raise ValueError("save_parcelle : 'surface_ha' doit être > 0")
    statut = data.get("statut")
    if statut and statut not in VALID_PARCELLE_STATUTS:
        raise ValueError(f"statut '{statut}' invalide — attendu {VALID_PARCELLE_STATUTS}")

    payload = {k: v for k, v in data.items() if k in PARCELLE_FIELDS}
    parcelle_id = data.get("id")

    with _conn() as c:
        if parcelle_id:
            # UPDATE
            set_clause = ", ".join(f"{k} = ?" for k in payload)
            c.execute(
                f"UPDATE parcelle SET {set_clause} WHERE id = ?",
                list(payload.values()) + [parcelle_id],
            )
            log.info("Parcelle #%s mise à jour : %s", parcelle_id, payload.get("nom"))
            return get_parcelle(parcelle_id)
        else:
            # INSERT
            cols = ", ".join(payload.keys())
            placeholders = ", ".join("?" for _ in payload)
            cursor = c.execute(
                f"INSERT INTO parcelle ({cols}) VALUES ({placeholders})",
                list(payload.values()),
            )
            new_id = cursor.lastrowid
            log.info("Parcelle créée #%s : %s", new_id, payload.get("nom"))
            return get_parcelle(new_id)


def rename_parcelle(parcelle_id: int, new_nom: str) -> dict[str, Any] | None:
    """Renomme une parcelle. Le nom doit être non vide après strip."""
    _ensure_schema()
    new_nom = (new_nom or "").strip()
    if not new_nom:
        raise ValueError("rename_parcelle : le nom ne peut pas être vide")
    with _conn() as c:
        cursor = c.execute(
            "UPDATE parcelle SET nom = ?, updated_at = datetime('now') WHERE id = ?",
            (new_nom, parcelle_id),
        )
        if cursor.rowcount == 0:
            return None
        log.info("Parcelle #%s renommée → %s", parcelle_id, new_nom)
    return get_parcelle(parcelle_id)


def delete_parcelle(parcelle_id: int) -> bool:
    """Supprime une parcelle (cascade → plans de culture liés).
    Retourne True si la ligne existait.
    """
    _ensure_schema()
    with _conn() as c:
        cursor = c.execute("DELETE FROM parcelle WHERE id = ?", (parcelle_id,))
        return cursor.rowcount > 0


# ============================================================
# CRUD Plan de culture
# ============================================================

def list_plan_culture(saison: int | None = None, parcelle_id: int | None = None) -> list[dict[str, Any]]:
    """Liste les plans de culture, filtres optionnels saison et parcelle.

    Joint la parcelle pour avoir le nom + commune dans le retour.
    """
    _ensure_schema()
    sql = """
        SELECT pc.*, p.nom AS parcelle_nom, p.commune AS parcelle_commune
        FROM plan_culture pc
        JOIN parcelle p ON p.id = pc.parcelle_id
        WHERE 1=1
    """
    params: list[Any] = []
    if saison is not None:
        sql += " AND pc.saison = ?"
        params.append(saison)
    if parcelle_id is not None:
        sql += " AND pc.parcelle_id = ?"
        params.append(parcelle_id)
    sql += " ORDER BY p.nom, pc.date_semis_prev"

    with _conn() as c:
        rows = c.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def get_plan_culture(plan_id: int) -> dict[str, Any] | None:
    _ensure_schema()
    with _conn() as c:
        row = c.execute("SELECT * FROM plan_culture WHERE id = ?", (plan_id,)).fetchone()
        return dict(row) if row else None


def save_plan_culture(data: dict[str, Any]) -> dict[str, Any]:
    """UPSERT plan_culture.

    Validation :
    - `parcelle_id` doit pointer vers une parcelle existante
    - `saison` entier 2020-2100
    - `culture` obligatoire (texte libre ou slug catalog)
    """
    _ensure_schema()

    if not data.get("parcelle_id"):
        raise ValueError("save_plan_culture : 'parcelle_id' requis")
    if not data.get("saison"):
        raise ValueError("save_plan_culture : 'saison' requis")
    if not data.get("culture"):
        raise ValueError("save_plan_culture : 'culture' requis (libellé ou slug)")

    # Validation FK parcelle
    if not get_parcelle(int(data["parcelle_id"])):
        raise ValueError(f"Parcelle #{data['parcelle_id']} introuvable")

    statut = data.get("statut")
    if statut and statut not in VALID_PLAN_STATUTS:
        raise ValueError(f"statut '{statut}' invalide — attendu {VALID_PLAN_STATUTS}")

    mode = data.get("mode_production")
    if mode and mode not in VALID_MODES_PRODUCTION:
        raise ValueError(f"mode_production '{mode}' invalide")

    payload = {k: v for k, v in data.items() if k in PLAN_CULTURE_FIELDS}
    plan_id = data.get("id")

    with _conn() as c:
        if plan_id:
            set_clause = ", ".join(f"{k} = ?" for k in payload)
            c.execute(
                f"UPDATE plan_culture SET {set_clause} WHERE id = ?",
                list(payload.values()) + [plan_id],
            )
            log.info("Plan_culture #%s mis à jour : %s", plan_id, payload.get("culture"))
            return get_plan_culture(plan_id)
        else:
            cols = ", ".join(payload.keys())
            placeholders = ", ".join("?" for _ in payload)
            cursor = c.execute(
                f"INSERT INTO plan_culture ({cols}) VALUES ({placeholders})",
                list(payload.values()),
            )
            new_id = cursor.lastrowid
            log.info("Plan_culture créé #%s : %s sur parcelle %s",
                     new_id, payload.get("culture"), payload.get("parcelle_id"))
            return get_plan_culture(new_id)


def delete_plan_culture(plan_id: int) -> bool:
    _ensure_schema()
    with _conn() as c:
        cursor = c.execute("DELETE FROM plan_culture WHERE id = ?", (plan_id,))
        return cursor.rowcount > 0


# ============================================================
# Helpers agrégation pour dashboard
# ============================================================

def stats_parcelles_saison(saison: int) -> dict[str, Any]:
    """Stats agrégées pour le dashboard : nombre, surface totale, par culture, par statut.

    Retour :
        {
            "count": 7,
            "surface_total_ha": 4.32,
            "par_statut": {"bio": 3, "conversion": 4, "conventionnel": 0},
            "par_culture": [{"label": "Chanvre Kompolti", "surface_ha": 1.2}, ...]
        }
    """
    _ensure_schema()
    with _conn() as c:
        parcelles = c.execute(
            "SELECT statut, surface_ha FROM parcelle"
        ).fetchall()
        plans = c.execute(
            "SELECT culture_label, culture, SUM(surface_ha) AS surface "
            "FROM plan_culture WHERE saison = ? AND statut != 'annule' "
            "GROUP BY COALESCE(culture_label, culture)",
            (saison,),
        ).fetchall()

    par_statut: dict[str, int] = {}
    surface_total = 0.0
    for p in parcelles:
        par_statut[p["statut"]] = par_statut.get(p["statut"], 0) + 1
        surface_total += p["surface_ha"] or 0

    par_culture = [
        {
            "label": r["culture_label"] or r["culture"],
            "surface_ha": round(r["surface"] or 0, 2),
        }
        for r in plans
    ]

    return {
        "count": len(parcelles),
        "surface_total_ha": round(surface_total, 2),
        "par_statut": par_statut,
        "par_culture": par_culture,
    }
