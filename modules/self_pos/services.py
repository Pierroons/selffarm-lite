"""SelfPOS services — clôture session + sync hub compta.

Convention comptable :
- Journal : VTE (ventes)
- Compte débit : 411 (clients divers)
- Compte crédit : 701 (ventes de produits finis)
- Une seule écriture journalière agrégée par session (cf. CGI franchise TVA + recettes journalières globales)
"""

from __future__ import annotations

import logging
from datetime import date as date_cls
from decimal import Decimal

from self_pos.storage import (
    get_session,
    list_ventes,
    mark_session_cloturee,
)

log = logging.getLogger(__name__)


def cloture_session(session_id: int) -> dict:
    """Clôture une session : génère 1 écriture compta agrégée et marque la session cloturée.

    Retourne {"ok": True, "ecriture_id": int, "session": {...}}.
    """
    session = get_session(session_id)
    if not session:
        raise ValueError(f"Session #{session_id} introuvable")
    if session["statut"] == "cloturee":
        raise ValueError(f"Session #{session_id} déjà clôturée")

    ventes = list_ventes(session_id)
    total = sum(float(v.get("total_ttc", 0) or 0) for v in ventes)

    # Si session vide → clôture mais aucune écriture compta
    if total <= 0 or not ventes:
        log.info("Session POS #%s clôturée sans vente (pas d'écriture compta)", session_id)
        return {
            "ok": True,
            "ecriture_id": None,
            "session": mark_session_cloturee(session_id, None),
            "info": "Aucune vente à comptabiliser",
        }

    # Import lazy pour éviter dépendance circulaire au chargement du module
    from self_agri_book.storage import save_ecriture

    try:
        # date_operation = date du marché si fournie, sinon aujourd'hui
        date_op = session.get("date_marche")
        if date_op:
            try:
                date_op = date_cls.fromisoformat(date_op[:10])
            except ValueError:
                date_op = date_cls.today()
        else:
            date_op = date_cls.today()

        numero_piece = f"POS-{session_id:04d}"
        libelle = f"Vente directe marché {session.get('lieu', '?')} — {session['nb_ventes']} ventes"

        ecriture_id, created = save_ecriture(
            date_operation=date_op,
            journal="VTE",
            numero_piece=numero_piece,
            libelle=libelle,
            compte_debit="411",   # Clients divers (vente directe particuliers)
            compte_credit="701",  # Ventes de produits finis
            montant_ttc=Decimal(str(round(total, 2))),
            source_module="self_pos",
            source_id=str(session_id),
        )
    except Exception:
        log.exception("Erreur création écriture compta pour clôture session #%s", session_id)
        raise

    session_cloturee = mark_session_cloturee(session_id, ecriture_id)
    log.info(
        "Session POS #%s clôturée : %.2f € total, écriture compta #%s (created=%s)",
        session_id, total, ecriture_id, created,
    )
    return {
        "ok": True,
        "ecriture_id": ecriture_id,
        "ecriture_created": created,
        "session": session_cloturee,
        "total_ttc": total,
    }
