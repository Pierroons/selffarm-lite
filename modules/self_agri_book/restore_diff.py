"""self_agri_book.restore_diff — restauration DIFFÉRENCIÉE du ledger (Partie E).

Au lieu d'écraser toute la base, on traite les tables selon leur NATURE :
- IMMUABLE (compta + facturation) → UNION : on ne perd JAMAIS une écriture/facture ;
  le compteur de factures ne recule jamais (MAX).
- ÉTAT (cultures, parcelles, POS opérationnel, profil…) → REMPLACÉ par le backup.

Anti-rétrogradage : la génération = MAX(seq) de `ledger_outbox`. Si le backup est plus
ANCIEN que la base (gen backup < gen base), on EXIGE une confirmation explicite — le
ledger reste protégé par l'union, mais l'état métier va reculer (rétro volontaire assumé).
"""
from __future__ import annotations

import logging
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

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


def _tables(conn, schema: str = "main") -> list[str]:
    return [r[0] for r in conn.execute(
        f"SELECT name FROM {schema}.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]


def _columns(conn, table: str) -> list[tuple[str, int]]:
    return [(r[1], r[5]) for r in conn.execute(f"PRAGMA table_info({table})")]  # (name, pk)


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


def _apply_policy(conn, table: str, policy: str, key: str | None) -> int:
    if policy == "keep":
        return 0
    if policy == "replace":
        cols = [n for n, _ in _columns(conn, table)]
        collist = ", ".join(cols)
        conn.execute(f"DELETE FROM main.{table}")
        conn.execute(f"INSERT INTO main.{table} ({collist}) SELECT {collist} FROM bak.{table}")
        return conn.execute(f"SELECT COUNT(*) FROM main.{table}").fetchone()[0]
    if policy == "union":
        cols = _columns(conn, table)
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


def restore_differential(backup_db_path, current_db_path, confirm_rollback: bool = False) -> dict:
    """Fusionne le backup dans la base courante selon TABLE_POLICY.

    Retourne un dict : {mode, applied, ...}. Si rétrogradage détecté et non confirmé,
    `applied=False` + `needs_confirmation=True` (rien n'est touché)."""
    backup_db_path = Path(backup_db_path)
    current_db_path = Path(current_db_path)
    if not backup_db_path.exists():
        raise FileNotFoundError(f"Backup DB absente : {backup_db_path}")

    # PC neuf / base absente → restauration complète (copie), aucun rétro possible
    if not current_db_path.exists():
        current_db_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup_db_path, current_db_path)
        log.info("Restore fresh (base absente) : copie complète du backup")
        return {"mode": "fresh", "applied": True}

    gen_base = db_generation(current_db_path)
    gen_bak = db_generation(backup_db_path)

    if gen_bak < gen_base and not confirm_rollback:
        return {"mode": "rollback", "applied": False, "needs_confirmation": True,
                "gen_base": gen_base, "gen_backup": gen_bak}

    # Filet : copie de la base avant toute modification
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    prediff = current_db_path.with_suffix(f".db.prediff-{ts}")
    shutil.copy2(current_db_path, prediff)

    conn = sqlite3.connect(str(current_db_path), isolation_level=None)
    summary: dict = {}
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("ATTACH DATABASE ? AS bak", (str(backup_db_path),))
        bak_tables = set(_tables(conn, "bak"))
        conn.execute("BEGIN")
        for t in _tables(conn, "main"):
            if t not in bak_tables:
                continue
            policy, key = TABLE_POLICY.get(t, ("replace", None))
            n = _apply_policy(conn, t, policy, key)
            summary[t] = {"policy": policy, "n": n}
        conn.execute("COMMIT")
        conn.execute("DETACH bak")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()

    mode = "rollback" if gen_bak < gen_base else "merge"
    log.info("Restore différencié (%s) appliqué : base gen %d, backup gen %d",
             mode, gen_base, gen_bak)
    return {"mode": mode, "applied": True, "gen_base": gen_base,
            "gen_backup": gen_bak, "prediff_bak": str(prediff), "tables": summary}
