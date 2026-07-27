"""Route /cultures — assolement de la saison, vue transversale toutes parcelles.

Complémentaire de /parcelles, qui est orientée **foncier** (une parcelle, ses
cultures). Ici on regarde l'inverse : **la culture d'abord**, agrégée sur
l'ensemble du parcellaire, et regroupée par **famille botanique** — la maille
qui compte pour les rotations, et donc pour la conformité en agriculture bio
(on ne fait pas revenir une solanacée sur la même planche deux ans de suite).

Le moteur vient de self_culture.cultures : rien n'est réimplémenté ici.
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from self_agri_book.exploitation import get_exploitation
from self_culture.cultures import (
    get_varietes_for_datalist,
    list_parcelles,
    list_plan_culture,
    stats_parcelles_saison,
)
from webapp import __version__

log = logging.getLogger(__name__)

router = APIRouter(prefix="/cultures", tags=["cultures"])
templates = Jinja2Templates(directory="webapp/templates")

# Ordre d'affichage des familles : les plus courantes en maraîchage d'abord.
_FAMILLE_ORDRE = [
    "Solanaceae", "Brassicaceae", "Apiaceae", "Cucurbitaceae",
    "Fabaceae", "Asteraceae", "Alliaceae", "Chenopodiaceae",
    "Lamiaceae", "Poaceae",
]

# Repères de rotation : délai de retour conseillé sur une même parcelle.
# Source : pratiques maraîchères bio courantes — indicatif, non réglementaire.
_RETOUR_CONSEILLE = {
    "Solanaceae": 4, "Brassicaceae": 4, "Apiaceae": 3, "Cucurbitaceae": 3,
    "Chenopodiaceae": 3, "Alliaceae": 3, "Asteraceae": 2, "Fabaceae": 2,
}


def _current_saison() -> int:
    exp = get_exploitation()
    if exp and exp.get("saison_courante"):
        try:
            return int(exp["saison_courante"])
        except (TypeError, ValueError):
            pass
    return date.today().year


# Repli par mot-clé quand la culture n'est pas au catalogue.
# Indispensable en pratique : un maraîcher saisit ses propres variétés
# (« Tomate Cornue des Andes ») que le catalogue ne connaît pas — sans ce
# repli, la culture sortirait du raisonnement de rotation, qui est justement
# ce qui compte en bio.
_MOTS_FAMILLE: tuple[tuple[tuple[str, ...], str], ...] = (
    (("tomate", "pomme de terre", "aubergine", "poivron", "piment"), "Solanaceae"),
    (("chou", "radis", "navet", "roquette", "moutarde", "colza", "cresson"), "Brassicaceae"),
    (("carotte", "persil", "celeri", "céleri", "fenouil", "panais", "aneth"), "Apiaceae"),
    (("courge", "courgette", "concombre", "melon", "potiron", "pâtisson", "patisson"), "Cucurbitaceae"),
    (("haricot", "pois", "feve", "fève", "feverole", "féverole", "luzerne", "trefle", "trèfle", "lupin", "vesce"), "Fabaceae"),
    (("salade", "laitue", "chicoree", "chicorée", "artichaut", "scarole", "mache", "mâche"), "Asteraceae"),
    (("oignon", "ail", "poireau", "echalote", "échalote", "ciboulette"), "Alliaceae"),
    (("betterave", "epinard", "épinard", "blette", "bette"), "Chenopodiaceae"),
    (("basilic", "menthe", "thym", "romarin", "sauge", "origan"), "Lamiaceae"),
    (("ble", "blé", "orge", "avoine", "seigle", "mais", "maïs", "sarrasin"), "Poaceae"),
)


def _famille_de(culture_label: str, catalog: list[dict]) -> str:
    """Retrouve la famille botanique d'une culture.

    Trois passes, de la plus fiable à la plus permissive :
    1. correspondance exacte avec une fiche du catalogue variétés ;
    2. correspondance approchée (le libellé a pu être édité à la main) ;
    3. repli par mot-clé — couvre les variétés saisies librement.
    """
    label = (culture_label or "").strip()
    if not label:
        return "Autres"

    for v in catalog:
        if v.get("value") == label:
            return v.get("famille") or "Autres"

    low = label.lower()
    for v in catalog:
        val = (v.get("value") or "").lower()
        if val and (val in low or low in val):
            return v.get("famille") or "Autres"

    for mots, famille in _MOTS_FAMILLE:
        if any(m in low for m in mots):
            return famille

    return "Autres"


@router.get("", response_class=HTMLResponse)
async def cultures_index(request: Request, saison: int | None = None):
    """Assolement de la saison : cultures groupées par famille botanique."""
    saison_active = saison or _current_saison()
    catalog = get_varietes_for_datalist()
    plans = list_plan_culture(saison=saison_active)

    # Regroupement par famille, avec cumul de surface et comptage de parcelles.
    familles: dict[str, dict] = {}
    for p in plans:
        fam = _famille_de(p.get("culture_label") or p.get("culture", ""), catalog)
        bloc = familles.setdefault(fam, {
            "nom": fam,
            "plans": [],
            "surface_ha": 0.0,
            "parcelles": set(),
            "retour_ans": _RETOUR_CONSEILLE.get(fam),
        })
        bloc["plans"].append(p)
        bloc["surface_ha"] += float(p.get("surface_ha") or 0)
        if p.get("parcelle_nom"):
            bloc["parcelles"].add(p["parcelle_nom"])

    for bloc in familles.values():
        bloc["parcelles"] = sorted(bloc["parcelles"])
        bloc["surface_ha"] = round(bloc["surface_ha"], 4)

    ordre = {f: i for i, f in enumerate(_FAMILLE_ORDRE)}
    familles_triees = sorted(
        familles.values(),
        key=lambda b: (ordre.get(b["nom"], 99), -b["surface_ha"]),
    )

    # Saisons disponibles : celles qui portent au moins un plan, + la courante.
    saisons = sorted(
        {p["saison"] for p in list_plan_culture() if p.get("saison")} | {saison_active},
        reverse=True,
    )

    surface_cultivee = round(sum(b["surface_ha"] for b in familles_triees), 4)
    stats = stats_parcelles_saison(saison_active)
    surface_totale = float(stats.get("surface_total_ha") or 0)

    return templates.TemplateResponse(
        "cultures/index.html",
        {
            "request": request,
            "version": __version__,
            "saison": saison_active,
            "saisons": saisons,
            "familles": familles_triees,
            "nb_plans": len(plans),
            "nb_parcelles": len(list_parcelles()),
            "surface_cultivee": surface_cultivee,
            "surface_totale": surface_totale,
            "taux_occupation": (
                round(surface_cultivee / surface_totale * 100) if surface_totale else None
            ),
        },
    )
