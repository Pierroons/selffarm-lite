"""
Script de test user-friendly pour les parsers de relevés bancaires.

Usage :
    python scripts/test_parser_bank.py <chemin_vers_pdf>

Exemples :
    python scripts/test_parser_bank.py modules/self_banking/fixtures/sg_sample_crediteur.pdf
    python scripts/test_parser_bank.py ~/Téléchargements/mon-releve-sg.pdf

Le script ne modifie AUCUN fichier. Il affiche uniquement le résultat
du parsing dans le terminal — parfait pour valider le parser sur un
vrai relevé sans exposer les données.
"""

from __future__ import annotations

import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 1

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"✗ Fichier introuvable : {path}", file=sys.stderr)
        return 1

    # Import différé pour afficher l'erreur si module absent
    try:
        from self_banking.parsers import parse_pdf
    except ImportError as e:
        print(f"✗ Module self_banking introuvable : {e}", file=sys.stderr)
        print("  Lance depuis la racine du repo avec PYTHONPATH=modules")
        return 1

    try:
        releve = parse_pdf(path)
    except NotImplementedError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"✗ Erreur parsing : {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    # --- Affichage résumé ---
    print("=" * 70)
    print(f"RELEVÉ {releve.banque} — {path.name}")
    print("=" * 70)
    print(f"Période          : {releve.periode_debut} → {releve.periode_fin}")
    print(f"Solde précédent  : {releve.solde_precedent:>12} €")
    print(f"Solde final      : {releve.solde_final:>12} €")
    print(f"Transactions     : {len(releve.transactions)}")
    print(f"Total débits     : {releve.total_debits:>12} €")
    print(f"Total crédits    : {releve.total_credits:>12} €")
    print(f"Solde calculé    : {releve.solde_calcule:>12} €")
    ecart = releve.ecart_parsing
    flag = "✓ OK" if abs(float(ecart)) < 0.01 else f"✗ ÉCART {ecart} €"
    print(f"Vérif parsing    : {flag}")

    # --- Répartition par type ---
    print()
    print("Répartition par type :")
    types = Counter(t.type_mouvement for t in releve.transactions)
    for tm, n in types.most_common():
        total = sum(
            (t.debit or Decimal("0")) + (t.credit or Decimal("0"))
            for t in releve.transactions
            if t.type_mouvement == tm
        )
        print(f"  {tm:20} : {n:3} mouvement(s)  total {total} €")

    # --- Détail transactions ---
    print()
    print("Détail transactions :")
    print(f"  {'Date':10}  {'Type':17}  {'Débit':>10}  {'Crédit':>10}  {'Contrepartie':25}  Libellé")
    print("  " + "-" * 110)
    for t in releve.transactions:
        debit_str = f"{t.debit}" if t.debit else ""
        credit_str = f"{t.credit}" if t.credit else ""
        contrepartie = (t.contrepartie or "")[:25]
        libelle = t.libelle[:40]
        print(
            f"  {t.date_operation}  {t.type_mouvement:17}  "
            f"{debit_str:>10}  {credit_str:>10}  {contrepartie:25}  {libelle}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
