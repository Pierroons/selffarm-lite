"""self_agri_book.restore_diff — restauration DIFFÉRENCIÉE du ledger (Partie E).

Au lieu d'écraser toute la base, on traite les tables selon leur NATURE :
- IMMUABLE (compta + facturation) → UNION : on ne perd JAMAIS une écriture/facture ;
  le compteur de factures ne recule jamais (MAX).
- ÉTAT (cultures, parcelles, POS opérationnel, profil…) → REMPLACÉ par le backup.

Anti-rétrogradage : la génération = MAX(seq) de `ledger_outbox`. Si le backup est plus
ANCIEN que la base (gen backup < gen base), on EXIGE une confirmation explicite — le
ledger reste protégé par l'union, mais l'état métier va reculer (rétro volontaire assumé).

Une base VIERGE — celle d'un PC neuf, que l'app crée dès la première page — est
remplacée en entier par le backup. Sinon le backup est d'abord porté à la version
de l'app, puis fusionné : les tables d'une verticale que la base n'a pas encore
sont importées avec leurs lignes de registre, pour qu'aucune migration ne rejoue.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from self_agri_book.storage import mettre_a_niveau, tables_du_module

log = logging.getLogger("self_agri_book.restore_diff")

# Politique par table. Défaut (non listée) = "replace" (état remplaçable).
#   ("union", key) : ajoute les lignes du backup absentes (par `key`), JAMAIS de delete
#   ("max", None)  : compteurs_factures — dernier_numero = MAX par (annee, prefix)
#   ("keep", None) : on garde la table actuelle (log local, schéma de l'app courante)
#   ("replace", None) [défaut] : on remet la version du backup
TABLE_POLICY: dict[str, tuple[str, str | None]] = {
    "ecritures_comptables": ("union", "hash_data"),
    "ledger_outbox":        ("union", "hash_data"),
    "pos_vente":            ("union", "offline_uuid"),   # frontière à valider (recettes)
    "compteurs_factures":   ("max", None),
    "audit_log":            ("keep", None),
    "_schema_migrations":   ("keep", None),
}

# Tables qui ne portent aucune donnée de l'exploitation : une base qui n'a de
# lignes que là, onboarding non fait, est vierge.
_SANS_DONNEES = {"exploitation", "audit_log"}


def _tables(conn, schema: str = "main") -> list[str]:
    return [r[0] for r in conn.execute(
        f"SELECT name FROM {schema}.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]


def _columns(conn, table: str, schema: str = "main") -> list[tuple[str, int]]:
    return [(r[1], r[5]) for r in conn.execute(f"PRAGMA {schema}.table_info({table})")]  # (name, pk)


def _lecture_seule(db_path) -> sqlite3.Connection:
    return sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)


def db_generation(db_path) -> int:
    """Génération du ledger = MAX(seq) de ledger_outbox (0 si table/base absente)."""
    db_path = Path(db_path)
    if not db_path.exists():
        return 0
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute("SELECT MAX(seq) FROM ledger_outbox").fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()


def base_vierge(db_path) -> bool:
    """Onboarding non fait et aucune ligne hors profil, journal d'audit et registres."""
    conn = _lecture_seule(db_path)
    try:
        for t in _tables(conn):
            if t in _SANS_DONNEES or t.startswith("_schema_migrations"):
                continue
            if conn.execute(f'SELECT 1 FROM "{t}" LIMIT 1').fetchone():
                return False
        try:
            row = conn.execute("SELECT onboarding_done FROM exploitation WHERE id = 1").fetchone()
        except sqlite3.OperationalError:
            return True
        return not (row and row[0])
    finally:
        conn.close()


def _copier(src, dst) -> None:
    """Copie par l'API de sauvegarde de SQLite : une requête qui lit `dst` pendant
    l'opération ne voit jamais un fichier tronqué, contrairement à une copie de fichier."""
    source = _lecture_seule(src)
    cible = sqlite3.connect(str(dst))
    try:
        source.backup(cible)
    finally:
        cible.close()
        source.close()


def _copie_de_surete(db_path: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    prediff = db_path.with_suffix(f".db.prediff-{ts}")
    _copier(db_path, prediff)
    return prediff


def _mettre_a_niveau(db_path: Path) -> set[str]:
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    try:
        return mettre_a_niveau(conn)
    finally:
        conn.close()


def _apply_policy(conn, table: str, policy: str, key: str | None) -> int:
    if policy == "keep":
        return 0
    # Colonnes communes : les deux bases sont à la version de l'app, mais une
    # colonne d'un seul côté ne doit pas faire échouer toute la restauration.
    bak_cols = {n for n, _ in _columns(conn, table, "bak")}
    if policy == "replace":
        cols = [n for n, _ in _columns(conn, table) if n in bak_cols]
        collist = ", ".join(cols)
        conn.execute(f"DELETE FROM main.{table}")
        conn.execute(f"INSERT INTO main.{table} ({collist}) SELECT {collist} FROM bak.{table}")
        return conn.execute(f"SELECT COUNT(*) FROM main.{table}").fetchone()[0]
    if policy == "union":
        cols = [(n, is_pk) for n, is_pk in _columns(conn, table) if n in bak_cols]
        pk = [n for n, is_pk in cols if is_pk]
        names = [n for n, _ in cols]
        # exclure la PK si c'est un unique auto-incrément (id/seq réattribués localement)
        insert_cols = [n for n in names if not (len(pk) == 1 and n == pk[0])]
        collist = ", ".join(insert_cols)
        before = conn.execute(f"SELECT COUNT(*) FROM main.{table}").fetchone()[0]
        conn.execute(
            f"INSERT INTO main.{table} ({collist}) "
            f"SELECT {collist} FROM bak.{table} "
            f"WHERE {key} NOT IN (SELECT {key} FROM main.{table})"
        )
        after = conn.execute(f"SELECT COUNT(*) FROM main.{table}").fetchone()[0]
        return after - before
    if policy == "max":
        # compteurs_factures : le numéro ne recule JAMAIS (MAX par annee/prefix)
        conn.execute(
            "INSERT INTO main.compteurs_factures (annee, prefix, dernier_numero, updated_at) "
            "SELECT annee, prefix, dernier_numero, updated_at FROM bak.compteurs_factures WHERE true "
            "ON CONFLICT(annee, prefix) DO UPDATE SET "
            "  dernier_numero = MAX(compteurs_factures.dernier_numero, excluded.dernier_numero)"
        )
        return 0
    raise ValueError(f"Politique inconnue : {policy}")


def _importer_module(conn, module: str, tables: set[str]) -> dict[str, int]:
    """Crée dans main les tables d'une verticale absente, avec leurs lignes, index,
    triggers, lignes de registre et compteurs d'auto-incrément."""
    importees: dict[str, int] = {}
    for t in sorted(tables):
        (ddl,) = conn.execute(
            "SELECT sql FROM bak.sqlite_master WHERE type='table' AND name=?", (t,)).fetchone()
        conn.execute(ddl)
        conn.execute(f'INSERT INTO main."{t}" SELECT * FROM bak."{t}"')
        importees[t] = conn.execute(f'SELECT COUNT(*) FROM main."{t}"').fetchone()[0]
    marques = ", ".join("?" * len(tables))
    # Les triggers après les lignes : un trigger d'insertion ne doit pas les réécrire.
    for (ddl,) in conn.execute(
        f"SELECT sql FROM bak.sqlite_master WHERE type IN ('index', 'trigger') "
        f"AND tbl_name IN ({marques}) AND sql IS NOT NULL ORDER BY type = 'trigger'",
        sorted(tables),
    ).fetchall():
        conn.execute(ddl)
    conn.execute(
        "INSERT INTO main._schema_migrations (module, version, name, applied_at) "
        "SELECT module, version, name, applied_at FROM bak._schema_migrations WHERE module = ?",
        (module,),
    )
    for name, seq in conn.execute(
        f"SELECT name, seq FROM bak.sqlite_sequence WHERE name IN ({marques})", sorted(tables),
    ).fetchall():
        conn.execute(
            "INSERT INTO main.sqlite_sequence (name, seq) SELECT ?, 0 "
            "WHERE NOT EXISTS (SELECT 1 FROM main.sqlite_sequence WHERE name = ?)", (name, name))
        conn.execute("UPDATE main.sqlite_sequence SET seq = MAX(seq, ?) WHERE name = ?", (seq, name))
    return importees


def restore_differential(backup_db_path, current_db_path, confirm_rollback: bool = False) -> dict:
    """Restaure `backup_db_path` dans `current_db_path`.

    `backup_db_path` est une copie de travail : elle est portée sur place à la
    version de l'app. Retourne un dict : {mode, applied, ...}. Si rétrogradage
    détecté et non confirmé, `applied=False` + `needs_confirmation=True` (la base
    n'est pas touchée)."""
    backup_db_path = Path(backup_db_path)
    current_db_path = Path(current_db_path)
    if not backup_db_path.exists():
        raise FileNotFoundError(f"Backup DB absente : {backup_db_path}")

    modules_inconnus = sorted(_mettre_a_niveau(backup_db_path))
    if modules_inconnus:
        log.warning("Backup : modules inconnus de cette version, non mis à niveau : %s",
                    ", ".join(modules_inconnus))

    # PC neuf : rien à préserver, le backup remplace la base, aucun rétro possible
    if not current_db_path.exists() or base_vierge(current_db_path):
        current_db_path.parent.mkdir(parents=True, exist_ok=True)
        prediff = _copie_de_surete(current_db_path) if current_db_path.exists() else None
        _copier(backup_db_path, current_db_path)
        log.info("Restore fresh (base vierge) : le backup remplace la base")
        return {"mode": "fresh", "applied": True,
                "prediff_bak": str(prediff) if prediff else None,
                "tables": {}, "importees": {}, "signalees": [],
                "modules_inconnus": modules_inconnus}

    gen_base = db_generation(current_db_path)
    gen_bak = db_generation(backup_db_path)

    if gen_bak < gen_base and not confirm_rollback:
        return {"mode": "rollback", "applied": False, "needs_confirmation": True,
                "gen_base": gen_base, "gen_backup": gen_bak}

    # Filet : copie de la base avant toute modification
    prediff = _copie_de_surete(current_db_path)
    _mettre_a_niveau(current_db_path)

    conn = sqlite3.connect(str(current_db_path), isolation_level=None)
    summary: dict = {}
    importees: dict[str, dict[str, int]] = {}
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("ATTACH DATABASE ? AS bak", (str(backup_db_path),))
        main_tables = set(_tables(conn, "main"))
        bak_tables = set(_tables(conn, "bak"))
        modules_main = {r[0] for r in conn.execute("SELECT DISTINCT module FROM main._schema_migrations")}
        modules_bak = {r[0] for r in conn.execute("SELECT DISTINCT module FROM bak._schema_migrations")}
        a_importer = {
            m: (tables_du_module(m) & bak_tables) - main_tables
            for m in sorted(modules_bak - modules_main - set(modules_inconnus))
        }
        conn.execute("BEGIN")
        for t in sorted(main_tables & bak_tables):
            policy, key = TABLE_POLICY.get(t, ("replace", None))
            n = _apply_policy(conn, t, policy, key)
            summary[t] = {"policy": policy, "n": n}
        for m, tables in a_importer.items():
            if tables:
                importees[m] = _importer_module(conn, m, tables)
        conn.execute("COMMIT")
        conn.execute("DETACH bak")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()

    deja_vues = main_tables | {t for tables in importees.values() for t in tables}
    signalees = sorted(t for t in bak_tables - deja_vues if not t.startswith("_schema_migrations"))
    if signalees:
        log.warning("Restore : tables du backup non restaurées (ni dans la base, ni d'un "
                    "module connu) : %s", ", ".join(signalees))

    mode = "rollback" if gen_bak < gen_base else "merge"
    log.info("Restore différencié (%s) appliqué : base gen %d, backup gen %d, %d module(s) importé(s)",
             mode, gen_base, gen_bak, len(importees))
    return {"mode": mode, "applied": True, "gen_base": gen_base,
            "gen_backup": gen_bak, "prediff_bak": str(prediff), "tables": summary,
            "importees": importees, "signalees": signalees,
            "modules_inconnus": modules_inconnus}
