"""
Storage SQLite pour le hub compta self_agri_book.

Table unique `ecritures_comptables` — hub central qui reçoit les auto-écritures
depuis tous les modules métier (self_invoice, self_banking, self_achats, ...).

Principe de simplicité : pas d'ORM (SQLAlchemy est dans le venv mais pas nécessaire
pour un schéma aussi plat). sqlite3 stdlib suffit.
"""

from __future__ import annotations

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
"""


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
    """Crée la DB + schéma si absents. Idempotent."""
    with _conn() as c:
        c.executescript(SCHEMA_SQL)
    log.info("Compta DB initialisée : %s", _db_path())


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
    allow_duplicate: bool = False,
) -> tuple[int, bool]:
    """Insère une écriture.

    Par défaut, si (source_module, source_id) existe déjà, l'écriture existante
    est renvoyée telle quelle (idempotence). Passer `allow_duplicate=True` force
    une nouvelle insertion même si doublon.

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
    with _conn() as c:
        cur = c.execute(
            """
            INSERT INTO ecritures_comptables
                (date_operation, journal, numero_piece, libelle,
                 compte_debit, compte_credit,
                 montant_ht, montant_tva, montant_ttc,
                 source_module, source_id, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
        ecriture_id = cur.lastrowid
    log.info(
        "Écriture #%d saisie : %s %s %s → %s / %s",
        ecriture_id, numero_piece, compte_debit, montant_ttc, compte_credit, libelle[:40],
    )
    return ecriture_id, True


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
