"""self_elevage.elevage — suivi de bande, ponte, mouvements et lots d'œufs.

Schéma propre au module (ELEVAGE_MIGRATIONS, namespace "self_elevage"), créé
**paresseusement** sur la base partagée du hub `self_agri_book` : tant que la
verticale élevage n'est pas sollicitée, ses tables n'existent pas. Le noyau
comptable reste agnostique du métier (règle A1).

Cadre réglementaire retenu — **moins de 250 poules, 100 % vente directe** :
- livraison au consommateur dans un délai maximum de **21 jours après la ponte** ;
- affichage obligatoire de la **période de ponte** et du **mode d'élevage** ;
- marquage du code producteur obligatoire hors site de production (marché, PVC).
Ces règles pilotent le modèle : `lot_oeufs` porte la période de ponte et sa date
limite, et `lots_a_ecouler()` sert l'alerte. Le module **n'atteste d'aucune
conformité** — il outille, il ne certifie pas.

API :
- list_bandes(actives_only=True) → list[dict]
- get_bande(bande_id) → dict | None
- save_bande(data) → dict            (UPSERT)
- effectif_vivant(bande_id) → int    (initial − mortalité − réforme + ajout)
- add_mouvement(data) → dict
- list_mouvements(bande_id=None) → list[dict]
- save_ponte(data) → dict            (UPSERT sur (bande_id, date_ponte))
- list_ponte(bande_id=None, debut=None, fin=None) → list[dict]
- taux_ponte(bande_id, jours=7) → dict
- creer_lot(data) → dict
- get_lot(lot_id) → dict | None
- list_lots(statut=None) → list[dict]
- lots_a_ecouler(marge_jours=5) → list[dict]
- update_lot_statut(lot_id, statut, destination=None) → dict
- oeufs_periode(bande_id, debut, fin) → dict   (aide au remplissage d'un lot)
- add_aliment(data) → dict           (livraison d'aliment)
- list_aliment(bande_id=None) → list[dict]
- stats_aliment(bande_id) → dict     (conso g/j/poule, coût par œuf)
- registre_elevage(bande_id, debut=None, fin=None) → dict   (document imprimable)
- stats_elevage() → dict             (bandeau tableau de bord)
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from self_agri_book.storage import _conn, apply_module_migrations

log = logging.getLogger(__name__)

# Délai réglementaire ponte → consommateur en vente directe (< 250 poules).
DELAI_VENTE_DIRECTE_JOURS = 21

VALID_ESPECES = ("poule_pondeuse", "poulet_chair", "canard", "caille", "autre")
VALID_MODES_ELEVAGE = ("bio", "plein_air", "sol", "cage")
VALID_TYPES_MOUVEMENT = ("mortalite", "reforme", "ajout")
VALID_STATUTS_BANDE = ("active", "terminee")
VALID_STATUTS_LOT = ("disponible", "vendu", "retire")
VALID_TYPES_ALIMENT = ("ponte", "demarrage", "croissance", "complement", "autre")

# Repère de consommation d'une poule pondeuse adulte, en grammes par jour.
# Sert uniquement à situer une conso mesurée — jamais à la remplacer.
REPERE_CONSO_G_JOUR = 120

# Durée de conservation du registre d'élevage (arrêté du 5 juin 2000).
DUREE_CONSERVATION_REGISTRE_ANS = 5

BANDE_FIELDS = (
    "nom", "espece", "race", "effectif_initial", "date_mise_en_place",
    "mode_elevage", "statut", "notes",
)
MOUVEMENT_FIELDS = ("bande_id", "date_mouvement", "type_mouvement", "nombre", "motif")
PONTE_FIELDS = ("bande_id", "date_ponte", "nb_oeufs", "nb_casses", "nb_declasses", "notes")
ALIMENT_FIELDS = (
    "bande_id", "date_livraison", "type_aliment", "quantite_kg",
    "prix_total_eur", "fournisseur", "notes",
)
LOT_FIELDS = (
    "bande_id", "date_ponte_debut", "date_ponte_fin", "nb_oeufs",
    "statut", "destination", "notes",
)


ELEVAGE_MIGRATIONS: list[tuple[int, str, str]] = [
    (1, "create_bande", """
        -- Bande = lot d'animaux mis en place ensemble. Multi-bandes assumé dès
        -- l'origine : une bande unique n'est qu'un cas particulier.
        CREATE TABLE IF NOT EXISTS bande (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL,                       -- ex: "Pondeuses 2026"
            espece TEXT NOT NULL DEFAULT 'poule_pondeuse'
                CHECK (espece IN ('poule_pondeuse','poulet_chair','canard','caille','autre')),
            race TEXT,                               -- ex: "Marans", "ISA Brown"
            effectif_initial INTEGER NOT NULL CHECK (effectif_initial > 0),
            date_mise_en_place TEXT NOT NULL,        -- ISO YYYY-MM-DD
            mode_elevage TEXT NOT NULL DEFAULT 'plein_air'
                CHECK (mode_elevage IN ('bio','plein_air','sol','cage')),
            statut TEXT NOT NULL DEFAULT 'active'
                CHECK (statut IN ('active','terminee')),
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_bande_statut ON bande(statut);
        CREATE TRIGGER IF NOT EXISTS trg_bande_updated_at
            AFTER UPDATE ON bande FOR EACH ROW
            BEGIN UPDATE bande SET updated_at = datetime('now') WHERE id = NEW.id; END;
    """),
    (2, "create_bande_mouvement", """
        -- Mouvements d'effectif. L'effectif vivant n'est jamais stocké : il se
        -- recalcule (initial − mortalité − réforme + ajout), donc il ne peut pas
        -- diverger de son historique. Le registre d'élevage s'appuie dessus.
        CREATE TABLE IF NOT EXISTS bande_mouvement (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bande_id INTEGER NOT NULL,
            date_mouvement TEXT NOT NULL,            -- ISO YYYY-MM-DD
            type_mouvement TEXT NOT NULL
                CHECK (type_mouvement IN ('mortalite','reforme','ajout')),
            nombre INTEGER NOT NULL CHECK (nombre > 0),
            motif TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (bande_id) REFERENCES bande(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_mouvement_bande ON bande_mouvement(bande_id, date_mouvement);
    """),
    (3, "create_ponte", """
        -- Relevé quotidien. Un seul enregistrement par bande et par jour
        -- (UNIQUE) : une double saisie corrige, elle ne duplique pas.
        CREATE TABLE IF NOT EXISTS ponte (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bande_id INTEGER NOT NULL,
            date_ponte TEXT NOT NULL,                -- ISO YYYY-MM-DD
            nb_oeufs INTEGER NOT NULL CHECK (nb_oeufs >= 0),
            nb_casses INTEGER NOT NULL DEFAULT 0 CHECK (nb_casses >= 0),
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE (bande_id, date_ponte),
            FOREIGN KEY (bande_id) REFERENCES bande(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_ponte_date ON ponte(date_ponte);
        CREATE TRIGGER IF NOT EXISTS trg_ponte_updated_at
            AFTER UPDATE ON ponte FOR EACH ROW
            BEGIN UPDATE ponte SET updated_at = datetime('now') WHERE id = NEW.id; END;
    """),
    (4, "create_lot_oeufs", """
        -- Lot d'œufs destiné à la vente. Porte la période de ponte (affichage
        -- obligatoire) et la date limite = fin de ponte + 21 jours, délai
        -- réglementaire de la vente directe sous 250 poules.
        CREATE TABLE IF NOT EXISTS lot_oeufs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bande_id INTEGER NOT NULL,
            date_ponte_debut TEXT NOT NULL,
            date_ponte_fin TEXT NOT NULL,
            date_limite TEXT NOT NULL,               -- fin + 21 j, calculée à la création
            nb_oeufs INTEGER NOT NULL CHECK (nb_oeufs > 0),
            statut TEXT NOT NULL DEFAULT 'disponible'
                CHECK (statut IN ('disponible','vendu','retire')),
            destination TEXT,                        -- ex: "Marché de Sainte-Foy", "PVC"
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (bande_id) REFERENCES bande(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_lot_statut ON lot_oeufs(statut, date_limite);
        CREATE TRIGGER IF NOT EXISTS trg_lot_updated_at
            AFTER UPDATE ON lot_oeufs FOR EACH ROW
            BEGIN UPDATE lot_oeufs SET updated_at = datetime('now') WHERE id = NEW.id; END;
    """),
    (5, "ponte_add_declasses", """
        -- Œufs déclassés : sales, fêlés, calibre hors norme. Ils ont bien été
        -- pondus (donc comptés dans le taux de ponte) mais ne partent pas au même
        -- circuit — autoconsommation ou transformation plutôt que marché ou PVC.
        -- Distinction commerciale réelle en vente directe.
        -- Pas de CHECK ici : SQLite ne le pose pas en ALTER, la validation est en Python.
        ALTER TABLE ponte ADD COLUMN nb_declasses INTEGER NOT NULL DEFAULT 0;
    """),
    (6, "create_aliment_livraison", """
        -- Aliment acheté. Poste de charge principal d'un atelier volailles : sans
        -- lui, aucune marge par œuf n'est calculable. On enregistre les LIVRAISONS
        -- (ce que l'éleveur a sous la main : un bon de livraison), pas la
        -- distribution quotidienne — qui ne serait jamais saisie.
        CREATE TABLE IF NOT EXISTS aliment_livraison (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bande_id INTEGER NOT NULL,
            date_livraison TEXT NOT NULL,            -- ISO YYYY-MM-DD
            type_aliment TEXT NOT NULL DEFAULT 'ponte'
                CHECK (type_aliment IN ('ponte','demarrage','croissance','complement','autre')),
            quantite_kg REAL NOT NULL CHECK (quantite_kg > 0),
            prix_total_eur REAL,                     -- facultatif : conso suivie même sans prix
            fournisseur TEXT,
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (bande_id) REFERENCES bande(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_aliment_bande ON aliment_livraison(bande_id, date_livraison);
        CREATE TRIGGER IF NOT EXISTS trg_aliment_updated_at
            AFTER UPDATE ON aliment_livraison FOR EACH ROW
            BEGIN UPDATE aliment_livraison SET updated_at = datetime('now') WHERE id = NEW.id; END;
    """),
]


def _ensure_schema() -> None:
    """Crée paresseusement le schéma de la verticale élevage."""
    apply_module_migrations("self_elevage", ELEVAGE_MIGRATIONS)


def _clean(data: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    """Ne retient que les champs connus — ignore silencieusement le superflu."""
    return {k: v for k, v in data.items() if k in fields}


# ============================================================
# BANDES
# ============================================================

def list_bandes(actives_only: bool = True) -> list[dict[str, Any]]:
    _ensure_schema()
    sql = "SELECT * FROM bande"
    if actives_only:
        sql += " WHERE statut = 'active'"
    sql += " ORDER BY date_mise_en_place DESC, id DESC"
    with _conn() as con:
        return [dict(r) for r in con.execute(sql)]


def get_bande(bande_id: int) -> dict[str, Any] | None:
    _ensure_schema()
    with _conn() as con:
        row = con.execute("SELECT * FROM bande WHERE id = ?", (bande_id,)).fetchone()
    return dict(row) if row else None


def save_bande(data: dict[str, Any]) -> dict[str, Any]:
    """Crée ou met à jour une bande. `id` présent → UPDATE, sinon INSERT."""
    _ensure_schema()
    d = _clean(data, BANDE_FIELDS)

    if not (d.get("nom") or "").strip():
        raise ValueError("Le nom de la bande est obligatoire.")
    try:
        effectif = int(d.get("effectif_initial") or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("Effectif initial invalide.") from exc
    if effectif <= 0:
        raise ValueError("L'effectif initial doit être supérieur à zéro.")
    d["effectif_initial"] = effectif

    espece = d.get("espece") or "poule_pondeuse"
    if espece not in VALID_ESPECES:
        raise ValueError(f"espèce invalide '{espece}' — attendu un de {VALID_ESPECES}")
    d["espece"] = espece

    mode = d.get("mode_elevage") or "plein_air"
    if mode not in VALID_MODES_ELEVAGE:
        raise ValueError(f"mode d'élevage invalide '{mode}' — attendu un de {VALID_MODES_ELEVAGE}")
    d["mode_elevage"] = mode

    statut = d.get("statut") or "active"
    if statut not in VALID_STATUTS_BANDE:
        raise ValueError(f"statut invalide '{statut}' — attendu un de {VALID_STATUTS_BANDE}")
    d["statut"] = statut

    if not d.get("date_mise_en_place"):
        d["date_mise_en_place"] = date.today().isoformat()

    bande_id = data.get("id")
    cols = [k for k in BANDE_FIELDS if k in d]
    with _conn() as con:
        if bande_id:
            con.execute(
                f"UPDATE bande SET {', '.join(f'{c} = ?' for c in cols)} WHERE id = ?",
                [d[c] for c in cols] + [bande_id],
            )
        else:
            cur = con.execute(
                f"INSERT INTO bande ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                [d[c] for c in cols],
            )
            bande_id = cur.lastrowid
    return get_bande(int(bande_id))  # type: ignore[arg-type]


def effectif_vivant(bande_id: int) -> int:
    """Effectif réel = initial − mortalité − réforme + ajout.

    Jamais stocké : recalculé depuis les mouvements, donc toujours cohérent avec
    l'historique. C'est le dénominateur du taux de ponte.
    """
    _ensure_schema()
    bande = get_bande(bande_id)
    if not bande:
        return 0
    with _conn() as con:
        rows = con.execute(
            "SELECT type_mouvement, SUM(nombre) AS n FROM bande_mouvement "
            "WHERE bande_id = ? GROUP BY type_mouvement",
            (bande_id,),
        ).fetchall()
    delta = 0
    for r in rows:
        n = int(r["n"] or 0)
        delta += n if r["type_mouvement"] == "ajout" else -n
    return max(0, int(bande["effectif_initial"]) + delta)


# ============================================================
# MOUVEMENTS
# ============================================================

def add_mouvement(data: dict[str, Any]) -> dict[str, Any]:
    _ensure_schema()
    d = _clean(data, MOUVEMENT_FIELDS)

    if not get_bande(int(d.get("bande_id") or 0)):
        raise ValueError("Bande introuvable.")

    type_mvt = d.get("type_mouvement")
    if type_mvt not in VALID_TYPES_MOUVEMENT:
        raise ValueError(f"type de mouvement invalide '{type_mvt}' — attendu un de {VALID_TYPES_MOUVEMENT}")

    try:
        nombre = int(d.get("nombre") or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("Nombre invalide.") from exc
    if nombre <= 0:
        raise ValueError("Le nombre doit être supérieur à zéro.")
    d["nombre"] = nombre

    if not d.get("date_mouvement"):
        d["date_mouvement"] = date.today().isoformat()

    cols = [k for k in MOUVEMENT_FIELDS if k in d]
    with _conn() as con:
        cur = con.execute(
            f"INSERT INTO bande_mouvement ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
            [d[c] for c in cols],
        )
        row = con.execute("SELECT * FROM bande_mouvement WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def list_mouvements(bande_id: int | None = None) -> list[dict[str, Any]]:
    _ensure_schema()
    sql = ("SELECT m.*, b.nom AS bande_nom FROM bande_mouvement m "
           "LEFT JOIN bande b ON b.id = m.bande_id")
    params: list[Any] = []
    if bande_id:
        sql += " WHERE m.bande_id = ?"
        params.append(bande_id)
    sql += " ORDER BY m.date_mouvement DESC, m.id DESC"
    with _conn() as con:
        return [dict(r) for r in con.execute(sql, params)]


# ============================================================
# PONTE
# ============================================================

def save_ponte(data: dict[str, Any]) -> dict[str, Any]:
    """Enregistre le relevé du jour. Re-saisir la même date **corrige** la valeur.

    Convention de saisie : `nb_oeufs` est le **total ramassé**. Les casses et les
    déclassés en sont des sous-ensembles — « j'ai ramassé 98 œufs, dont 2 cassés
    et 3 sales » — d'où le contrôle casses + déclassés ≤ total.
    """
    _ensure_schema()
    d = _clean(data, PONTE_FIELDS)

    bande_id = int(d.get("bande_id") or 0)
    if not get_bande(bande_id):
        raise ValueError("Bande introuvable.")

    try:
        nb = int(d.get("nb_oeufs") or 0)
        casses = int(d.get("nb_casses") or 0)
        declasses = int(d.get("nb_declasses") or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("Nombre d'œufs invalide.") from exc
    if nb < 0 or casses < 0 or declasses < 0:
        raise ValueError("Les quantités ne peuvent pas être négatives.")
    if casses + declasses > nb:
        raise ValueError(
            f"Casses et déclassés ({casses + declasses}) dépassent le total ramassé ({nb})."
        )
    d["nb_oeufs"], d["nb_casses"], d["nb_declasses"] = nb, casses, declasses

    if not d.get("date_ponte"):
        d["date_ponte"] = date.today().isoformat()

    cols = [k for k in PONTE_FIELDS if k in d]
    with _conn() as con:
        con.execute(
            f"INSERT INTO ponte ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
            f"ON CONFLICT(bande_id, date_ponte) DO UPDATE SET "
            f"{', '.join(f'{c} = excluded.{c}' for c in cols if c not in ('bande_id', 'date_ponte'))}",
            [d[c] for c in cols],
        )
        row = con.execute(
            "SELECT * FROM ponte WHERE bande_id = ? AND date_ponte = ?",
            (bande_id, d["date_ponte"]),
        ).fetchone()
    return dict(row)


def list_ponte(bande_id: int | None = None, debut: str | None = None,
               fin: str | None = None) -> list[dict[str, Any]]:
    _ensure_schema()
    sql = ("SELECT p.*, b.nom AS bande_nom FROM ponte p "
           "LEFT JOIN bande b ON b.id = p.bande_id WHERE 1=1")
    params: list[Any] = []
    if bande_id:
        sql += " AND p.bande_id = ?"
        params.append(bande_id)
    if debut:
        sql += " AND p.date_ponte >= ?"
        params.append(debut)
    if fin:
        sql += " AND p.date_ponte <= ?"
        params.append(fin)
    sql += " ORDER BY p.date_ponte DESC, p.id DESC"
    with _conn() as con:
        return [dict(r) for r in con.execute(sql, params)]


def taux_ponte(bande_id: int, jours: int = 7) -> dict[str, Any]:
    """Taux de ponte sur les N derniers jours **relevés** (pas calendaires).

    Rapporté à l'effectif **vivant** : un troupeau qui a perdu des poules ne voit
    pas son taux s'effondrer artificiellement. Renvoie None plutôt que 0 quand la
    donnée manque — un taux de 0 % signifierait « aucune ponte », ce qui est faux.
    """
    _ensure_schema()
    releves = list_ponte(bande_id=bande_id)[:jours]
    effectif = effectif_vivant(bande_id)
    total_oeufs = sum(int(r["nb_oeufs"] or 0) for r in releves)
    total_casses = sum(int(r["nb_casses"] or 0) for r in releves)
    total_declasses = sum(int(r.get("nb_declasses") or 0) for r in releves)
    nb_jours = len(releves)

    taux = None
    if effectif > 0 and nb_jours > 0:
        # Le taux mesure la PONTE, donc sur le total ramassé : un œuf sale ou
        # fêlé a bien été pondu. Ce qui est vendable se lit à part.
        taux = round(total_oeufs / (effectif * nb_jours) * 100, 1)

    vendables = total_oeufs - total_casses - total_declasses
    return {
        "effectif_vivant": effectif,
        "jours_releves": nb_jours,
        "total_oeufs": total_oeufs,
        "total_casses": total_casses,
        "total_declasses": total_declasses,
        "total_vendables": vendables,
        "taux_vendable_pct": round(vendables / total_oeufs * 100, 1) if total_oeufs else None,
        "moyenne_jour": round(total_oeufs / nb_jours, 1) if nb_jours else None,
        "taux_ponte_pct": taux,
    }


# ============================================================
# LOTS D'ŒUFS
# ============================================================

def _date_limite(date_ponte_fin: str) -> str:
    """Date limite de remise au consommateur : fin de ponte + 21 jours."""
    return (date.fromisoformat(date_ponte_fin)
            + timedelta(days=DELAI_VENTE_DIRECTE_JOURS)).isoformat()


def creer_lot(data: dict[str, Any]) -> dict[str, Any]:
    _ensure_schema()
    d = _clean(data, LOT_FIELDS)

    if not get_bande(int(d.get("bande_id") or 0)):
        raise ValueError("Bande introuvable.")

    try:
        debut = date.fromisoformat((d.get("date_ponte_debut") or "").strip())
        fin = date.fromisoformat((d.get("date_ponte_fin") or "").strip())
    except ValueError as exc:
        raise ValueError("Dates de ponte invalides — format attendu AAAA-MM-JJ.") from exc
    if fin < debut:
        raise ValueError("La fin de période ne peut pas précéder son début.")

    try:
        nb = int(d.get("nb_oeufs") or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("Nombre d'œufs invalide.") from exc
    if nb <= 0:
        raise ValueError("Le lot doit contenir au moins un œuf.")
    d["nb_oeufs"] = nb

    statut = d.get("statut") or "disponible"
    if statut not in VALID_STATUTS_LOT:
        raise ValueError(f"statut invalide '{statut}' — attendu un de {VALID_STATUTS_LOT}")
    d["statut"] = statut
    d["date_limite"] = _date_limite(fin.isoformat())

    cols = [k for k in (*LOT_FIELDS, "date_limite") if k in d]
    with _conn() as con:
        cur = con.execute(
            f"INSERT INTO lot_oeufs ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
            [d[c] for c in cols],
        )
        row = con.execute("SELECT * FROM lot_oeufs WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def list_lots(statut: str | None = None) -> list[dict[str, Any]]:
    _ensure_schema()
    sql = ("SELECT l.*, b.nom AS bande_nom, b.mode_elevage FROM lot_oeufs l "
           "LEFT JOIN bande b ON b.id = l.bande_id")
    params: list[Any] = []
    if statut:
        sql += " WHERE l.statut = ?"
        params.append(statut)
    sql += " ORDER BY l.date_limite ASC, l.id DESC"
    with _conn() as con:
        rows = [dict(r) for r in con.execute(sql, params)]
    today = date.today()
    for r in rows:
        try:
            r["jours_restants"] = (date.fromisoformat(r["date_limite"]) - today).days
        except (TypeError, ValueError):
            r["jours_restants"] = None
    return rows


def lots_a_ecouler(marge_jours: int = 5) -> list[dict[str, Any]]:
    """Lots disponibles dont la date limite approche ou est dépassée.

    Sert l'alerte : au-delà de 21 jours après la ponte, un œuf ne peut plus être
    remis au consommateur en vente directe.
    """
    return [
        lot for lot in list_lots(statut="disponible")
        if lot.get("jours_restants") is not None and lot["jours_restants"] <= marge_jours
    ]


def get_lot(lot_id: int) -> dict[str, Any] | None:
    _ensure_schema()
    with _conn() as con:
        row = con.execute("SELECT * FROM lot_oeufs WHERE id = ?", (lot_id,)).fetchone()
    return dict(row) if row else None


def update_lot_statut(lot_id: int, statut: str,
                      destination: str | None = None) -> dict[str, Any]:
    """Fait passer un lot de « disponible » à « vendu » ou « retiré ».

    Un lot n'est jamais supprimé : le registre doit garder trace de ce qui a été
    produit, y compris de ce qui n'a pas pu être vendu. « retiré » couvre le lot
    périmé, cassé ou consommé sur place.
    """
    _ensure_schema()
    if statut not in VALID_STATUTS_LOT:
        raise ValueError(f"statut invalide '{statut}' — attendu un de {VALID_STATUTS_LOT}")
    if not get_lot(lot_id):
        raise ValueError("Lot introuvable.")

    with _conn() as con:
        if destination is not None:
            con.execute("UPDATE lot_oeufs SET statut = ?, destination = ? WHERE id = ?",
                        (statut, destination, lot_id))
        else:
            con.execute("UPDATE lot_oeufs SET statut = ? WHERE id = ?", (statut, lot_id))
    return get_lot(lot_id)  # type: ignore[return-value]


def oeufs_periode(bande_id: int, debut: str, fin: str) -> dict[str, Any]:
    """Ce qu'ont donné les relevés d'une période — aide à remplir un lot.

    Renvoie le total ramassé et le **vendable** (hors casses et déclassés) : c'est
    ce second chiffre qu'on propose par défaut à la création d'un lot, puisque
    c'est lui qui partira au marché.
    """
    _ensure_schema()
    releves = list_ponte(bande_id=bande_id, debut=debut, fin=fin)
    total = sum(int(r["nb_oeufs"] or 0) for r in releves)
    casses = sum(int(r["nb_casses"] or 0) for r in releves)
    declasses = sum(int(r.get("nb_declasses") or 0) for r in releves)
    return {
        "jours_releves": len(releves),
        "total_oeufs": total,
        "total_casses": casses,
        "total_declasses": declasses,
        "vendables": max(0, total - casses - declasses),
    }


# ============================================================
# ALIMENT
# ============================================================

def add_aliment(data: dict[str, Any]) -> dict[str, Any]:
    """Enregistre une livraison d'aliment.

    Le prix est **facultatif** : un éleveur qui ne le connaît pas encore doit
    quand même pouvoir suivre sa consommation. La marge se calculera plus tard.
    """
    _ensure_schema()
    d = _clean(data, ALIMENT_FIELDS)

    if not get_bande(int(d.get("bande_id") or 0)):
        raise ValueError("Bande introuvable.")

    type_al = d.get("type_aliment") or "ponte"
    if type_al not in VALID_TYPES_ALIMENT:
        raise ValueError(f"type d'aliment invalide '{type_al}' — attendu un de {VALID_TYPES_ALIMENT}")
    d["type_aliment"] = type_al

    try:
        qte = float(str(d.get("quantite_kg") or "0").replace(",", "."))
    except (TypeError, ValueError) as exc:
        raise ValueError("Quantité invalide — indique un nombre de kilos.") from exc
    if qte <= 0:
        raise ValueError("La quantité doit être supérieure à zéro.")
    d["quantite_kg"] = qte

    prix_raw = str(d.get("prix_total_eur") or "").strip()
    if prix_raw:
        try:
            prix = float(prix_raw.replace(",", "."))
        except ValueError as exc:
            raise ValueError("Prix invalide — indique un montant en euros.") from exc
        if prix < 0:
            raise ValueError("Le prix ne peut pas être négatif.")
        d["prix_total_eur"] = prix
    else:
        d["prix_total_eur"] = None

    if not d.get("date_livraison"):
        d["date_livraison"] = date.today().isoformat()

    cols = [k for k in ALIMENT_FIELDS if k in d]
    with _conn() as con:
        cur = con.execute(
            f"INSERT INTO aliment_livraison ({', '.join(cols)}) "
            f"VALUES ({', '.join('?' * len(cols))})",
            [d[c] for c in cols],
        )
        row = con.execute(
            "SELECT * FROM aliment_livraison WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    return dict(row)


def list_aliment(bande_id: int | None = None) -> list[dict[str, Any]]:
    _ensure_schema()
    sql = ("SELECT a.*, b.nom AS bande_nom FROM aliment_livraison a "
           "LEFT JOIN bande b ON b.id = a.bande_id")
    params: list[Any] = []
    if bande_id:
        sql += " WHERE a.bande_id = ?"
        params.append(bande_id)
    sql += " ORDER BY a.date_livraison DESC, a.id DESC"
    with _conn() as con:
        rows = [dict(r) for r in con.execute(sql, params)]
    for r in rows:
        qte = float(r["quantite_kg"] or 0)
        prix = r["prix_total_eur"]
        r["prix_kg_eur"] = round(float(prix) / qte, 3) if prix is not None and qte else None
    return rows


def stats_aliment(bande_id: int) -> dict[str, Any]:
    """Consommation et coût alimentaire d'une bande.

    ⚠️ **Approximation assumée** : on suit les *livraisons*, pas la distribution
    réelle. La consommation journalière est donc lissée sur la période allant de
    la première livraison à aujourd'hui, à effectif vivant constant. Un stock non
    encore consommé la surestime, un achat en gros aussi. C'est un ordre de
    grandeur destiné à repérer une dérive, pas une mesure.
    """
    _ensure_schema()
    livraisons = list_aliment(bande_id=bande_id)
    if not livraisons:
        return {
            "nb_livraisons": 0, "total_kg": 0.0, "total_eur": None,
            "prix_moyen_kg": None, "conso_g_jour_poule": None,
            "jours_periode": 0, "cout_par_oeuf_eur": None,
            "repere_g_jour": REPERE_CONSO_G_JOUR,
        }

    total_kg = sum(float(l["quantite_kg"] or 0) for l in livraisons)
    prix = [float(l["prix_total_eur"]) for l in livraisons if l["prix_total_eur"] is not None]
    total_eur = round(sum(prix), 2) if prix else None

    premiere = min(l["date_livraison"] for l in livraisons)
    try:
        jours = max(1, (date.today() - date.fromisoformat(premiere)).days)
    except ValueError:
        jours = 1

    effectif = effectif_vivant(bande_id)
    conso = round(total_kg * 1000 / (jours * effectif), 1) if effectif and jours else None

    # Coût par œuf sur la même fenêtre que l'aliment consommé.
    oeufs = sum(int(r["nb_oeufs"] or 0) for r in list_ponte(bande_id=bande_id, debut=premiere))
    cout_oeuf = round(total_eur / oeufs, 4) if total_eur and oeufs else None

    return {
        "nb_livraisons": len(livraisons),
        "total_kg": round(total_kg, 1),
        "total_eur": total_eur,
        "prix_moyen_kg": round(total_eur / total_kg, 3) if total_eur and total_kg else None,
        "conso_g_jour_poule": conso,
        "jours_periode": jours,
        "oeufs_periode": oeufs,
        "cout_par_oeuf_eur": cout_oeuf,
        "repere_g_jour": REPERE_CONSO_G_JOUR,
    }


# ============================================================
# REGISTRE D'ÉLEVAGE
# ============================================================

def registre_elevage(bande_id: int, debut: str | None = None,
                     fin: str | None = None) -> dict[str, Any]:
    """Registre d'élevage d'une bande, prêt à imprimer.

    L'arrêté du 5 juin 2000 impose la tenue d'un registre d'élevage conservé
    **5 ans** : identification de l'atelier, entrées et sorties d'animaux,
    traitements et ordonnances, mortalités.

    ⚠️ SelfFarm n'en couvre que la **partie effectifs et production**. Les
    traitements vétérinaires et les ordonnances ne sont pas modélisés : ils
    restent à consigner par ailleurs, et le document le rappelle explicitement
    plutôt que de laisser croire à un registre complet.
    """
    _ensure_schema()
    bande = get_bande(bande_id)
    if not bande:
        raise ValueError("Bande introuvable.")

    mouvements = list_mouvements(bande_id=bande_id)
    if debut:
        mouvements = [m for m in mouvements if m["date_mouvement"] >= debut]
    if fin:
        mouvements = [m for m in mouvements if m["date_mouvement"] <= fin]

    releves = list_ponte(bande_id=bande_id, debut=debut, fin=fin)
    lots = [l for l in list_lots() if int(l["bande_id"]) == bande_id]
    if debut:
        lots = [l for l in lots if l["date_ponte_fin"] >= debut]
    if fin:
        lots = [l for l in lots if l["date_ponte_debut"] <= fin]

    livraisons = list_aliment(bande_id=bande_id)
    if debut:
        livraisons = [a for a in livraisons if a["date_livraison"] >= debut]
    if fin:
        livraisons = [a for a in livraisons if a["date_livraison"] <= fin]

    # Bilan d'effectif sur la période — les entrées et sorties du registre.
    par_type = {t: 0 for t in VALID_TYPES_MOUVEMENT}
    for m in mouvements:
        par_type[m["type_mouvement"]] += int(m["nombre"] or 0)

    total_oeufs = sum(int(r["nb_oeufs"] or 0) for r in releves)
    total_casses = sum(int(r["nb_casses"] or 0) for r in releves)
    total_declasses = sum(int(r.get("nb_declasses") or 0) for r in releves)

    return {
        "bande": bande,
        "periode": {"debut": debut, "fin": fin},
        "effectif_initial": int(bande["effectif_initial"] or 0),
        "effectif_vivant": effectif_vivant(bande_id),
        "entrees": par_type["ajout"],
        "sorties_mortalite": par_type["mortalite"],
        "sorties_reforme": par_type["reforme"],
        "mouvements": mouvements,
        "nb_jours_releves": len(releves),
        "total_oeufs": total_oeufs,
        "total_casses": total_casses,
        "total_declasses": total_declasses,
        "total_vendables": max(0, total_oeufs - total_casses - total_declasses),
        "releves": releves,
        "lots": lots,
        "livraisons": livraisons,
        "total_aliment_kg": round(sum(float(a["quantite_kg"] or 0) for a in livraisons), 1),
        "conservation_ans": DUREE_CONSERVATION_REGISTRE_ANS,
    }


def stats_elevage() -> dict[str, Any]:
    """Chiffres du bandeau tableau de bord, tous ateliers confondus."""
    _ensure_schema()
    bandes = list_bandes(actives_only=True)
    effectif_total = sum(effectif_vivant(int(b["id"])) for b in bandes)
    lots_dispo = list_lots(statut="disponible")
    alertes = lots_a_ecouler()

    oeufs_7j = 0
    depuis = (date.today() - timedelta(days=7)).isoformat()
    for b in bandes:
        oeufs_7j += sum(
            int(r["nb_oeufs"] or 0)
            for r in list_ponte(bande_id=int(b["id"]), debut=depuis)
        )

    cout_aliment = sum(
        float(l["prix_total_eur"])
        for l in list_aliment()
        if l["prix_total_eur"] is not None
    )

    return {
        "nb_bandes": len(bandes),
        "effectif_total": effectif_total,
        "oeufs_7j": oeufs_7j,
        "stock_lots": sum(int(l["nb_oeufs"] or 0) for l in lots_dispo),
        "nb_lots_disponibles": len(lots_dispo),
        "nb_alertes": len(alertes),
        "cout_aliment_eur": round(cout_aliment, 2) if cout_aliment else None,
    }
