"""Route DNJA : simulateur + génération PDF."""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from self_dnja.engine import calculer
from self_dnja.models import Hypotheses
from self_dnja.pdf import render_pdf

from webapp import __version__

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
    labels = {
        "hypotheses-pierroons-chambre": ("Prévisionnel CHAMBRE 🏛️",
                                          "Version officielle CDOA — matériel neuf, charges valorisées"),
        "hypotheses-pierroons-perso": ("Prévisionnel PERSO 🔧",
                                        "Vision réelle terrain — matériel DIY/occase, vraie marge"),
        "hypotheses-pierroons-huile-cbd": ("Scénario huile CBD 🛢️",
                                            "Installation graduelle mix fleurs + huile + maraîchage"),
        "hypotheses-pierroons-realiste": ("Scénario réaliste 🌱",
                                            "Ancien modèle fleurs brutes — à titre comparatif"),
        "hypotheses-pierroons": ("Scénario optimiste ⭐",
                                  "Ancien modèle optimiste pour comparatif"),
        "hypotheses-demo-publique": ("Démo publique 🌻",
                                      "JA fictif·ve Dordogne — maraîchage bio + PPAM (données 100 % anonymisées)"),
    }
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
        "dnja/index.html",
        {
            "request": request,
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
        "dnja/_result.html",
        {
            "request": request,
            "version": __version__,
            "result": result.model_dump(mode="json"),
            "example": example,
        },
    )


@router.get("/editor", response_class=HTMLResponse)
async def dnja_editor_index(request: Request):
    return templates.TemplateResponse(
        "dnja/editor.html",
        {"request": request, "version": __version__, "examples": _list_examples()},
    )


@router.get("/editor/load", response_class=HTMLResponse)
async def dnja_editor_load(request: Request, slug: str):
    h = _load_example(slug)
    return templates.TemplateResponse(
        "dnja/_editor_form.html",
        {
            "request": request,
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
        "dnja/_result.html",
        {
            "request": request,
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


@router.get("/compare", response_class=HTMLResponse)
async def dnja_compare_index(request: Request):
    examples = _list_examples()
    return templates.TemplateResponse(
        "dnja/compare.html",
        {
            "request": request,
            "version": __version__,
            "examples": examples,
            "default_a": "hypotheses-pierroons-chambre" if any(e["slug"] == "hypotheses-pierroons-chambre" for e in examples) else examples[0]["slug"],
            "default_b": "hypotheses-pierroons-perso" if any(e["slug"] == "hypotheses-pierroons-perso" for e in examples) else (examples[1]["slug"] if len(examples) > 1 else examples[0]["slug"]),
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
        "dnja/_compare_result.html",
        {
            "request": request,
            "a": {"slug": a, "label": examples[a]["label"], "result": ra.model_dump(mode="json")},
            "b": {"slug": b, "label": examples[b]["label"], "result": rb.model_dump(mode="json")},
            "comparison": comparison,
            "synthese": synth,
        },
    )


@router.get("/pdf")
async def dnja_pdf(example: str):
    """Télécharge le PDF d'un scénario."""
    h = _load_example(example)
    result = calculer(h)
    # Fichier temporaire mémoire

    # Re-utilise la fonction render_pdf qui écrit sur disque
    tmp_path = Path(f"/tmp/selffarm-dnja-{example}.pdf")
    render_pdf(result, tmp_path)
    pdf_bytes = tmp_path.read_bytes()
    tmp_path.unlink(missing_ok=True)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="dossier-dnja-{example}.pdf"',
        },
    )
