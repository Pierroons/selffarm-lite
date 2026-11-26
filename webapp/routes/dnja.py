"""Route DNJA : simulateur + génération PDF."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

import anyio
import yaml
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from self_dnja.engine import calculer
from self_dnja.models import Hypotheses
from self_dnja.pdf import pdf_bytes

from webapp import __version__

log = logging.getLogger(__name__)

router = APIRouter(prefix="/dnja", tags=["dnja"])

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
EXAMPLES_DIR = Path(__file__).parent.parent.parent / "examples"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# ── OPSEC : les scénarios nominatifs portent l'identité civile dans le YAML.
# Ils ne doivent JAMAIS être listés ni chargés hors de la machine perso, même
# si un fichier traîne sur le serveur (rsync accidentel). Barrière applicative
# indépendante du .gitignore : on n'expose les scénarios « pierroons/perso »
# que si SELFFARM_ENV=perso.
_PRIVATE_SCENARIO_PATTERNS = ("pierroons", "perso")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# ── OPSEC : un libellé de scénario, et le couple comparé par défaut, décrivent
# une exploitation réelle — sa filière, son dossier d'installation. Ils vivent
# donc hors du dépôt, dans examples/libelles.local.json, ignoré par git et par
# Docker. Sans ce fichier, un scénario s'affiche sous son slug et la
# comparaison part des deux premiers de la liste : l'application marche, elle
# ne raconte simplement plus rien.
_LIBELLES_LOCAUX = EXAMPLES_DIR / "libelles.local.json"

# Seul libellé porté par le dépôt : la démo, dont le YAML est publié et fictif.
_LIBELLES_PUBLICS: dict[str, tuple[str, str]] = {
    "hypotheses-demo-publique": (
        "Démo publique 🌻",
        "JA fictif·ve — maraîchage bio + PPAM (données 100 % anonymisées)",
    ),
}


# 64 Kio : ce fichier porte des libellés, pas un jeu de données. Il est relu à
# CHAQUE requête, sans cache : un fichier de 60 Mo coûtait une seconde par page,
# dans la boucle d'événements, donc pour toutes les requêtes en cours.
_LIBELLES_TAILLE_MAX = 64 * 1024


def _libelles_locaux() -> dict:
    """Contenu de examples/libelles.local.json, ou {} si le fichier ne convient pas.

    Relu à chaque appel, sans cache : le fichier peut apparaître entre deux
    requêtes, et un cache rendrait son absence définitive pour le processus.

    Trois refus AVANT de lire, et chacun répond à une panne mesurée :
    - **un fichier régulier seulement.** Un tube nommé à cette place bloque
      l'ouverture, donc la boucle d'événements, donc l'application entière — pas
      une page, toutes. Un dossier ou un lien cassé repassent par le même refus.
    - **une taille de libellés.** Voir la constante ci-dessus.
    - **une forme attendue.** Un JSON *valide* de mauvaise forme franchissait les
      gardes : une racine en liste rendait 500 sur les quatre routes DNJA.
    Et `RecursionError` est attrapée : un JSON profond de 200 000 niveaux est
    syntaxiquement valide, et son erreur n'est ni OSError ni ValueError.
    """
    try:
        if not _LIBELLES_LOCAUX.is_file():
            return {}
        taille = _LIBELLES_LOCAUX.stat().st_size
        if taille > _LIBELLES_TAILLE_MAX:
            log.warning("libelles.local.json ignoré : %d o pour un plafond de %d",
                        taille, _LIBELLES_TAILLE_MAX)
            return {}
        with _LIBELLES_LOCAUX.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError, RecursionError) as exc:
        log.warning("libelles.local.json illisible, libellés par défaut : %s", exc)
        return {}
    if not isinstance(data, dict):
        log.warning("libelles.local.json : objet attendu à la racine, %s reçu",
                    type(data).__name__)
        return {}
    return data


def _perso_env() -> bool:
    return os.environ.get("SELFFARM_ENV", "prod").lower() == "perso"


def _is_private_scenario(slug: str) -> bool:
    s = slug.lower()
    return any(p in s for p in _PRIVATE_SCENARIO_PATTERNS)


def _list_examples() -> list[dict]:
    """Scanne le dossier examples/ et retourne les YAML dispos avec metadata.

    Hors machine perso, les scénarios nominatifs sont filtrés (OPSEC).
    """
    out = []
    show_private = _perso_env()
    labels = dict(_LIBELLES_PUBLICS)
    nommes = _libelles_locaux().get("libelles")
    if nommes is not None and not isinstance(nommes, dict):
        # Une liste, une chaîne ou un nombre rendait 500 ici même, par .items().
        log.warning("libelles.local.json : « libelles » doit être un objet, %s reçu",
                    type(nommes).__name__)
        nommes = None
    for slug, valeur in (nommes or {}).items():
        if isinstance(valeur, dict):
            labels[str(slug)] = (str(valeur.get("label") or slug), str(valeur.get("desc") or ""))
    for path in sorted(EXAMPLES_DIR.glob("hypotheses-*.yaml")):
        slug = path.stem
        if not show_private and _is_private_scenario(slug):
            continue
        label, desc = labels.get(slug, (slug, ""))
        out.append({"slug": slug, "label": label, "desc": desc, "path": path})
    return out


def _load_example(slug: str) -> Hypotheses:
    # Garde-fou anti-traversal + OPSEC : pas de scénario nominatif hors perso.
    if not _SLUG_RE.match(slug) or (not _perso_env() and _is_private_scenario(slug)):
        raise HTTPException(404, f"Scénario introuvable : {slug}")
    path = EXAMPLES_DIR / f"{slug}.yaml"
    if not path.exists():
        raise HTTPException(404, f"Scénario introuvable : {slug}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Hypotheses.model_validate(data)


@router.get("", response_class=HTMLResponse)
async def dnja_index(request: Request):
    return templates.TemplateResponse(
        request, "dnja/index.html",
        {
            "version": __version__,
            "examples": _list_examples(),
        },
    )


@router.get("/calcul", response_class=HTMLResponse)
async def dnja_calcul(request: Request, example: str):
    """Fragment HTMX injecté dans #result."""
    h = _load_example(example)
    result = calculer(h)
    return templates.TemplateResponse(
        request, "dnja/_result.html",
        {
            "version": __version__,
            "result": result.model_dump(mode="json"),
            "example": example,
        },
    )


@router.get("/editor", response_class=HTMLResponse)
async def dnja_editor_index(request: Request):
    return templates.TemplateResponse(
        request, "dnja/editor.html",
        {"version": __version__, "examples": _list_examples()},
    )


@router.get("/editor/load", response_class=HTMLResponse)
async def dnja_editor_load(request: Request, slug: str):
    h = _load_example(slug)
    return templates.TemplateResponse(
        request, "dnja/_editor_form.html",
        {
            "h": h,
            "source_slug": slug,
        },
    )


async def _apply_form_to_hypotheses(slug: str, form_data: dict) -> Hypotheses:
    """Charge le YAML source + applique les changements du formulaire."""
    h = _load_example(slug)
    d = h.model_dump()

    # Identité
    if "candidat" in form_data:
        d["candidat"] = form_data["candidat"]
    if "uth" in form_data:
        d["uth"] = form_data["uth"]
    if "prelevements_mensuels" in form_data:
        d["prelevements_mensuels"] = form_data["prelevements_mensuels"]

    # Activités : champs act_<idx>_surface_ha, act_<idx>_quantite, act_<idx>_prix
    for key, value in form_data.items():
        m = re.match(r"^act_(\d+)_(surface_ha|quantite|prix)$", key)
        if not m:
            continue
        idx = int(m.group(1))
        field = m.group(2)
        if idx >= len(d["activites"]):
            continue
        if field == "surface_ha":
            d["activites"][idx]["surface_ha"] = value
        elif field == "quantite":
            if float(value) > 0:
                d["activites"][idx]["quantite_annuelle"] = value
        elif field == "prix":
            d["activites"][idx]["prix_vente_ht"] = value

    # MSA
    if "msa_base" in form_data:
        d["cotisations_msa"]["cotisation_base_annuelle"] = form_data["msa_base"]
    if "msa_exo" in form_data:
        d["cotisations_msa"]["exoneration_ja_active"] = form_data["msa_exo"] == "true"

    return Hypotheses.model_validate(d)


@router.post("/editor/calcul", response_class=HTMLResponse)
async def dnja_editor_calcul(request: Request):
    form = await request.form()
    form_data = {k: v for k, v in form.items()}
    source_slug = form_data.pop("source_slug", None)
    if not source_slug:
        raise HTTPException(400, "source_slug manquant")
    h = await _apply_form_to_hypotheses(source_slug, form_data)
    result = calculer(h)
    return templates.TemplateResponse(
        request, "dnja/_result.html",
        {
            "result": result.model_dump(mode="json"),
            "example": source_slug,  # pour le bouton PDF fallback
        },
    )


@router.post("/editor/save", response_class=HTMLResponse)
async def dnja_editor_save(request: Request):
    """Enregistre le formulaire actuel sous un nouveau slug."""
    form = await request.form()
    form_data = {k: v for k, v in form.items()}
    source_slug = form_data.pop("source_slug", None)
    if not source_slug:
        raise HTTPException(400, "source_slug manquant")

    # Le nom soufflé par hx-prompt arrive dans le header HX-Prompt
    new_slug = request.headers.get("HX-Prompt", "").strip()
    if not new_slug:
        return HTMLResponse(
            '<div class="card text-red-400">❌ Nom manquant — réessaie avec un nom valide</div>',
            status_code=400,
        )
    # Sanitize
    new_slug = re.sub(r"[^a-z0-9\-]", "-", new_slug.lower())
    new_slug = f"hypotheses-{new_slug}" if not new_slug.startswith("hypotheses-") else new_slug

    h = await _apply_form_to_hypotheses(source_slug, form_data)
    dest = EXAMPLES_DIR / f"{new_slug}.yaml"
    yaml_text = yaml.safe_dump(
        h.model_dump(mode="python"),
        default_flow_style=False, sort_keys=False, allow_unicode=True,
    )
    dest.write_text(yaml_text, encoding="utf-8")

    return HTMLResponse(
        f'<div class="card text-green-400">✅ Scénario enregistré dans <code>{dest.name}</code>. '
        f'<a href="/dnja" class="underline">Voir dans la liste</a>.</div>'
    )


def _defauts_compare(examples: list[dict]) -> tuple[str, str]:
    """Couple de scénarios proposé à l'ouverture de /dnja/compare.

    Il vient de examples/libelles.local.json quand il nomme deux scénarios
    présents ; sinon ce sont les deux premiers de la liste. Un slug absent est
    ignoré plutôt que proposé : la page ne doit pas nommer un scénario qu'elle
    ne peut pas charger.
    """
    slugs = [e["slug"] for e in examples]
    if not slugs:
        return "", ""
    voulu = _libelles_locaux().get("compare") or {}
    a = voulu.get("a") if isinstance(voulu, dict) else None
    b = voulu.get("b") if isinstance(voulu, dict) else None
    defaut_a = a if a in slugs else slugs[0]
    defaut_b = b if b in slugs else (slugs[1] if len(slugs) > 1 else slugs[0])
    return defaut_a, defaut_b


@router.get("/compare", response_class=HTMLResponse)
async def dnja_compare_index(request: Request):
    examples = _list_examples()
    defaut_a, defaut_b = _defauts_compare(examples)
    return templates.TemplateResponse(
        request, "dnja/compare.html",
        {
            "version": __version__,
            "examples": examples,
            "default_a": defaut_a,
            "default_b": defaut_b,
        },
    )


@router.get("/compare/run", response_class=HTMLResponse)
async def dnja_compare_run(request: Request, a: str, b: str):
    """Fragment HTMX : tableau de comparaison A vs B."""
    examples = {e["slug"]: e for e in _list_examples()}
    ha = _load_example(a)
    hb = _load_example(b)
    ra = calculer(ha)
    rb = calculer(hb)
    la, lb = ra.lignes[-1], rb.lignes[-1]

    def row(label, av, bv, highlight=False, positive_good=True):
        av = float(av); bv = float(bv)
        return {
            "label": label, "a": av, "b": bv,
            "delta": round(bv - av, 2),
            "highlight": highlight,
            "positive_good": positive_good,
        }

    comparison = [
        row("CA (produits)", la.produits_exploitation, lb.produits_exploitation),
        row("Charges exploitation", la.charges_exploitation, lb.charges_exploitation, positive_good=False),
        row("Amortissements", la.amortissements, lb.amortissements, positive_good=False),
        row("Cotisations MSA", la.charges_sociales, lb.charges_sociales, positive_good=False),
        row("Aides revenu", la.aides_revenu, lb.aides_revenu),
        row("EBE", la.ebe, lb.ebe, highlight=True),
        row("Résultat avant IR", la.resultat, lb.resultat),
        row("IR JA", la.ir_estime, lb.ir_estime, positive_good=False),
        row("Résultat net", la.resultat_net_apres_ir, lb.resultat_net_apres_ir, highlight=True),
        row("Revenu dispo mensuel", la.revenu_disponible_mensuel, lb.revenu_disponible_mensuel),
        row("EBE/UTH (seuil DNJA)", ra.ebe_uth_annee_cible, rb.ebe_uth_annee_cible, highlight=True),
    ]

    # Synthèse
    synth = []
    delta_ebe = float(lb.ebe - la.ebe)
    delta_res = float(lb.resultat_net_apres_ir - la.resultat_net_apres_ir)
    delta_rev_mensuel = float(lb.revenu_disponible_mensuel - la.revenu_disponible_mensuel)
    if delta_ebe > 0:
        synth.append(f"✓ EBE N+4 augmente de {delta_ebe:,.0f} €".replace(",", " "))
    elif delta_ebe < 0:
        synth.append(f"⚠ EBE N+4 baisse de {abs(delta_ebe):,.0f} €".replace(",", " "))
    if delta_res != 0:
        synth.append(f"Résultat net : {'+' if delta_res > 0 else ''}{delta_res:,.0f} €/an".replace(",", " "))
    if delta_rev_mensuel != 0:
        synth.append(f"Revenu disponible : {'+' if delta_rev_mensuel > 0 else ''}{delta_rev_mensuel:,.0f} €/mois".replace(",", " "))
    if ra.ebe_uth_atteint and not rb.ebe_uth_atteint:
        synth.append("⚠ B ne passe plus le seuil DNJA")
    elif not ra.ebe_uth_atteint and rb.ebe_uth_atteint:
        synth.append("✓ B passe le seuil DNJA (A non)")

    return templates.TemplateResponse(
        request, "dnja/_compare_result.html",
        {
            "a": {"slug": a, "label": examples[a]["label"], "result": ra.model_dump(mode="json")},
            "b": {"slug": b, "label": examples[b]["label"], "result": rb.model_dump(mode="json")},
            "comparison": comparison,
            "synthese": synth,
        },
    )


RENDUS_PDF = anyio.CapacityLimiter(1)


@router.get("/pdf")
async def dnja_pdf(example: str):
    """Télécharge le PDF d'un scénario."""
    h = _load_example(example)
    # Le rendu prend près d'une seconde : hors de la boucle, pour que les autres pages
    # répondent, et un seul à la fois, pour qu'une rafale ne prenne ni la mémoire ni le
    # pool de threads commun. En mémoire : aucun fichier à nom prévisible dans /tmp.
    contenu = await anyio.to_thread.run_sync(lambda: pdf_bytes(calculer(h)), limiter=RENDUS_PDF)

    return Response(
        content=contenu,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="dossier-dnja-{example}.pdf"',
        },
    )
