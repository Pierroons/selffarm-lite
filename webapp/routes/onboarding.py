"""
Routes du wizard d'onboarding / édition profil exploitation.

Comportement unifié :
- Chaque étape POST → save_exploitation() avec UPDATE partiel SQL → persistance immédiate
- Premier passage (onboarding_done=0) : flow guidé étape par étape
- Après finalisation (onboarding_done=1) : accès libre à n'importe quelle étape via ?force=true,
  form pré-rempli depuis BDD, modification immédiate à la soumission de chaque step

L'utilisateur peut donc :
1. Faire le wizard initial intégralement
2. Quitter en cours de route et reprendre plus tard (les data sont déjà persistées)
3. Modifier UNE seule étape après finalisation sans tout recommencer

Routes :
- GET  /onboarding                     → redirect /onboarding/1 (ou / si déjà fait sans ?force)
- GET  /onboarding/{1..7}              → affiche template (form pré-rempli depuis BDD ou session)
- POST /onboarding/{2..6}              → save partiel en BDD + redirect étape suivante
- POST /onboarding/7                   → mark_onboarding_done() + redirect /
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from self_agri_book.exploitation import (
    get_exploitation,
    is_onboarding_done,
    mark_onboarding_done,
    save_exploitation,
)

from webapp import __version__

log = logging.getLogger(__name__)

router = APIRouter(tags=["onboarding"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

# Mapping étape → nom de template (ordre des écrans dans le wizard)
STEP_TEMPLATES = {
    1: "onboarding/step_1_welcome.html",
    2: "onboarding/step_2_identite.html",
    3: "onboarding/step_3_localisation.html",
    4: "onboarding/step_4_installation.html",
    5: "onboarding/step_5_regime.html",
    6: "onboarding/step_6_productions.html",
    7: "onboarding/step_7_recap.html",
}

SESSION_KEY = "onboarding_form"


def _hydrate_form_state(request: Request) -> dict:
    """Construit le form state à afficher :
    1. Charge le profil depuis BDD si existant (= source de vérité)
    2. Merge avec la session (= modifications en cours non encore persistées)
    3. Reconstitue `regime_tva` depuis `tva_assujetti` si nécessaire (compat UI)
    """
    exploitation = get_exploitation()
    form_state = {}
    if exploitation:
        # Profil persisté → seed depuis BDD
        form_state.update({k: v for k, v in exploitation.items() if k not in ("id", "created_at", "updated_at")})
        # Reconstitue regime_tva depuis tva_assujetti pour cohérence des radio cards
        if "regime_tva" not in form_state:
            form_state["regime_tva"] = "franchise" if not form_state.get("tva_assujetti") else "rsa"
    # Overlay session (modifs en cours pas encore validées sur step courant)
    session_state = request.session.get(SESSION_KEY, {})
    form_state.update(session_state)
    return form_state


def _save_form_state(request: Request, updates: dict) -> dict:
    """Merge des nouveaux champs dans la session (pour reprendre si user repart en arrière)."""
    state = request.session.get(SESSION_KEY, {})
    state.update(updates)
    request.session[SESSION_KEY] = state
    return state


def _clear_form_state(request: Request) -> None:
    """Vide l'état de session du wizard."""
    request.session.pop(SESSION_KEY, None)


def _persist_to_db(updates: dict, request: Request | None = None) -> None:
    """Persiste les modifications en BDD si possible, sinon laisse en session.

    Cas gérés :
    1. Profil existe (row id=1) → UPDATE partiel, toujours sûr
    2. Profil n'existe pas + payload contient nom+statut → INSERT initial complet
       (on enrichit aussi avec les data de session présentes des steps précédents)
    3. Profil n'existe pas + payload incomplet (user a sauté step 2) → skip persistance,
       les data restent en session pour reprise ultérieure. Pas de crash.
    """
    try:
        exploitation = get_exploitation()
        if exploitation:
            # Cas 1 — UPDATE partiel, toujours sûr
            save_exploitation(updates)
            log.info("Persist UPDATE partiel : champs=%s", list(updates.keys()))
            return

        has_minimal = bool(updates.get("nom") and updates.get("statut"))
        if has_minimal:
            # Cas 2 — INSERT initial. On enrichit avec la session pour ne pas perdre
            # les data des steps déjà saisis (si user fait 5 → 6 → revient à 2)
            if request is not None:
                session_state = request.session.get(SESSION_KEY, {})
                merged = {**session_state, **updates}
                save_exploitation(merged)
                log.info("Persist INSERT initial (enrichi session) : champs=%s", list(merged.keys()))
            else:
                save_exploitation(updates)
                log.info("Persist INSERT initial : champs=%s", list(updates.keys()))
            return

        # Cas 3 — pas d'INSERT initial possible, on skip
        log.info(
            "Persistance reportée (profil pas encore initialisé, payload sans nom+statut) — "
            "data conservées en session : %s",
            list(updates.keys()),
        )
    except Exception:
        log.exception("ERREUR pendant _persist_to_db avec updates=%s", updates)
        raise


def _render_step(request: Request, step: int):
    """Rendu d'un step avec le form state courant + flag mode édition."""
    form_state = _hydrate_form_state(request)
    return templates.TemplateResponse(
        STEP_TEMPLATES[step],
        {
            "request": request,
            "form": form_state,
            "version": __version__,
            "step_num": step,
            "step_total": len(STEP_TEMPLATES),
            "is_edit_mode": is_onboarding_done(),
        },
    )


# ============ Routes ============

EDIT_MODE_KEY = "onboarding_edit_mode"


def _enter_edit_mode_if_requested(request: Request) -> None:
    """Si ?force=true en query string, active le mode édition en session.

    Une fois activé, les liens internes du wizard (Précédent / Suivant / Commencer)
    n'ont pas besoin de porter ?force=true : la session porte l'état.
    Clearé à la finalisation step 7.
    """
    if request.query_params.get("force"):
        request.session[EDIT_MODE_KEY] = True


def _is_edit_mode(request: Request) -> bool:
    return bool(request.session.get(EDIT_MODE_KEY, False))


@router.get("/onboarding", include_in_schema=False)
async def onboarding_root(request: Request):
    """Entry point :
    - Si onboarding pas fait → /onboarding/1 (wizard initial)
    - Si onboarding déjà fait → / sauf si ?force=true (active mode édition)
    """
    _enter_edit_mode_if_requested(request)
    if is_onboarding_done() and not _is_edit_mode(request):
        return RedirectResponse(url="/", status_code=302)
    return RedirectResponse(url="/onboarding/1", status_code=302)


@router.get("/onboarding/{step}", include_in_schema=False)
async def onboarding_step_get(request: Request, step: int):
    """Affiche l'étape demandée.

    En mode édition (onboarding_done=1), nécessite ?force=true au premier accès
    OU une session edit_mode déjà active. Sans ça, redirect / pour éviter de
    relancer accidentellement le wizard depuis un signet.
    """
    _enter_edit_mode_if_requested(request)
    if is_onboarding_done() and not _is_edit_mode(request):
        return RedirectResponse(url="/", status_code=302)
    if step not in STEP_TEMPLATES:
        return RedirectResponse(url="/onboarding/1", status_code=302)
    return _render_step(request, step)


# Étape 1 — Welcome : pas de POST (lien direct vers /onboarding/2 dans le template)


@router.post("/onboarding/2", include_in_schema=False)
async def step_2_post(
    request: Request,
    nom: str = Form(...),
    statut: str = Form(...),
    siret: str = Form(""),
):
    """Étape 2 : identité (nom, statut, SIRET) → save direct BDD."""
    data = {
        "nom": nom.strip(),
        "statut": statut.strip().upper(),
        "siret": siret.strip() or None,
    }
    _save_form_state(request, data)
    _persist_to_db(data, request=request)
    return RedirectResponse(url="/onboarding/3", status_code=303)


@router.post("/onboarding/3", include_in_schema=False)
async def step_3_post(
    request: Request,
    commune: str = Form(...),
    code_postal: str = Form(...),
    departement: str = Form(...),
):
    """Étape 3 : localisation → save direct BDD."""
    data = {
        "commune": commune.strip(),
        "code_postal": code_postal.strip(),
        "departement": departement.strip(),
    }
    _save_form_state(request, data)
    _persist_to_db(data, request=request)
    return RedirectResponse(url="/onboarding/4", status_code=303)


@router.post("/onboarding/4", include_in_schema=False)
async def step_4_post(
    request: Request,
    saison_courante: int = Form(...),
    date_installation: str = Form(""),
):
    """Étape 4 : date d'installation + saison → save direct BDD."""
    data = {
        "date_installation": date_installation.strip() or None,
        "saison_courante": int(saison_courante),
    }
    _save_form_state(request, data)
    _persist_to_db(data, request=request)
    return RedirectResponse(url="/onboarding/5", status_code=303)


@router.post("/onboarding/5", include_in_schema=False)
async def step_5_post(
    request: Request,
    regime_fiscal: str = Form(...),
    regime_tva: str = Form(...),
):
    """Étape 5 : régime fiscal (BA) + régime TVA → save direct BDD.

    Les 2 dimensions sont indépendantes :
    - regime_fiscal : micro_ba / reel_simplifie / reel_normal
    - regime_tva    : franchise / rsa / reel_tva

    Mapping vers BDD : `tva_assujetti` = False si franchise, True sinon.
    En V1.1 on pourra ajouter une colonne dédiée `regime_tva` pour distinguer rsa vs reel_tva.
    """
    data = {
        "regime_fiscal": regime_fiscal.strip(),
        "regime_tva": regime_tva.strip(),  # gardé en session pour cohérence UI
        "tva_assujetti": regime_tva.strip() != "franchise",
    }
    _save_form_state(request, data)
    # En BDD on ne save QUE les colonnes existantes (regime_tva pas en colonne pour l'instant)
    _persist_to_db({
        "regime_fiscal": data["regime_fiscal"],
        "tva_assujetti": data["tva_assujetti"],
    }, request=request)
    return RedirectResponse(url="/onboarding/6", status_code=303)


@router.post("/onboarding/6", include_in_schema=False)
async def step_6_post(request: Request):
    """Étape 6 : productions (multi-select) → save direct BDD."""
    form = await request.form()
    productions = [p.strip() for p in form.getlist("productions") if p.strip()]
    data = {"productions": productions}
    _save_form_state(request, data)
    _persist_to_db(data, request=request)
    return RedirectResponse(url="/onboarding/7", status_code=303)


@router.post("/onboarding/7", include_in_schema=False)
async def step_7_finalize(request: Request):
    """Étape finale : marque l'onboarding comme terminé + clear session + redirect /.

    Toutes les données sont déjà persistées en BDD à ce stade (saves progressifs
    aux étapes 2-6). Cette étape ne fait que basculer le flag onboarding_done.
    Idempotent : sûr à re-appeler après une modif d'étape ultérieure.
    """
    exploitation = get_exploitation()
    if not exploitation or not exploitation.get("nom") or not exploitation.get("statut"):
        log.warning("Finalize onboarding sans profil minimal — redirect step 2")
        return RedirectResponse(url="/onboarding/2", status_code=303)

    first_time = not is_onboarding_done()
    mark_onboarding_done()
    _clear_form_state(request)
    request.session.pop(EDIT_MODE_KEY, None)  # sortir du mode édition
    log.info("Onboarding finalisé (ou modifié) pour exploitation '%s'", exploitation["nom"])
    # 1ère finalisation → écran « Protège tes données » (choix d'une cible de sauvegarde)
    if first_time:
        return RedirectResponse(url="/backup/demarrage", status_code=303)
    return RedirectResponse(url="/", status_code=303)
