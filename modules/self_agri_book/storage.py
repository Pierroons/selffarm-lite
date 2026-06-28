"""
Storage SQLite pour le hub compta self_agri_book.

Table unique `ecritures_comptables` — hub central qui reçoit les auto-écritures
depuis tous les modules métier (self_invoice, self_banking, self_achats, ...).

Principe de simplicité : pas d'ORM (SQLAlchemy est dans le venv mais pas nécessaire
pour un schéma aussi plat). sqlite3 stdlib suffit.
"""

from __future__ import annotations

import hashlib
import json as _json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

log = logging.getLogger("self_agri_book.storage")

# Localisation base SQLite : var XDG ou défaut /opt/selffarm-lite/data/compta.db
DEFAULT_DB_DIR = Path(os.environ.get("SELFFARM_DATA_DIR", str(Path.home() / ".selffarm")))
DEFAULT_DB_PATH = DEFAULT_DB_DIR / "compta.db"


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ecritures_comptables (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    date_operation TEXT NOT NULL,
    journal TEXT NOT NULL,
    numero_piece TEXT NOT NULL,
    libelle TEXT NOT NULL,
    compte_debit TEXT NOT NULL,
    compte_credit TEXT NOT NULL,
    montant_ht TEXT,
    montant_tva TEXT,
    montant_ttc TEXT NOT NULL,
    source_module TEXT,
    source_id TEXT,
    metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_ecritures_date ON ecritures_comptables(date_operation);
CREATE INDEX IF NOT EXISTS idx_ecritures_source ON ecritures_comptables(source_module, source_id);
CREATE INDEX IF NOT EXISTS idx_ecritures_compte_debit ON ecritures_comptables(compte_debit);
CREATE INDEX IF NOT EXISTS idx_ecritures_compte_credit ON ecritures_comptables(compte_credit);

CREATE TABLE IF NOT EXISTS _schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# Migrations versionnées — chaque entrée = (version, nom_descriptif, sql_a_executer)
# Schéma initial = version 0 (créée par SCHEMA_SQL ci-dessus). Toute évolution
# de schéma suivante DOIT être ajoutée ici en fin de liste, jamais modifiée.
MIGRATIONS: list[tuple[int, str, str]] = [
    (1, "create_compteurs_factures", """
        CREATE TABLE IF NOT EXISTS compteurs_factures (
            annee INTEGER NOT NULL,
            prefix TEXT NOT NULL DEFAULT 'F',
            dernier_numero INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (annee, prefix)
        );
        -- Initialise les compteurs depuis l'historique self_invoice existant
        -- (factures déjà émises en démo aléatoire) pour éviter les doublons
        INSERT OR REPLACE INTO compteurs_factures (annee, prefix, dernier_numero)
        SELECT
            CAST(SUBSTR(numero_piece, 3, 4) AS INTEGER) AS annee,
            'F' AS prefix,
            MAX(CAST(SUBSTR(numero_piece, 8) AS INTEGER)) AS dernier_numero
        FROM ecritures_comptables
        WHERE source_module = 'self_invoice'
          AND numero_piece LIKE 'F-%'
          AND LENGTH(numero_piece) >= 8
        GROUP BY annee
        HAVING annee IS NOT NULL AND annee >= 2020 AND annee <= 2100;
    """),
    (2, "add_hash_chain_and_lock", """
        ALTER TABLE ecritures_comptables ADD COLUMN hash_data TEXT;
        ALTER TABLE ecritures_comptables ADD COLUMN hash_previous TEXT;
        ALTER TABLE ecritures_comptables ADD COLUMN hash_pdf TEXT;
        ALTER TABLE ecritures_comptables ADD COLUMN locked INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE ecritures_comptables ADD COLUMN locked_at TEXT;
        CREATE INDEX IF NOT EXISTS idx_ecritures_locked ON ecritures_comptables(locked);
    """),
    (3, "create_audit_log", """
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL DEFAULT (datetime('now')),
            actor TEXT NOT NULL DEFAULT 'system',
            action TEXT NOT NULL,
            target_type TEXT,
            target_id TEXT,
            details_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_audit_target ON audit_log(target_type, target_id);
        -- Triggers append-only : refuse UPDATE et DELETE
        CREATE TRIGGER IF NOT EXISTS trg_audit_log_no_update
            BEFORE UPDATE ON audit_log
            BEGIN SELECT RAISE(ABORT, 'audit_log is append-only — UPDATE forbidden'); END;
        CREATE TRIGGER IF NOT EXISTS trg_audit_log_no_delete
            BEFORE DELETE ON audit_log
            BEGIN SELECT RAISE(ABORT, 'audit_log is append-only — DELETE forbidden'); END;
    """),
    (4, "create_exploitation", """
        -- Profil exploitation — single-row (id=1 toujours en V1 mono-exploitation)
        -- Saisi via le wizard d'onboarding au premier lancement.
        -- En V1.1+ : multi-exploitation possible via duplication ou switch profile.
        CREATE TABLE IF NOT EXISTS exploitation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL,
            initials TEXT,
            statut TEXT NOT NULL CHECK(statut IN ('JA','NA','AGRI','PME')),
            date_installation TEXT,            -- ISO YYYY-MM-DD (date de début JA pour compteur 5 ans)
            saison_courante INTEGER,           -- année en cours (ex: 2026)
            regime_fiscal TEXT CHECK(regime_fiscal IN ('franchise','micro_ba','reel_simplifie','reel_normal')),
            tva_assujetti INTEGER NOT NULL DEFAULT 0,
            siret TEXT,                        -- 14 chiffres, optionnel à l'install
            commune TEXT,
            code_postal TEXT,
            departement TEXT,                  -- code INSEE du département, 2 chiffres (ex: '01')
            productions TEXT,                  -- JSON array, ex: '["chanvre","maraichage","fruits"]'
            onboarding_done INTEGER NOT NULL DEFAULT 0,  -- 1 quand wizard validé
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        -- Trigger : maj automatique updated_at sur UPDATE
        CREATE TRIGGER IF NOT EXISTS trg_exploitation_updated_at
            AFTER UPDATE ON exploitation
            FOR EACH ROW
            BEGIN
                UPDATE exploitation SET updated_at = datetime('now') WHERE id = NEW.id;
            END;
    """),
    (5, "create_parcelle", """
        -- Parcelles déclarées de l'exploitation.
        -- V1 simple, sans planches/zones (sera enrichi V2 via module self_culture complet).
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
        -- Trigger maj updated_at
        CREATE TRIGGER IF NOT EXISTS trg_parcelle_updated_at
            AFTER UPDATE ON parcelle
            FOR EACH ROW
            BEGIN
                UPDATE parcelle SET updated_at = datetime('now') WHERE id = NEW.id;
            END;
    """),
    (6, "create_plan_culture", """
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
    (7, "create_pos_produit", """
        -- SelfPOS — Catalogue produits (vente directe marché)
        CREATE TABLE IF NOT EXISTS pos_produit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL,
            prix_unitaire REAL NOT NULL CHECK (prix_unitaire >= 0),
            unite TEXT NOT NULL DEFAULT 'pièce',
            categorie TEXT,
            emoji TEXT,
            actif INTEGER NOT NULL DEFAULT 1,
            ordre INTEGER DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_pos_produit_actif ON pos_produit(actif);
    """),
    (8, "create_pos_session", """
        -- SelfPOS — Session de marché (1 session = 1 journée typique)
        CREATE TABLE IF NOT EXISTS pos_session (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date_marche TEXT NOT NULL,
            lieu TEXT NOT NULL,
            statut TEXT NOT NULL DEFAULT 'ouverte' CHECK (statut IN ('ouverte','cloturee')),
            total_ttc REAL NOT NULL DEFAULT 0,
            total_especes REAL NOT NULL DEFAULT 0,
            total_cb REAL NOT NULL DEFAULT 0,
            total_cheque REAL NOT NULL DEFAULT 0,
            nb_ventes INTEGER NOT NULL DEFAULT 0,
            ecriture_id INTEGER,
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            cloture_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_pos_session_statut ON pos_session(statut);
        CREATE INDEX IF NOT EXISTS idx_pos_session_date ON pos_session(date_marche);
    """),
    (9, "create_pos_vente", """
        -- SelfPOS — Vente individuelle attachée à une session
        CREATE TABLE IF NOT EXISTS pos_vente (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            lignes_json TEXT NOT NULL,
            total_ttc REAL NOT NULL CHECK (total_ttc >= 0),
            mode_paiement TEXT NOT NULL CHECK (mode_paiement IN ('especes','cb','cheque','mixte')),
            details_paiement_json TEXT,
            client_libelle TEXT,
            offline_uuid TEXT UNIQUE,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (session_id) REFERENCES pos_session(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_pos_vente_session ON pos_vente(session_id);
        CREATE INDEX IF NOT EXISTS idx_pos_vente_offline ON pos_vente(offline_uuid);
    """),
    (10, "create_pos_chargement", """
        -- SelfPOS V0.3 — Chargement camion préparé avant un marché
        CREATE TABLE IF NOT EXISTS pos_chargement (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            produit_id INTEGER,
            produit_nom TEXT NOT NULL,
            unite TEXT NOT NULL DEFAULT 'pièce',
            quantite_chargee REAL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (session_id) REFERENCES pos_session(id) ON DELETE CASCADE,
            FOREIGN KEY (produit_id) REFERENCES pos_produit(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_pos_chargement_session ON pos_chargement(session_id);
    """),
    (11, "create_pos_residu_marche", """
        -- SelfPOS V0.3 — Résidu de marché : stock / invendu / transferé / hors-marché
        CREATE TABLE IF NOT EXISTS pos_residu_marche (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            produit_id INTEGER,
            produit_nom TEXT NOT NULL,
            unite TEXT NOT NULL DEFAULT 'pièce',
            quantite REAL NOT NULL CHECK (quantite >= 0),
            status TEXT NOT NULL CHECK (status IN ('stock','invendu','transfere','consomme_hors_marche')),
            destination TEXT,
            derniere_revue_at TEXT NOT NULL DEFAULT (datetime('now')),
            next_session_id INTEGER,
            archive INTEGER NOT NULL DEFAULT 0,
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (session_id) REFERENCES pos_session(id) ON DELETE CASCADE,
            FOREIGN KEY (produit_id) REFERENCES pos_produit(id) ON DELETE SET NULL,
            FOREIGN KEY (next_session_id) REFERENCES pos_session(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_pos_residu_session ON pos_residu_marche(session_id);
        CREATE INDEX IF NOT EXISTS idx_pos_residu_status ON pos_residu_marche(status, archive);
    """),
    (12, "create_pos_planning_marche", """
        -- SelfPOS V0.3 — Marchés récurrents planifiés + config rappels
        CREATE TABLE IF NOT EXISTS pos_planning_marche (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL,
            lieu TEXT NOT NULL,
            recurrence TEXT NOT NULL DEFAULT 'hebdo' CHECK (recurrence IN ('hebdo','bihebdo','mensuel','ponctuel')),
            jour_semaine INTEGER,
            heure_debut TEXT,
            heure_fin TEXT,
            rappel_chargement_jours INTEGER NOT NULL DEFAULT 1,
            rappel_jour_marche INTEGER NOT NULL DEFAULT 1,
            active INTEGER NOT NULL DEFAULT 1,
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_pos_planning_active ON pos_planning_marche(active);
    """),
    (13, "create_pos_point_vente_collectif", """
        -- SelfPOS V0.3 — Point de vente collectif (magasin producteurs, Coccinelle Bio etc.)
        CREATE TABLE IF NOT EXISTS pos_point_vente_collectif (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL,
            adresse TEXT,
            convention TEXT NOT NULL DEFAULT 'depot_vente' CHECK (convention IN ('depot_vente','achat_direct')),
            commission_pct REAL,
            jour_recap INTEGER,
            contact TEXT,
            notes TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_pos_collectif_active ON pos_point_vente_collectif(active);
    """),
    (14, "extend_pos_session_type", """
        -- SelfPOS V0.3 — Distinction type de session (marché ponctuel vs point vente collectif)
        ALTER TABLE pos_session ADD COLUMN type_vente TEXT NOT NULL DEFAULT 'marche_ponctuel';
        ALTER TABLE pos_session ADD COLUMN point_vente_id INTEGER REFERENCES pos_point_vente_collectif(id) ON DELETE SET NULL;
        CREATE INDEX IF NOT EXISTS idx_pos_session_type ON pos_session(type_vente);
    """),
    (15, "add_modules_state", """
        -- Système de modes/modules (lite/full/perso) — cf project_selffarm_modes_modulaires.
        -- modules_actifs : JSON array d'ids de modules actifs. NULL = pas encore configuré
        --   (fallback côté code : tous les modules 'live' actifs).
        -- view_mode : 'mine' (mes modules) | 'full' (vue complète, modules à venir grisés).
        ALTER TABLE exploitation ADD COLUMN modules_actifs TEXT;
        ALTER TABLE exploitation ADD COLUMN view_mode TEXT;
    """),
    (16, "create_ledger_outbox", """
        -- Journal append-only des événements immuables du ledger (compta + facturation).
        -- Réplication continue vers les supports (DD/NAS/mobile) = sauvegarde temps réel
        -- du ledger (RPO≈0). seq = compteur de génération monotone (cf anti-rétrogradage).
        -- Append-only : jamais de UPDATE/DELETE d'un événement ; seul replicated_to évolue.
        CREATE TABLE IF NOT EXISTS ledger_outbox (
            seq           INTEGER PRIMARY KEY AUTOINCREMENT,
            created_utc   TEXT NOT NULL,
            event_type    TEXT NOT NULL,                 -- 'ecriture' | 'facture'
            ecriture_id   INTEGER,                       -- lien vers ecritures_comptables.id
            numero_piece  TEXT,
            hash_data     TEXT,                          -- empreinte stable de l'écriture
            payload_json  TEXT NOT NULL,                 -- contenu canonical de l'événement
            replicated_to TEXT NOT NULL DEFAULT '[]'     -- JSON array d'ids de supports
        );
    """),
]


def _apply_migrations() -> None:
    """Applique les migrations manquantes. Idempotent.

    Stratégie : version 0 = schéma initial (déjà créé via SCHEMA_SQL).
    Versions ≥ 1 sont des évolutions à appliquer dans l'ordre, une seule fois.
    """
    with _conn() as c:
        applied = {
            int(r["version"])
            for r in c.execute("SELECT version FROM _schema_migrations").fetchall()
        }
        for version, name, sql in MIGRATIONS:
            if version in applied:
                continue
            log.info("Application migration #%d : %s", version, name)
            c.executescript(sql)
            c.execute(
                "INSERT INTO _schema_migrations (version, name) VALUES (?, ?)",
                (version, name),
            )


def _db_path() -> Path:
    return Path(os.environ.get("SELFFARM_COMPTA_DB", str(DEFAULT_DB_PATH)))


@contextmanager
def _conn():
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), isolation_level=None)  # autocommit
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    """Crée la DB + schéma si absents puis applique les migrations. Idempotent."""
    with _conn() as c:
        c.executescript(SCHEMA_SQL)
    _apply_migrations()
    log.info("Compta DB initialisée : %s", _db_path())


def next_numero_facture(annee: int, prefix: str = "F") -> str:
    """Retourne le prochain numéro de facture séquentiel pour (annee, prefix).

    Atomique : SELECT + UPDATE en transaction SQLite (row-level lock).
    Ex: next_numero_facture(2026) → "F-2026-0001", puis "F-2026-0002", etc.

    Conformité CGI art. 289-II : numérotation séquentielle continue, sans saut.
    Le compteur ne décrémente jamais. Pour annuler une facture → émettre un avoir
    avec préfixe distinct (ex: AV-2026-0001).
    """
    init_db()
    with _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        try:
            row = c.execute(
                "SELECT dernier_numero FROM compteurs_factures WHERE annee=? AND prefix=?",
                (annee, prefix),
            ).fetchone()
            current = row["dernier_numero"] if row else 0
            new_num = current + 1
            if row:
                c.execute(
                    "UPDATE compteurs_factures SET dernier_numero=?, updated_at=datetime('now') "
                    "WHERE annee=? AND prefix=?",
                    (new_num, annee, prefix),
                )
            else:
                c.execute(
                    "INSERT INTO compteurs_factures (annee, prefix, dernier_numero) VALUES (?, ?, ?)",
                    (annee, prefix, new_num),
                )
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise
    # Format 4 chiffres mini, extensible auto si > 9999/an
    width = max(4, len(str(new_num)))
    return f"{prefix}-{annee}-{new_num:0{width}d}"


def peek_numero_facture(annee: int, prefix: str = "F") -> str:
    """Retourne le prochain numéro SANS l'incrémenter (preview pour le form)."""
    init_db()
    with _conn() as c:
        row = c.execute(
            "SELECT dernier_numero FROM compteurs_factures WHERE annee=? AND prefix=?",
            (annee, prefix),
        ).fetchone()
    current = row["dernier_numero"] if row else 0
    new_num = current + 1
    width = max(4, len(str(new_num)))
    return f"{prefix}-{annee}-{new_num:0{width}d}"


def find_ecriture_by_source(source_module: str, source_id: str) -> dict | None:
    """Retourne l'écriture existante si source_module+source_id déjà saisie, None sinon.

    Sert à garantir l'idempotence : une même facture F-2026-0042 ne génère
    qu'UNE seule écriture 411/701, même si la facture est re-ouverte/re-générée.
    """
    if not source_module or not source_id:
        return None
    init_db()
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM ecritures_comptables WHERE source_module=? AND source_id=? LIMIT 1",
            (source_module, source_id),
        ).fetchone()
    return dict(row) if row else None


def _compute_hash_data(payload: dict) -> str:
    """Hash SHA256 d'un payload canonical JSON (clés triées, encodage déterministe)."""
    canonical = _json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _last_hash_chain() -> str:
    """Récupère le hash_data de la dernière écriture insérée (chaîne)."""
    with _conn() as c:
        row = c.execute(
            "SELECT hash_data FROM ecritures_comptables ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return row["hash_data"] if row and row["hash_data"] else ""


def save_ecriture(
    *,
    date_operation: date,
    journal: str,
    numero_piece: str,
    libelle: str,
    compte_debit: str,
    compte_credit: str,
    montant_ttc: Decimal,
    montant_ht: Decimal | None = None,
    montant_tva: Decimal | None = None,
    source_module: str | None = None,
    source_id: str | None = None,
    metadata_json: str | None = None,
    hash_pdf: str | None = None,
    locked: bool = False,
    allow_duplicate: bool = False,
) -> tuple[int, bool]:
    """Insère une écriture avec chaînage cryptographique + verrouillage optionnel.

    Par défaut, si (source_module, source_id) existe déjà, l'écriture existante
    est renvoyée telle quelle (idempotence). Passer `allow_duplicate=True` force
    une nouvelle insertion même si doublon.

    Conformité PAF (CGI art. 289-VII) :
    - hash_data = SHA256 canonical JSON (clés triées) du contenu écriture
    - hash_previous = hash_data de la PRÉCÉDENTE écriture → chaîne immuable
    - locked = 1 → l'écriture est verrouillée, modifications futures interdites
    - audit_log = trace de l'action (hook write_audit)

    Retourne (ecriture_id, created_bool) :
        - created_bool = True → nouvelle écriture insérée
        - created_bool = False → écriture pré-existante retournée (dedup)
    """
    init_db()
    # Dédup : si source_module+source_id déjà présent, retourne l'existant
    if not allow_duplicate and source_module and source_id:
        existing = find_ecriture_by_source(source_module, source_id)
        if existing:
            log.info(
                "Écriture déjà présente pour source %s/%s (id=#%d) — dédup appliquée",
                source_module, source_id, existing["id"],
            )
            return existing["id"], False

    # Calcul du hash chaîne — payload canonical = données fonctionnelles, pas l'id
    hash_previous = _last_hash_chain()
    payload = {
        "date_operation": date_operation.isoformat(),
        "journal": journal,
        "numero_piece": numero_piece,
        "libelle": libelle,
        "compte_debit": compte_debit,
        "compte_credit": compte_credit,
        "montant_ht": str(montant_ht) if montant_ht is not None else None,
        "montant_tva": str(montant_tva) if montant_tva is not None else None,
        "montant_ttc": str(montant_ttc),
        "source_module": source_module,
        "source_id": source_id,
        "metadata_json": metadata_json,
        "hash_previous": hash_previous,
    }
    hash_data = _compute_hash_data(payload)
    locked_at = datetime.now().isoformat() if locked else None

    with _conn() as c:
        cur = c.execute(
            """
            INSERT INTO ecritures_comptables
                (date_operation, journal, numero_piece, libelle,
                 compte_debit, compte_credit,
                 montant_ht, montant_tva, montant_ttc,
                 source_module, source_id, metadata_json,
                 hash_data, hash_previous, hash_pdf, locked, locked_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                date_operation.isoformat(),
                journal,
                numero_piece,
                libelle,
                compte_debit,
                compte_credit,
                str(montant_ht) if montant_ht is not None else None,
                str(montant_tva) if montant_tva is not None else None,
                str(montant_ttc),
                source_module,
                source_id,
                metadata_json,
                hash_data,
                hash_previous,
                hash_pdf,
                1 if locked else 0,
                locked_at,
            ),
        )
        ecriture_id = cur.lastrowid

    write_audit(
        action="ecriture.create",
        target_type="ecriture",
        target_id=str(ecriture_id),
        details={
            "numero_piece": numero_piece,
            "compte_debit": compte_debit,
            "compte_credit": compte_credit,
            "montant_ttc": str(montant_ttc),
            "source_module": source_module,
            "locked": locked,
            "hash_data": hash_data,
        },
    )
    log.info(
        "Écriture #%d saisie : %s %s %s → %s / %s [hash %s]",
        ecriture_id, numero_piece, compte_debit, montant_ttc, compte_credit,
        libelle[:40], hash_data[:12],
    )
    # Journal append-only du ledger (outbox) — réplication continue (Partie E).
    # Best-effort : NE DOIT JAMAIS bloquer une écriture comptable (la DB fait foi).
    try:
        from self_agri_book.outbox import append_event
        append_event(
            event_type="facture" if (numero_piece or "").startswith("F-") else "ecriture",
            payload=payload,
            hash_data=hash_data,
            ecriture_id=ecriture_id,
            numero_piece=numero_piece,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("Outbox append échoué (non bloquant) : %s", e)
    return ecriture_id, True


def lock_ecriture(ecriture_id: int) -> bool:
    """Verrouille une écriture (locked=1). Retourne True si modifié, False sinon.

    Une écriture verrouillée est immutable :
    - lock_ecriture sur une écriture déjà locked → no-op (False)
    - Toute tentative de modif/suppression doit être rejetée par les routes
    - Pour annuler : émettre un avoir (compte 709), ne PAS unlock
    """
    init_db()
    with _conn() as c:
        row = c.execute(
            "SELECT locked FROM ecritures_comptables WHERE id=?", (ecriture_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"Écriture #{ecriture_id} introuvable")
        if row["locked"]:
            return False
        c.execute(
            "UPDATE ecritures_comptables SET locked=1, locked_at=datetime('now') WHERE id=?",
            (ecriture_id,),
        )
    write_audit(
        action="ecriture.lock",
        target_type="ecriture",
        target_id=str(ecriture_id),
        details={"locked_at": datetime.now().isoformat()},
    )
    return True


def write_audit(
    *,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    actor: str = "system",
    details: dict | None = None,
) -> int:
    """Enregistre une entrée dans l'audit log (append-only, triggers SQLite).

    Tentative de UPDATE/DELETE sur audit_log → erreur SQLite (trigger ABORT).
    Permet de prouver à un contrôleur DGFIP qu'aucune action n'a été effacée.
    """
    init_db()
    details_json = _json.dumps(details, sort_keys=True, default=str) if details else None
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO audit_log (actor, action, target_type, target_id, details_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (actor, action, target_type, target_id, details_json),
        )
        return cur.lastrowid


def verify_chain() -> dict:
    """Vérifie l'intégrité de la chaîne cryptographique des écritures.

    Recalcule chaque hash_data et vérifie le lien hash_previous → hash_data
    de la précédente. Retourne :
    {
        valid: bool,
        nb_ecritures: int,
        nb_locked: int,
        broken_at: int | None,  (id de la première écriture cassée)
        reason: str | None,
    }
    """
    init_db()
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM ecritures_comptables ORDER BY id ASC"
        ).fetchall()
    if not rows:
        return {"valid": True, "nb_ecritures": 0, "nb_locked": 0, "broken_at": None, "reason": None}

    nb_locked = 0
    expected_previous = ""
    for r in rows:
        if r["locked"]:
            nb_locked += 1
        # Recalcule le hash attendu
        payload = {
            "date_operation": r["date_operation"],
            "journal": r["journal"],
            "numero_piece": r["numero_piece"],
            "libelle": r["libelle"],
            "compte_debit": r["compte_debit"],
            "compte_credit": r["compte_credit"],
            "montant_ht": r["montant_ht"],
            "montant_tva": r["montant_tva"],
            "montant_ttc": r["montant_ttc"],
            "source_module": r["source_module"],
            "source_id": r["source_id"],
            "metadata_json": r["metadata_json"],
            "hash_previous": r["hash_previous"] or "",
        }
        expected_hash = _compute_hash_data(payload)

        if r["hash_data"] is None:
            # Écriture pré-migration #2 : skip vérif chaîne, OK rétrocompat
            expected_previous = r["hash_data"] or ""
            continue
        if r["hash_data"] != expected_hash:
            return {
                "valid": False,
                "nb_ecritures": len(rows),
                "nb_locked": nb_locked,
                "broken_at": r["id"],
                "reason": f"hash_data ne correspond pas — écriture #{r['id']} a été modifiée",
            }
        if r["hash_previous"] != expected_previous:
            return {
                "valid": False,
                "nb_ecritures": len(rows),
                "nb_locked": nb_locked,
                "broken_at": r["id"],
                "reason": f"chaîne brisée — écriture #{r['id']} pointe vers un hash_previous incorrect",
            }
        expected_previous = r["hash_data"]

    return {
        "valid": True,
        "nb_ecritures": len(rows),
        "nb_locked": nb_locked,
        "broken_at": None,
        "reason": None,
    }


def list_audit_log(limit: int = 100) -> list[dict]:
    """Retourne les dernières entrées de l'audit log (desc)."""
    init_db()
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def list_ecritures(
    *,
    limit: int = 200,
    source_module: str | None = None,
    compte: str | None = None,
) -> list[dict]:
    """Retourne les écritures récentes (triées desc), éventuellement filtrées."""
    init_db()
    sql = "SELECT * FROM ecritures_comptables WHERE 1=1"
    params: list = []
    if source_module:
        sql += " AND source_module = ?"
        params.append(source_module)
    if compte:
        sql += " AND (compte_debit = ? OR compte_credit = ?)"
        params.extend([compte, compte])
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with _conn() as c:
        rows = c.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def balance_par_compte(limit: int = 50) -> list[dict]:
    """Somme débit/crédit par compte sur toute la période."""
    init_db()
    with _conn() as c:
        rows = c.execute(
            """
            SELECT compte, SUM(debit) AS total_debit, SUM(credit) AS total_credit
            FROM (
                SELECT compte_debit AS compte, CAST(montant_ttc AS REAL) AS debit, 0 AS credit
                FROM ecritures_comptables
                UNION ALL
                SELECT compte_credit AS compte, 0 AS debit, CAST(montant_ttc AS REAL) AS credit
                FROM ecritures_comptables
            )
            GROUP BY compte
            ORDER BY compte
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def stats_globales() -> dict:
    """Retourne quelques stats pour le dashboard /compta."""
    init_db()
    with _conn() as c:
        nb = c.execute("SELECT COUNT(*) AS n FROM ecritures_comptables").fetchone()["n"]
        total = c.execute(
            "SELECT COALESCE(SUM(CAST(montant_ttc AS REAL)), 0) AS t FROM ecritures_comptables"
        ).fetchone()["t"]
        by_src = c.execute(
            """
            SELECT source_module, COUNT(*) AS n
            FROM ecritures_comptables
            GROUP BY source_module
            """
        ).fetchall()
    return {
        "nb_ecritures": nb,
        "total_volume": total,
        "par_source": {r["source_module"] or "manuel": r["n"] for r in by_src},
    }


def reset_demo() -> None:
    """Purge la table — utile pour reset la démo publique."""
    init_db()
    with _conn() as c:
        c.execute("DELETE FROM ecritures_comptables")
    log.warning("Compta DB purgée (reset démo)")


# ---------------- Bilan / Compte de résultat ----------------

def _soldes_par_compte() -> dict[str, dict]:
    """Retourne un dict {code_compte: {debit, credit, solde}}.

    Solde = débit − crédit (positif = solde débiteur = actif ; négatif = créditeur = passif).
    """
    rows = balance_par_compte(limit=500)
    out = {}
    for r in rows:
        d = float(r["total_debit"] or 0)
        c = float(r["total_credit"] or 0)
        out[r["compte"]] = {
            "debit": d,
            "credit": c,
            "solde": d - c,
        }
    return out


def resultat_data() -> dict:
    """Compte de résultat simplifié.

    Classe 7 (crédit − débit) = produits.
    Classe 6 (débit − crédit) = charges.
    Résultat = produits − charges.
    """
    soldes = _soldes_par_compte()

    produits: list[dict] = []
    charges: list[dict] = []
    total_produits = 0.0
    total_charges = 0.0

    for code, data in sorted(soldes.items()):
        if not code:
            continue
        classe = code[0]
        if classe == "7":
            # Produits : solde normal = créditeur → on prend (credit - debit)
            montant = data["credit"] - data["debit"]
            if abs(montant) > 0.001:
                produits.append({"compte": code, "montant": montant})
                total_produits += montant
        elif classe == "6":
            # Charges : solde normal = débiteur → (debit - credit)
            montant = data["debit"] - data["credit"]
            if abs(montant) > 0.001:
                charges.append({"compte": code, "montant": montant})
                total_charges += montant

    resultat = total_produits - total_charges

    return {
        "produits": produits,
        "charges": charges,
        "total_produits": total_produits,
        "total_charges": total_charges,
        "resultat_net": resultat,
        "is_benefice": resultat >= 0,
    }


def export_fec(siren: str = "000000000") -> tuple[str, str]:
    """Export FEC DGFIP conforme BOI-CF-IOR-60-40-10 (art. L47 A-I LPF).

    Retourne (filename, contenu_tsv).
    18 colonnes tab-separated, encodage UTF-8, une ligne par ligne d'écriture.

    Source : https://bofip.impots.gouv.fr/bofip/9028-PGP.html/identifiant%3DBOI-CF-IOR-60-40-10-20181003

    Colonnes FEC obligatoires :
      1  JournalCode   code alpha journal (VEN, ACH, BQ, OD, AN)
      2  JournalLib    libellé journal
      3  EcritureNum   numéro séquentiel chrono
      4  EcritureDate  date comptabilisation YYYYMMDD
      5  CompteNum     n° compte PCG
      6  CompteLib     libellé compte
      7  CompAuxNum    n° compte auxiliaire (tiers) — optionnel
      8  CompAuxLib    libellé compte auxiliaire
      9  PieceRef      référence pièce (n° facture...)
     10  PieceDate     date pièce YYYYMMDD
     11  EcritureLib   libellé écriture
     12  Debit         montant débit (ou 0,00) format 0,00
     13  Credit        montant crédit (ou 0,00)
     14  EcritureLet   lettrage
     15  DateLet       date lettrage
     16  ValidDate     date validation écriture (YYYYMMDD)
     17  Montantdevise montant devise étrangère
     18  Idevise       code ISO devise
    """
    init_db()

    # Libellés comptes (enrichissement — doit être passé depuis l'appelant normalement)
    # Ici on re-déclare les libellés principaux pour auto-suffisance.
    LIBELLES = {
        "411": "Clients",
        "401": "Fournisseurs",
        "512": "Banque",
        "530": "Caisse",
        "701": "Ventes de produits finis",
        "707": "Ventes de marchandises",
        "6011": "Achats de matières premières - Semences",
        "6012": "Achats de matières premières - Engrais",
        "6013": "Achats de matières premières - Phyto",
        "6014": "Achats de matières premières - Aliments bétail",
        "6061": "Achats fournitures non stockables (emballages)",
        "6062": "Achats carburant et lubrifiants",
        "6132": "Locations immobilières (fermage)",
        "613": "Locations",
        "615": "Entretien et réparations",
        "616": "Primes d'assurance",
        "622": "Rémunérations d'intermédiaires et honoraires",
        "6262": "Frais de télécommunication",
        "6271": "Services bancaires",
        "6281": "Cotisations syndicales et professionnelles",
        "6451": "Cotisations MSA",
        "74": "Subventions d'exploitation",
        "164": "Emprunts auprès des établissements de crédit",
        "44571": "TVA collectée",
        "44566": "TVA déductible sur autres biens et services",
        "2154": "Matériel agricole",
        "2184": "Mobilier",
    }
    JOURNAUX = {
        "VEN": "Ventes",
        "ACH": "Achats",
        "BQ": "Banque",
        "CA": "Caisse",
        "OD": "Opérations diverses",
        "AN": "À nouveaux",
    }

    with _conn() as c:
        rows = c.execute(
            """
            SELECT id, date_operation, journal, numero_piece, libelle,
                   compte_debit, compte_credit,
                   montant_ht, montant_tva, montant_ttc,
                   source_module, source_id, created_at
            FROM ecritures_comptables
            ORDER BY date_operation ASC, id ASC
            """
        ).fetchall()

    # Header 18 colonnes
    header = [
        "JournalCode", "JournalLib", "EcritureNum", "EcritureDate",
        "CompteNum", "CompteLib", "CompAuxNum", "CompAuxLib",
        "PieceRef", "PieceDate", "EcritureLib",
        "Debit", "Credit", "EcritureLet", "DateLet", "ValidDate",
        "Montantdevise", "Idevise",
    ]
    lines = ["\t".join(header)]

    def _fmt_date(iso_str: str) -> str:
        # YYYY-MM-DD[THH:MM:SS] → YYYYMMDD
        return (iso_str or "")[:10].replace("-", "")

    def _fmt_montant(val) -> str:
        # 12.34 → "12,34" (format FEC : virgule décimale)
        if val is None or val == "":
            return "0,00"
        try:
            return f"{Decimal(str(val)).quantize(Decimal('0.01'))}".replace(".", ",")
        except Exception:
            return "0,00"

    for r in rows:
        date_op_fec = _fmt_date(r["date_operation"])
        valid_date_fec = _fmt_date(r["created_at"])
        journal_code = r["journal"] or "OD"
        journal_lib = JOURNAUX.get(journal_code, journal_code)

        # 1 écriture compta = 2 lignes FEC : la ligne débit + la ligne crédit
        # Ligne débit : compte au débit, montant en colonne Debit
        lines.append("\t".join([
            journal_code,
            journal_lib,
            f"E{r['id']:06d}",             # EcritureNum zero-padded
            date_op_fec,
            r["compte_debit"] or "",
            LIBELLES.get(r["compte_debit"], r["compte_debit"] or ""),
            "",                             # CompAuxNum (non géré)
            "",                             # CompAuxLib
            r["numero_piece"] or "",
            date_op_fec,                    # PieceDate = date op
            (r["libelle"] or "").replace("\t", " ").replace("\n", " "),
            _fmt_montant(r["montant_ttc"]),
            "0,00",
            "",                             # EcritureLet (lettrage manuel)
            "",                             # DateLet
            valid_date_fec,
            "",                             # Montantdevise
            "",                             # Idevise (vide = EUR par défaut)
        ]))
        # Ligne crédit
        lines.append("\t".join([
            journal_code,
            journal_lib,
            f"E{r['id']:06d}",
            date_op_fec,
            r["compte_credit"] or "",
            LIBELLES.get(r["compte_credit"], r["compte_credit"] or ""),
            "",
            "",
            r["numero_piece"] or "",
            date_op_fec,
            (r["libelle"] or "").replace("\t", " ").replace("\n", " "),
            "0,00",
            _fmt_montant(r["montant_ttc"]),
            "",
            "",
            valid_date_fec,
            "",
            "",
        ]))

    contenu = "\n".join(lines) + "\n"

    # Nom fichier : <siren>FEC<AAAAMMJJ>.txt (convention DGFIP)
    # Si pas de date fin d'exercice fournie, on prend today
    from datetime import date as _dt
    end_date = _dt.today().strftime("%Y%m%d")
    filename = f"{siren}FEC{end_date}.txt"

    log.info("Export FEC : %d lignes (%d écritures) → %s", len(lines) - 1, len(rows), filename)
    return filename, contenu


def bilan_data() -> dict:
    """Bilan simplifié : actif / passif groupés par grande rubrique PCG.

    Règle de classement :
    - Classe 2 (Immobilisations) → ACTIF
    - Classe 3 (Stocks) → ACTIF
    - Classe 4 : 411 créances → ACTIF ; 401 + 43x + 44571 dettes → PASSIF
      (affectation par solde : débiteur = actif, créditeur = passif)
    - Classe 5 (Financiers) → ACTIF (512 banque, 53 caisse)
    - Classe 1 (Capitaux, Emprunts) → PASSIF
    - Le résultat de l'exercice (produits − charges) va en PASSIF (capitaux propres)
    """
    soldes = _soldes_par_compte()
    res = resultat_data()

    actif_groupes: dict[str, list[dict]] = {
        "Immobilisations (classe 2)": [],
        "Stocks (classe 3)": [],
        "Créances clients (411/43 déductible)": [],
        "Disponibilités (classe 5)": [],
    }
    passif_groupes: dict[str, list[dict]] = {
        "Capitaux propres (classe 1 + résultat)": [],
        "Emprunts (164)": [],
        "Dettes fournisseurs (401)": [],
        "Dettes fiscales et sociales (43/44)": [],
    }

    total_actif = 0.0
    total_passif = 0.0

    for code, data in sorted(soldes.items()):
        if not code:
            continue
        classe = code[0]
        solde = data["solde"]
        if abs(solde) < 0.001:
            continue

        if classe == "2":
            actif_groupes["Immobilisations (classe 2)"].append({"compte": code, "montant": solde})
            total_actif += solde
        elif classe == "3":
            actif_groupes["Stocks (classe 3)"].append({"compte": code, "montant": solde})
            total_actif += solde
        elif classe == "5":
            actif_groupes["Disponibilités (classe 5)"].append({"compte": code, "montant": solde})
            total_actif += solde
        elif classe == "4":
            if code.startswith("411") or code.startswith("43") and solde > 0:
                actif_groupes["Créances clients (411/43 déductible)"].append({"compte": code, "montant": abs(solde)})
                total_actif += abs(solde)
            elif code.startswith("401"):
                passif_groupes["Dettes fournisseurs (401)"].append({"compte": code, "montant": abs(solde)})
                total_passif += abs(solde)
            else:
                # Autres 43/44 en dettes fiscales/sociales
                passif_groupes["Dettes fiscales et sociales (43/44)"].append({"compte": code, "montant": abs(solde)})
                total_passif += abs(solde)
        elif classe == "1":
            if code.startswith("164"):
                passif_groupes["Emprunts (164)"].append({"compte": code, "montant": abs(solde)})
                total_passif += abs(solde)
            else:
                passif_groupes["Capitaux propres (classe 1 + résultat)"].append({"compte": code, "montant": abs(solde)})
                total_passif += abs(solde)

    # Résultat de l'exercice (calculé) → ajouté en capitaux propres passif
    if abs(res["resultat_net"]) > 0.001:
        passif_groupes["Capitaux propres (classe 1 + résultat)"].append({
            "compte": "120 (résultat de l'exercice)",
            "montant": res["resultat_net"],
        })
        total_passif += res["resultat_net"]

    # Nettoyer les groupes vides
    actif = {k: v for k, v in actif_groupes.items() if v}
    passif = {k: v for k, v in passif_groupes.items() if v}

    return {
        "actif": actif,
        "passif": passif,
        "total_actif": total_actif,
        "total_passif": total_passif,
        "equilibre": abs(total_actif - total_passif) < 0.01,
        "ecart": total_actif - total_passif,
        "resultat_net": res["resultat_net"],
    }
