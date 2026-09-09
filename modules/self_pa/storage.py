"""
Persistance des factures reçues — table `facture_recue`, namespace `self_pa`.

Le connecteur de SelfInvoice gardait ses transmissions en mémoire. Pour l'entrant
ce n'est pas tenable : il faut savoir ce qui a déjà été traité (sans quoi chaque
appel du bouton reproposerait tout), par quel canal c'est arrivé, et pouvoir le
démontrer.

**La déduplication est portée par le schéma.** `cle_metier` est la clé primaire :
la base refuse le doublon par construction, et non par une vérification qu'un
appelant pourrait oublier. C'est le même parti pris que `save_ecriture()`, qui
déduplique sur `(source_module, source_id)`.

Les montants sont stockés en TEXT, comme dans `ecritures_comptables` : un
`Decimal` traverse un TEXT sans perte, un REAL non.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from self_agri_book.storage import _conn, apply_module_migrations

from self_pa.imputation import Imputation
from self_pa.models import CanalReception, FactureRecue

log = logging.getLogger("selffarm.self_pa.storage")

MODULE = "self_pa"

# Statuts d'une facture reçue.
#   proposee — lue et contrôlée, une écriture attend la validation d'un humain
#   bloquee  — reçue, mais une anomalie empêche d'en proposer une écriture
#   validee  — l'humain a validé, l'écriture existe (ecriture_id renseigné)
#   ecartee  — l'humain a refusé de la comptabiliser
STATUTS = ("proposee", "bloquee", "validee", "ecartee")

MIGRATIONS: list[tuple[int, str, str]] = [
    (1, "create_facture_recue", """
        CREATE TABLE IF NOT EXISTS facture_recue (
            cle_metier TEXT PRIMARY KEY,
            siren_emetteur TEXT NOT NULL,
            nom_emetteur TEXT NOT NULL DEFAULT '',
            numero_facture TEXT NOT NULL,
            date_facture TEXT,
            montant_ht TEXT,
            montant_tva TEXT,
            montant_ttc TEXT,
            devise TEXT NOT NULL DEFAULT 'EUR',
            canal TEXT NOT NULL,
            provider TEXT NOT NULL DEFAULT '',
            provider_invoice_id TEXT,
            hash_fichier TEXT,
            statut TEXT NOT NULL DEFAULT 'proposee'
                CHECK (statut IN ('proposee', 'bloquee', 'validee', 'ecartee')),
            anomalies_json TEXT NOT NULL DEFAULT '[]',
            imputation_json TEXT NOT NULL DEFAULT '[]',
            facture_json TEXT,
            ecriture_id INTEGER,
            recue_le TEXT NOT NULL DEFAULT (datetime('now')),
            traitee_le TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_facture_recue_statut
            ON facture_recue(statut);
        CREATE INDEX IF NOT EXISTS idx_facture_recue_provider
            ON facture_recue(provider, provider_invoice_id);
        CREATE INDEX IF NOT EXISTS idx_facture_recue_emetteur
            ON facture_recue(siren_emetteur);
    """),
]


def _ensure_schema() -> None:
    """Crée la table à la première sollicitation.

    Paresseux comme `self_culture._ensure_schema()` : une installation qui
    n'utilise pas la réception ne porte pas sa table.
    """
    apply_module_migrations(MODULE, MIGRATIONS)


def _texte(valeur: Any) -> str | None:
    return None if valeur is None else str(valeur)


def enregistrer(
    facture: FactureRecue,
    imputation: Imputation,
    *,
    canal: CanalReception = CanalReception.PLATEFORME,
    provider: str = "superpdp",
    provider_invoice_id: str | int | None = None,
    hash_fichier: str | None = None,
) -> tuple[str, bool]:
    """Enregistre une facture reçue. Rend `(clé métier, nouvellement créée)`.

    Rejouer la même facture — par le même canal ou par un autre — ne crée rien :
    la clé primaire l'interdit. C'est ce qui protège du double traitement quand
    une facture arrive à la fois par mail et par la plateforme.
    """
    _ensure_schema()
    statut = "proposee" if imputation.proposable else "bloquee"
    cle = facture.cle_metier

    with _conn() as c:
        curseur = c.execute(
            """
            INSERT OR IGNORE INTO facture_recue
                (cle_metier, siren_emetteur, nom_emetteur, numero_facture,
                 date_facture, montant_ht, montant_tva, montant_ttc, devise,
                 canal, provider, provider_invoice_id, hash_fichier, statut,
                 anomalies_json, imputation_json, facture_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cle,
                facture.emetteur.siren,
                facture.emetteur.nom,
                facture.numero,
                facture.date_facture.isoformat() if facture.date_facture else None,
                _texte(facture.total_ht),
                _texte(facture.total_tva),
                _texte(facture.total_ttc),
                facture.devise,
                canal.value,
                provider,
                str(provider_invoice_id) if provider_invoice_id is not None else None,
                hash_fichier,
                statut,
                json.dumps([a.model_dump(mode="json") for a in imputation.anomalies],
                           ensure_ascii=False),
                json.dumps([ln.model_dump(mode="json") for ln in imputation.lignes],
                           ensure_ascii=False),
                facture.model_dump_json(),
            ),
        )
        creee = curseur.rowcount > 0

    if creee:
        log.info("Facture reçue enregistrée : %s (%s, %s)", cle, canal.value, statut)
    else:
        log.info("Facture %s déjà connue — ignorée (canal %s)", cle, canal.value)
    return cle, creee


def obtenir(cle_metier: str) -> dict | None:
    _ensure_schema()
    with _conn() as c:
        ligne = c.execute(
            "SELECT * FROM facture_recue WHERE cle_metier = ?", (cle_metier,)
        ).fetchone()
    return dict(ligne) if ligne else None


def lister(statut: str | None = None) -> list[dict]:
    """Factures reçues, les plus récentes d'abord."""
    _ensure_schema()
    if statut is not None and statut not in STATUTS:
        raise ValueError(f"Statut inconnu : {statut!r} — attendu l'un de {STATUTS}.")
    with _conn() as c:
        if statut:
            lignes = c.execute(
                "SELECT * FROM facture_recue WHERE statut = ? ORDER BY recue_le DESC",
                (statut,),
            ).fetchall()
        else:
            lignes = c.execute(
                "SELECT * FROM facture_recue ORDER BY recue_le DESC"
            ).fetchall()
    return [dict(x) for x in lignes]


def dernier_id_plateforme(provider: str = "superpdp") -> int | None:
    """Le plus grand identifiant de facture déjà récupéré chez ce fournisseur.

    C'est le curseur de reprise : il évite de reparcourir tout l'historique à
    chaque appel. La plateforme numérote ses factures par entiers croissants et
    pagine sur `starting_after_id`, d'où le MAX plutôt qu'une date.
    """
    _ensure_schema()
    with _conn() as c:
        ligne = c.execute(
            """
            SELECT MAX(CAST(provider_invoice_id AS INTEGER)) AS dernier
            FROM facture_recue
            WHERE provider = ? AND provider_invoice_id IS NOT NULL
            """,
            (provider,),
        ).fetchone()
    return int(ligne["dernier"]) if ligne and ligne["dernier"] is not None else None


def marquer_validee(cle_metier: str, ecriture_id: int) -> bool:
    """Note qu'un humain a validé, et rattache l'écriture créée.

    Seule une facture déjà validée est refusée — c'est ce qui empêche qu'un
    double clic produise une seconde écriture. Une facture écartée, elle, peut
    être reprise : écarter est une décision, pas une condamnation, et un clic
    malheureux ne doit pas rendre une dette réelle incomptabilisable.
    """
    _ensure_schema()
    with _conn() as c:
        curseur = c.execute(
            """
            UPDATE facture_recue
               SET statut = 'validee', ecriture_id = ?, traitee_le = ?
             WHERE cle_metier = ? AND statut != 'validee'
            """,
            (ecriture_id, datetime.now().isoformat(), cle_metier),
        )
        change = curseur.rowcount > 0
    if change:
        log.info("Facture %s validée → écriture #%d", cle_metier, ecriture_id)
    else:
        log.warning(
            "Facture %s : validation sans effet (absente ou déjà traitée)", cle_metier
        )
    return change


def marquer_ecartee(cle_metier: str, motif: str = "") -> bool:
    """L'humain refuse de comptabiliser. La facture reste en base : elle a été
    reçue, et le guide DGFiP demande de pouvoir justifier son traitement."""
    _ensure_schema()
    with _conn() as c:
        curseur = c.execute(
            """
            UPDATE facture_recue
               SET statut = 'ecartee', traitee_le = ?,
                   anomalies_json = json_insert(
                       anomalies_json, '$[#]',
                       json_object('code', 'ecartee_manuellement',
                                   'message', ?, 'gravite', 'avertissement'))
             WHERE cle_metier = ? AND statut IN ('proposee', 'bloquee')
            """,
            (datetime.now().isoformat(), motif or "Écartée par l'utilisateur.",
             cle_metier),
        )
        change = curseur.rowcount > 0
    if change:
        log.info("Facture %s écartée : %s", cle_metier, motif or "sans motif")
    return change
