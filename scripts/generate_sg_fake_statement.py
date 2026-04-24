"""
Générateur de relevés bancaires SG Particuliers FACTICES.

Produit un PDF respectant le gabarit standard des relevés Société Générale
Particuliers (2024-2026), avec des données 100 % fictives. Sert de fixture
de test pour le parser self_banking, sans jamais exposer de vraies données
bancaires utilisateur.

Usage :
    python scripts/generate_sg_fake_statement.py \
        --output modules/self_banking/fixtures/sg_sample_debiteur.pdf \
        --scenario debiteur \
        --seed 42
"""

from __future__ import annotations

import argparse
import random
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


# --- Pools de données fictives -------------------------------------------------

BENEFICIAIRES_VIR_EMIS = [
    "FOURNISSEUR-ALPHA", "GARAGE-CENTRAL", "IMPOTS-REVENU",
    "EDF-SERVICES-CLIENT", "ORANGE-FRANCE", "SOCIETE-FICTIVE-SARL",
    "LOYER-MME-DUPONT", "FOURNISSEUR-BETA",
]
EMETTEURS_VIR_RECU = [
    "CLIENT-GAMMA", "POLE-EMPLOI", "CAF-VIREMENT", "CLIENT-DELTA",
    "REMBOURSEMENT-SANTE", "TRESOR-PUBLIC",
]
EMETTEURS_PRLV = [
    "ASSURANCE-MULTI", "MUTUELLE-SANTE", "EDF-PRELEVEMENT",
    "ENGIE-ENERGIE", "ABONNEMENT-TELECOM", "ORANGE-MOBILE",
    "NETFLIX-SARL",
]
MARCHANDS_CB = [
    "SUPERMARCHE-CENTRE", "STATION-ESSENCE-A", "PHARMACIE-CENTRALE",
    "BOULANGERIE-LOCALE", "RESTAURANT-CHEZ-X", "AMAZON-EU",
    "DECATHLON-MAGASIN", "LECLERC-STATION", "BRICOLAGE-CENTRE",
]


@dataclass
class Config:
    scenario: str  # debiteur | crediteur | tangent
    periode_debut: date
    periode_fin: date
    solde_precedent: Decimal
    nb_mouvements: int
    output: Path
    seed: int

    titulaire_nom: str = "M. MARTIN DUPONT"
    titulaire_adresse_l1: str = "10 RUE DE LA PAIX"
    titulaire_adresse_l2: str = "75001 PARIS"
    num_compte: str = "30003 00000 00000000000 00"
    code_client: str = "00000000"
    agence_nom: str = "PARIS CENTRE"
    agence_tel: str = "01 00 00 00 00"
    conseiller: str = "MR JEAN MARTIN"
    conseiller_tel: str = "01 00 00 00 01"


def _make_mouvement(config: Config, jour: date) -> dict:
    """Génère un mouvement aléatoire plausible."""
    type_choice = random.choices(
        ["vir_emis", "vir_recu", "prlv", "cb", "frais"],
        weights=[15, 10, 25, 45, 5],
    )[0]

    if type_choice == "vir_emis":
        return {
            "date": jour,
            "date_valeur": jour,
            "nature": "VIR INSTANTANE EMIS LOGITEL",
            "sous_lignes": [
                f"POUR: {random.choice(BENEFICIAIRES_VIR_EMIS)}",
                f"DATE: {jour.strftime('%d/%m/%Y')} {random.randint(8, 20):02d}:{random.randint(0, 59):02d}",
                f"REF: {random.randint(10**11, 10**12 - 1)}",
            ],
            "debit": Decimal(random.randint(1000, 50000)) / Decimal("100"),
            "credit": None,
        }
    elif type_choice == "vir_recu":
        return {
            "date": jour,
            "date_valeur": jour,
            "nature": f"VIR RECU {random.randint(10**8, 10**9 - 1)}S",
            "sous_lignes": [
                f"DE: {random.choice(EMETTEURS_VIR_RECU)}",
                f"MOTIF: Virement",
                f"REF: A{random.randint(10**11, 10**12 - 1)}",
            ],
            "debit": None,
            "credit": Decimal(random.randint(500, 200000)) / Decimal("100"),
        }
    elif type_choice == "prlv":
        return {
            "date": jour,
            "date_valeur": jour,
            "nature": f"PRLV SEPA {random.choice(EMETTEURS_PRLV)}",
            "sous_lignes": [
                f"MANDAT: {random.randint(10**8, 10**9 - 1)}",
                f"REF: {random.randint(10**11, 10**12 - 1)}",
            ],
            "debit": Decimal(random.randint(500, 30000)) / Decimal("100"),
            "credit": None,
        }
    elif type_choice == "cb":
        return {
            "date": jour,
            "date_valeur": jour,
            "nature": f"ACHAT CB {random.choice(MARCHANDS_CB)} {jour.strftime('%d/%m')}",
            "sous_lignes": [
                f"CARTE NUMERO XXXX{random.randint(1000, 9999)}",
            ],
            "debit": Decimal(random.randint(200, 15000)) / Decimal("100"),
            "credit": None,
        }
    else:  # frais
        return {
            "date": jour,
            "date_valeur": jour,
            "nature": "COMMISSIONS D'INTERVENTION",
            "sous_lignes": [],
            "debit": Decimal(random.randint(500, 1500)) / Decimal("100"),
            "credit": None,
        }


def _generate_mouvements(config: Config) -> list[dict]:
    """Génère une série cohérente de mouvements sur la période."""
    random.seed(config.seed)
    mouvements = []
    jours = (config.periode_fin - config.periode_debut).days
    for _ in range(config.nb_mouvements):
        offset = random.randint(1, max(1, jours - 1))
        jour = config.periode_debut + timedelta(days=offset)
        mouvements.append(_make_mouvement(config, jour))
    mouvements.sort(key=lambda m: m["date"])
    return mouvements


def _format_amount(amount: Decimal) -> str:
    """Format français : 1 234,56 (espace insécable pour les milliers)."""
    s = f"{amount:.2f}".replace(".", ",")
    # Milliers : découpage manuel
    parts = s.split(",")
    entier = parts[0]
    if len(entier) > 3:
        entier = " ".join([entier[max(0, i - 3):i] for i in range(len(entier), 0, -3)][::-1])
    return f"{entier},{parts[1]}"


def render_pdf(config: Config, mouvements: list[dict]) -> None:
    """Génère le PDF avec ReportLab en respectant le gabarit SG."""
    c = canvas.Canvas(str(config.output), pagesize=A4)
    width, height = A4

    x_margin = 15 * mm
    y = height - 18 * mm

    # --- En-tête principal ---
    c.setFont("Helvetica-Bold", 11)
    c.drawString(x_margin, y, "RELEVÉ DE COMPTE")
    y -= 5 * mm
    c.setFont("Helvetica", 9)
    c.drawString(x_margin, y, "COMPTE DE PARTICULIER - en euros")
    y -= 4 * mm
    c.drawString(x_margin, y, f"n° {config.num_compte}")
    y -= 4 * mm
    c.drawString(
        x_margin,
        y,
        f"du {config.periode_debut.strftime('%d/%m/%Y')} au {config.periode_fin.strftime('%d/%m/%Y')}",
    )
    y -= 4 * mm
    c.drawString(x_margin, y, "envoi n°3 Page 1/1")
    y -= 8 * mm

    # --- Bloc contacts (colonne droite) ---
    c.setFont("Helvetica-Bold", 8)
    c.drawString(width - 80 * mm, height - 18 * mm, "VOS CONTACTS")
    c.setFont("Helvetica", 7)
    c.drawString(width - 80 * mm, height - 23 * mm, "Votre Banque à Distance")
    c.drawString(width - 80 * mm, height - 27 * mm, f"Code client: {config.code_client}")
    c.drawString(width - 80 * mm, height - 31 * mm, "sur internet : particuliers.sg.fr")
    c.drawString(width - 80 * mm, height - 35 * mm, "par téléphone au 39331")

    # --- Bloc titulaire ---
    c.setFont("Helvetica", 9)
    c.drawString(x_margin, y, config.titulaire_nom)
    y -= 4 * mm
    c.drawString(x_margin, y, config.titulaire_adresse_l1)
    y -= 4 * mm
    c.drawString(x_margin, y, config.titulaire_adresse_l2)
    y -= 8 * mm

    # --- Agence ---
    c.setFont("Helvetica-Bold", 8)
    c.drawString(x_margin, y, f"Votre agence {config.agence_nom}")
    y -= 4 * mm
    c.setFont("Helvetica", 8)
    c.drawString(x_margin, y, f"par téléphone : {config.agence_tel}")
    y -= 6 * mm
    c.setFont("Helvetica-Bold", 8)
    c.drawString(x_margin, y, "Votre conseiller en agence")
    y -= 4 * mm
    c.setFont("Helvetica", 8)
    c.drawString(x_margin, y, config.conseiller)
    y -= 4 * mm
    c.drawString(x_margin, y, f"par téléphone : {config.conseiller_tel}")
    y -= 10 * mm

    # --- Solde info ---
    solde_final = config.solde_precedent
    for m in mouvements:
        if m["debit"]:
            solde_final -= m["debit"]
        if m["credit"]:
            solde_final += m["credit"]

    c.setFont("Helvetica", 9)
    signe = "débiteur" if solde_final < 0 else "créditeur"
    c.drawString(
        x_margin,
        y,
        f"Nous vous informons qu'au {config.periode_fin.strftime('%d/%m/%Y')}, "
        f"votre solde est {signe} de {_format_amount(solde_final)} euros.",
    )
    y -= 10 * mm

    # --- Tableau opérations ---
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x_margin, y, "RELEVÉ DES OPÉRATIONS")
    y -= 6 * mm
    c.setFont("Helvetica-Bold", 8)
    c.drawString(x_margin, y, "Date")
    c.drawString(x_margin + 20 * mm, y, "Valeur")
    c.drawString(x_margin + 40 * mm, y, "Nature de l'opération")
    c.drawString(width - 50 * mm, y, "Débit")
    c.drawString(width - 25 * mm, y, "Crédit")
    y -= 2 * mm
    c.line(x_margin, y, width - x_margin, y)
    y -= 4 * mm

    # Solde précédent
    c.setFont("Helvetica", 8)
    c.drawString(x_margin, y, f"SOLDE PRÉCÉDENT AU {config.periode_debut.strftime('%d/%m/%Y')}")
    if config.solde_precedent >= 0:
        c.drawRightString(width - 15 * mm, y, _format_amount(config.solde_precedent))
    else:
        c.drawRightString(width - 40 * mm, y, _format_amount(-config.solde_precedent))
    y -= 5 * mm

    # Mouvements
    for m in mouvements:
        if y < 30 * mm:
            c.showPage()
            y = height - 20 * mm
            c.setFont("Helvetica", 8)
        c.drawString(x_margin, y, m["date"].strftime("%d/%m/%Y"))
        c.drawString(x_margin + 20 * mm, y, m["date_valeur"].strftime("%d/%m/%Y"))
        c.drawString(x_margin + 40 * mm, y, m["nature"][:50])
        if m["debit"]:
            c.drawRightString(width - 40 * mm, y, _format_amount(m["debit"]))
        if m["credit"]:
            c.drawRightString(width - 15 * mm, y, _format_amount(m["credit"]))
        y -= 4 * mm
        for sous in m["sous_lignes"]:
            c.setFont("Helvetica", 7)
            c.drawString(x_margin + 40 * mm, y, sous[:60])
            y -= 3.5 * mm
        c.setFont("Helvetica", 8)
        y -= 1 * mm

    # Solde final
    y -= 3 * mm
    c.line(x_margin, y, width - x_margin, y)
    y -= 5 * mm
    c.setFont("Helvetica-Bold", 8)
    c.drawString(x_margin, y, f"*** SOLDE AU {config.periode_fin.strftime('%d/%m/%Y')} ***")
    if solde_final >= 0:
        c.drawRightString(width - 15 * mm, y, _format_amount(solde_final))
    else:
        c.drawRightString(width - 40 * mm, y, _format_amount(-solde_final))

    c.save()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--scenario",
        choices=["debiteur", "crediteur", "tangent"],
        default="crediteur",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--nb-mouvements", type=int, default=20)
    parser.add_argument("--periode-debut", type=str, default="2026-02-27")
    parser.add_argument("--periode-fin", type=str, default="2026-03-26")
    args = parser.parse_args()

    soldes_par_scenario = {
        "debiteur": Decimal("150.00"),
        "crediteur": Decimal("2500.00"),
        "tangent": Decimal("50.00"),
    }

    config = Config(
        scenario=args.scenario,
        periode_debut=date.fromisoformat(args.periode_debut),
        periode_fin=date.fromisoformat(args.periode_fin),
        solde_precedent=soldes_par_scenario[args.scenario],
        nb_mouvements=args.nb_mouvements,
        output=args.output,
        seed=args.seed,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    mouvements = _generate_mouvements(config)
    render_pdf(config, mouvements)
    print(f"✓ PDF SG factice généré : {args.output}")
    print(f"  Scénario : {config.scenario}")
    print(f"  Période : {config.periode_debut} → {config.periode_fin}")
    print(f"  Mouvements : {len(mouvements)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
