"""
Génération du dossier PDF DNJA depuis un PrevisionnelDnja.

Rend le template Jinja2 `templates/dossier-dnja.html.j2` en PDF via WeasyPrint.
Conformité visée : PDF/A-ready pour archivage (fontes embarquées, pas de JS).
"""

from __future__ import annotations

import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML

from self_dnja.models import PrevisionnelDnja

log = logging.getLogger("self-dnja")

TEMPLATES_DIR = Path(__file__).parent / "templates"


def render_pdf(result: PrevisionnelDnja, out_path: Path) -> Path:
    """Génère le PDF à `out_path`. Retourne le chemin final."""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("dossier-dnja.html.j2")
    payload = result.model_dump(mode="json")

    # Annexe interne « capacité & réserve » : écart capacité de production − quantité
    # déclarée vendue, valorisé au prix de vente. Affiché seulement si le flag est ON.
    reserves = []
    for a in payload["hypotheses"]["activites"]:
        cap = a.get("capacite_annuelle")
        if cap is None or a.get("quantite_annuelle") is None:
            continue
        cap_f = float(cap)
        vendu_f = float(a["quantite_annuelle"])
        if cap_f <= vendu_f:
            continue
        reserve_qte = cap_f - vendu_f
        reserves.append({
            "nom": a["nom"],
            "unite": a["unite_vente"],
            "capacite": cap_f,
            "vendu": vendu_f,
            "reserve_qte": reserve_qte,
            "prix": float(a["prix_vente_ht"]),
            "valeur_reserve": reserve_qte * float(a["prix_vente_ht"]),
        })

    # Le template reçoit des dicts, pas les modèles Pydantic : les propriétés
    # calculées (TempsTravail.lignes) n'y survivent pas. On les résout ici.
    tt = payload["hypotheses"].get("temps_travail") or {}
    tt_lignes = [(nom, h) for nom, h in (tt.get("postes") or {}).items() if h]
    tt_lignes += [(lib, tt[champ]) for champ, lib in (
        ("chanvre_culture", "Culture chanvre"),
        ("transformation_huile", "Transformation"),
        ("maraichage", "Maraîchage"),
        ("vente_admin", "Vente et administratif"),
        ("autre", "Autre"),
    ) if tt.get(champ)]

    html_str = template.render(
        hypotheses=payload["hypotheses"],
        temps_travail_lignes=tt_lignes,
        temps_travail_total=sum(h for _, h in tt_lignes),
        lignes=payload["lignes"],
        version=payload["version"],
        genere_le=payload["genere_le"],
        ebe_uth_atteint=payload["ebe_uth_atteint"],
        ebe_uth_seuil=payload["ebe_uth_seuil"],
        ebe_uth_annee_cible=payload["ebe_uth_annee_cible"],
        ratios_n4=payload.get("ratios_n4"),
        scenarios_stress=payload.get("scenarios_stress") or [],
        bilan_n4=payload.get("bilan_n4"),
        marges_brutes_n4=payload.get("marges_brutes_n4") or [],
        plan_financement=payload.get("plan_financement"),
        plan_tresorerie=payload.get("plan_tresorerie") or [],
        seuil_rentabilite=payload.get("seuil_rentabilite"),
        caf_annuelles=payload.get("caf_annuelles") or {},
    )
    log.info("Rendu HTML terminé, taille=%d caractères", len(html_str))
    HTML(string=html_str, base_url=str(TEMPLATES_DIR)).write_pdf(str(out_path))
    log.info("PDF écrit : %s", out_path)
    return out_path
