# self-dnja

Moteur de prévisionnel **DNJA / DJA** sur 4 ans, à partir d'hypothèses
structurées en YAML. Sortie : compte de résultat année par année +
vérification du seuil EBE/UTH attendu par la DDT + dossier PDF prêt à
présenter.

## Installation

Depuis la racine de SelfFarm-Lite :
```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[facturx,dev]"
```

## Utilisation

### Calcul prévisionnel (console/JSON)
```bash
self-dnja calcul examples/hypotheses-pierroons-realiste.yaml
self-dnja calcul hypotheses.yaml -o previsionnel.json
```

### Génération PDF DDT
```bash
self-dnja pdf hypotheses.yaml -o dossier-dnja.pdf
```

Exemple de sortie console :
```
=== SYNTHÈSE DNJA ===
  Année 1: CA=     6750.00€  EBE=    19685.00€  Résultat=    17355.00€
  Année 4: CA=    22500.00€  EBE=    27935.00€  Résultat=    23775.00€
  EBE/UTH année 4: 27935.00 € (seuil 22000 €) → ✓ ATTEINT
```

## Format YAML d'hypothèses

Voir `examples/hypotheses-pierroons-realiste.yaml` comme référence. Les blocs
principaux :

- `activites` — 1 ou plusieurs activités productives (surface, rendement,
  prix, bio, montée en charge)
- `charges_recurrentes` — intrants, fermages, assurances, certif bio…
- `immobilisations` — matériel amortissable linéaire, avec % subvention
- `aides` — DJA/DNJA, ACJA, CI-AB, écorégime bio, CAB, etc. (étalables sur
  plusieurs années pour lisser l'EBE)
- `cotisations_msa` — cotisation base + barème exonération JA dégressive
- `uth` — Unités Travail Humain (1.0 par défaut = exploitant seul)

## Questionnaire d'intake guidé (SelfHub)

`intake_schema.yaml` décrit un **questionnaire d'installation** destiné à être
rendu comme une page SelfFarm et piloté par le LLM local SelfHub : l'utilisateur
répond en langage terrain (champs libres + cases « je ne sais pas »), le LLM
applique les référentiels embarqués, les règles auto (certification bio,
façonnage CBD, barème MSA, découpage DNJA 80/20…) et les checklists de
complétude par profil, puis assemble l'objet `Hypotheses` passé au moteur.

Sections : `profil`, `productions`, `charges`, `investissements`, `aides`,
`social`, `financement`, `accompagnement`. Conception **neutre** : aucun
prestataire nommé, aucun chiffre présenté comme une promesse (valeurs
indicatives, fourchettes de référence). Garde-fou par défaut : EBE/UTH ≥
seuil + 2 000 €.

## Sources officielles mobilisées

- Seuil EBE/UTH 2026 NA zone défavorisée : https://les-aides.nouvelle-aquitaine.fr/
- Barème exonération MSA JA : https://www.msa.fr/
- PCG agricole : https://www.anc.gouv.fr/

## Moteur de calcul — formules

```
produits_annee_N = Σ activites(quantite_N × prix_ht × facteur_montée_en_charge_N)
charges_annee_N  = Σ charges_recurrentes.montant_annuel_ht
amort_annee_N    = Σ immobilisations (si acquise ≤ N et amortissement pas terminé)
                   .assiette / duree   where assiette = montant × (100 - subv%) / 100
social_annee_N   = cotisation_base × (100 - pct_exoneration_N) / 100
aides_revenu_N   = Σ aides (annee_versement = N, est_subvention_capital = False)

EBE       = produits - charges + aides_revenu
resultat  = EBE - amort - social
```

## Tests

```bash
PYTHONPATH=modules .venv/bin/python -m pytest modules/self_dnja/tests/ -v
```

Couvre le moteur (compte de résultat, RDA, bilan, plan de financement,
`annee_fin`) + le schéma d'intake (`test_intake_schema.py`, dont contrôle
anti-marque).

## Roadmap

- v0.2 : connecteur `self-agri-book` → alimente les hypothèses depuis la compta
  réelle historique (calibration fine)
- v0.3 : mode "scénarios" (comparer 3 YAML avec diff automatique)
- v0.4 : page d'intake guidée (`intake_schema.yaml`) + SelfHub pour saisir les
  hypothèses en langage naturel et ajuster en live
