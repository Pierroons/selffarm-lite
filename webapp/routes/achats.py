"""Route /achats — factures fournisseurs reçues via une Plateforme Agréée.

L'écran où un humain décide. La récupération remplit une liste d'attente ; rien
n'entre en comptabilité sans un clic sur cette page, et sans un compte de charge
choisi ici.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from webapp import __version__

log = logging.getLogger("selffarm.routes.achats")

# self_pa a besoin de httpx, qui est un extra (`pip install '.[pa]'`). Une
# installation non raccordée à une plateforme n'a pas à le porter : l'écran se
# contente alors de dire pourquoi il est vide.
try:
    from self_pa import comptes, reception, storage
    from self_pa.client import ErreurPlateforme
    MODULE_OK = True
    RAISON_INDISPONIBLE = ""
except ImportError as e:
    MODULE_OK = False
    RAISON_INDISPONIBLE = str(e)
    log.warning("Module self_pa indisponible : %s", e)

router = APIRouter(prefix="/achats", tags=["achats"])

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

ORDRE_STATUTS = ("proposee", "bloquee", "validee", "ecartee")


def _decorer(ligne: dict) -> dict:
    """Prépare une ligne pour l'affichage : JSON décodé, libellés résolus."""
    ligne = dict(ligne)
    for champ, defaut in (("anomalies_json", []), ("imputation_json", [])):
        try:
            ligne[champ.removesuffix("_json")] = json.loads(ligne.get(champ) or "[]")
        except json.JSONDecodeError:
            ligne[champ.removesuffix("_json")] = defaut
    ligne["bloquantes"] = [
        a for a in ligne["anomalies"] if a.get("gravite") == "bloquant"
    ]
    ligne["avertissements"] = [
        a for a in ligne["anomalies"] if a.get("gravite") != "bloquant"
    ]
    return ligne


@router.get("", response_class=HTMLResponse)
async def achats_index(request: Request, message: str = "", erreur: str = ""):
    if not MODULE_OK:
        return templates.TemplateResponse(
            request, "achats/indisponible.html",
            {"raison": RAISON_INDISPONIBLE, "version": __version__},
            status_code=503,
        )

    factures = [_decorer(f) for f in storage.lister()]
    par_statut = {s: [f for f in factures if f["statut"] == s] for s in ORDRE_STATUTS}
    return templates.TemplateResponse(
        request,
        "achats/index.html",
        {
            "par_statut": par_statut,
            "total": len(factures),
            "groupes_comptes": comptes.groupes_de_charge(),
            "libelle_compte": comptes.libelle,
            "message": message,
            "erreur": erreur,
            "version": __version__,
        },
    )


@router.post("/recuperer")
async def achats_recuperer(request: Request):
    """Le bouton du matin. Interroge la plateforme et remplit la liste d'attente.

    Ne crée aucune écriture — c'est tout l'intérêt de le séparer de la
    validation.
    """
    if not MODULE_OK:
        return RedirectResponse("/achats", status_code=303)
    try:
        rapport = await reception.recuperer_nouvelles()
    except ErreurPlateforme as e:
        log.warning("Récupération impossible : %s", e)
        return _retour(erreur=f"Plateforme injoignable — {e}")

    message = rapport.resume()
    if rapport.echecs:
        message += f" · en échec : {', '.join(i for i, _ in rapport.echecs)}"
    return _retour(message=message)


@router.post("/valider")
async def achats_valider(
    request: Request,
    cle_metier: str = Form(...),
    compte_charge: str = Form(...),
):
    """Comptabilise une facture, sur le compte que l'utilisateur a choisi."""
    if not MODULE_OK:
        return RedirectResponse("/achats", status_code=303)

    # Le compte vient d'un formulaire : rien ne garantit qu'il soit une charge.
    # Une facture d'achat imputée sur un compte de classe 4 ou 7 passerait
    # inaperçue dans un bilan tout en le faussant.
    if not comptes.est_compte_de_charge(compte_charge):
        return _retour(
            erreur=f"{compte_charge} n'est pas un compte de charge (classe 6)."
        )
    try:
        ecriture_id = reception.valider(cle_metier, compte_charge)
    except ValueError as e:
        return _retour(erreur=str(e))
    return _retour(
        message=f"Écriture #{ecriture_id} créée sur le compte {compte_charge} "
                f"({comptes.libelle(compte_charge)})."
    )


@router.post("/ecarter")
async def achats_ecarter(
    request: Request,
    cle_metier: str = Form(...),
    motif: str = Form(""),
):
    """Refuse de comptabiliser, sans effacer : la facture a bien été reçue."""
    if not MODULE_OK:
        return RedirectResponse("/achats", status_code=303)
    if storage.marquer_ecartee(cle_metier, motif):
        return _retour(message=f"Facture {cle_metier} écartée.")
    return _retour(erreur=f"Facture {cle_metier} introuvable ou déjà traitée.")


def _retour(message: str = "", erreur: str = "") -> RedirectResponse:
    """Redirige vers la liste en portant le compte rendu.

    Un POST suivi d'une redirection plutôt qu'une réponse directe : sans cela,
    un rafraîchissement du navigateur rejouerait la validation.
    """
    from urllib.parse import urlencode

    params = {k: v for k, v in (("message", message), ("erreur", erreur)) if v}
    suffixe = f"?{urlencode(params)}" if params else ""
    return RedirectResponse(f"/achats{suffixe}", status_code=303)
