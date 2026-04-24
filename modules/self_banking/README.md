# self_banking — import de relevés bancaires (MySelf)

Module SelfFarm-Lite pour importer et parser des relevés bancaires au format PDF
(dans un premier temps). 100 % local, aucun agrément DSP2, aucune capture de
données. L'utilisateur exporte son relevé depuis son app bancaire, dépose le
fichier, et le module extrait les transactions normalisées prêtes à être
rapprochées de la compta (`self_agri_book`) et des factures (`self_invoice`).

## Parsers supportés

| Banque | Format | Statut |
|--------|--------|--------|
| Société Générale Particuliers | PDF | ✅ v0.1 — testé sur fixtures générées |
| Crédit Agricole | PDF / CSV / OFX | 🏗️ à venir |
| Boursorama | CSV / OFX | 🏗️ à venir |
| Crédit Mutuel | PDF / CSV | 🏗️ à venir |
| Caisse d'Épargne | PDF / CSV | 🏗️ à venir |
| BNP Paribas | PDF / CSV | 🏗️ à venir |

## Principe « fake-first » pour le développement

Pour éviter toute exposition de données bancaires réelles en développement,
le module utilise des **fixtures factices** générées par
`scripts/generate_sg_fake_statement.py`. Les parsers sont d'abord développés
et testés contre ces fausses données, puis l'utilisateur les valide en local
sur ses vrais relevés sans que le contenu ne transite jamais hors de son poste.

## Test rapide

```bash
# Régénérer les fixtures (si besoin)
PYTHONPATH=modules python scripts/generate_sg_fake_statement.py \
    --output modules/self_banking/fixtures/sg_sample_crediteur.pdf \
    --scenario crediteur --seed 42

# Tester le parser sur une fixture
PYTHONPATH=modules python scripts/test_parser_bank.py \
    modules/self_banking/fixtures/sg_sample_crediteur.pdf

# Tester le parser sur un vrai relevé (aucune donnée ne sort du poste)
PYTHONPATH=modules python scripts/test_parser_bank.py \
    ~/Téléchargements/mon-releve-sg.pdf
```

## Structure normalisée

Chaque transaction extraite suit le modèle `Transaction` :

- `date_operation` : date de l'opération
- `date_valeur` : date de valeur (optionnelle)
- `libelle` : libellé brut tel qu'affiché par la banque
- `debit` / `credit` : montants signés (Decimal, max 2 décimales)
- `type_mouvement` : classification technique (virement émis/reçu, prélèvement,
  carte bancaire, chèque, retrait DAB, dépôt espèces, frais, intérêts, inconnu)
- `reference` : référence bancaire si présente (format `REF: XXX`)
- `contrepartie` : bénéficiaire/émetteur détecté depuis les sous-lignes

## Validation du parsing

La classe `Releve` expose un indicateur `ecart_parsing` :

```python
ecart = releve.solde_final - (releve.solde_precedent + credits - debits)
```

Si ≈ 0 → parsing OK. Si > quelques centimes → bug parseur, à signaler.

## Licence

AGPL-3.0-or-later (convention MySelf 19/04/2026).
