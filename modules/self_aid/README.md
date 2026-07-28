# self-aid

Catalogue **ouvert, sourcé et filtrable** des aides publiques. Premier
vertical : aides agricoles 2026. Architecture extensible aux autres
statuts (salariat, demandeur d'emploi, étudiant, artiste-auteur…).

## Particularités

- **Sources primaires officielles uniquement** (Légifrance, BOFiP,
  service-public, mesdemarches.agriculture, FranceAgriMer, MSA,
  portails régionaux). Aucun blog ni site marchand en autorité.
- **Chaque aide datée** : `source.date_maj_vu` indique quand la source a été
  vérifiée pour la dernière fois.
- **Cumulabilité exprimée explicitement** : chaque aide déclare avec qui elle
  se cumule et qui elle exclut.
- **Schéma extensible** : nouveaux statuts ajoutables en créant un nouveau
  YAML dans `data/` sans toucher au code.

## Utilisation

```bash
self-aid list
self-aid show acja-2026
self-aid search --statut ja-installation
self-aid search --bio --zone France
self-aid search --mot-cle chanvre
self-aid search --categorie credit_impot
```

## Structure YAML

Chaque aide est un bloc sous la clé `aides:` avec :
- `id` (slug court unique)
- `nom` (libellé officiel complet)
- `categorie` (installation, revenu, credit_impot, cotisation…)
- `montant` (fixe/variable avec min/max, unité €, €/ha, €/ha/an…)
- `conditions` (âge, zone, formation, autres critères)
- `cumul_possible_avec` / `exclut` (IDs d'autres aides)
- `source` (URL, autorité, date_maj_vu, extrait_citation)

## Contribuer une nouvelle aide

1. Identifier la source primaire officielle (ordre d'autorité strict)
2. Ajouter un bloc YAML dans `data/aides-agri-2026.yaml` (ou créer un
   nouveau fichier pour un autre statut)
3. Mettre `date_maj_vu` à la date de vérification
4. Citer l'extrait officiel qui justifie le montant

## Dataset versionné — 15 aides JA nationales et régionales 2026

Les aides **départementales** (conseil départemental, montants DNJA
régionalisés) dépendent du territoire : elles se placent dans
`data/local/`, que le dépôt ne versionne pas. Le loader additionne
les deux dossiers.

| ID | Nom | Montant |
|---|---|---|
| aita-diagnostic-na-2026 | AITA diagnostic NA | 599,25 € |
| aita-etude-eco-na-2026 | AITA étude économique NA | 599,25 € |
| acja-2026 | ACJA (aide complémentaire revenu JA) | 4 300 – 4 469 €/an |
| ecoregime-bio-2026 | Écorégime PAC bio | 93,39 – 110 €/ha/an |
| chanvre-couple-2026 | Aide couplée chanvre | 67 – 97 €/ha |
| ci-ab-2026 | Crédit d'impôt AB | 4 500 €/an |
| ci-hve-2026 | Crédit d'impôt HVE | 2 500 € |
| dep-73-cgi-2026 | Déduction pour Épargne de Précaution | 0 – 50 585 €/ex |
| exo-msa-ja-2026 | Exo cotisations MSA JA | 944 – 4 089 €/an |
| cab-bio-2026 | Aide à la Conversion AB | 44 – 900 €/ha/an |

Enveloppe cumulée indicative pour un profil JA bio 1 ha : **82 000 – 92 500 €
sur 5 ans**.

## Roadmap

- v0.2 : moteur de recommandation "top 5 aides pour ton profil" basé sur
  questionnaire structuré
- v0.3 : nouveau vertical `aides-salariat.yaml` (aides au retour à l'emploi,
  formation professionnelle, mobilité)
- v0.4 : mode TUI interactif
- v0.5 : base de données SQLite indexée (si le YAML devient trop gros)
