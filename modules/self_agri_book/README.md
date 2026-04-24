# self-agri-book

**Hub comptable central de SelfFarm-Lite** — journal + grand livre + bilan +
compte de résultat + export FEC DGFIP, local-first, alimenté en temps réel par
tous les autres modules métier.

## Statut : **v0.2 — hub live** (24-25 avril 2026)

Implémentation en production sur `selffarm.my-self.fr`.
Tous les flux suivants alimentent le hub via auto-écritures :

| Module source | Comptes débités / crédités | Action |
|---------------|---------------------------|--------|
| `self_invoice` | 411 / 701 | Génération facture Factur-X → écriture auto de vente |
| `self_compta_manuel` | 411 / 701 | Saisie vente rapide (B2B facturable, B2C non-facturable) |
| `self_achats` | 6011-6062-613.../401 | Achat fournisseur (semences, carburant, assurance…) |
| `self_banking` | 512 / 411, 6xxx/401, 6271/512 | Import relevé bancaire → lettrage auto, prélèvements, frais |

Tous partagent la même table SQLite `ecritures_comptables`. Pas de double
saisie. Dédup par `(source_module, source_id)` garantie.

## Ce qui est livré

### Architecture de données

- `data/pcg-agricole-2026.yaml` — Plan Comptable Général Agricole officiel
  2026 (sourcé ANC + arrêté 1986 PCGA + règlement ANC 2019-01 biens vivants).
  9 classes, 64 comptes à 2 chiffres, 396 sous-comptes dont 133
  `agri_specifique: true`.
- `models.py` — Modèles Pydantic v2 : `Compte`, `Ecriture`, `LigneEcriture`,
  `TypeJournal`, `SensEcriture` avec validator `_equilibre_debit_credit`
  automatique.
- `storage.py` — Couche SQLite : schéma + CRUD + fonctions d'agrégation.

### Fonctions Python exposées

```python
from self_agri_book.storage import (
    save_ecriture,              # Saisie + dédup source_module/source_id
    find_ecriture_by_source,    # Lookup idempotent
    list_ecritures,             # Journal chrono
    balance_par_compte,         # Balance par code compte
    stats_globales,             # Nb écritures + volume + par source
    resultat_data,              # Compte de résultat (produits 7 / charges 6)
    bilan_data,                 # Bilan (actif classes 2/3/4/5, passif 1/4 + résultat)
    export_fec,                 # FEC DGFIP 18 colonnes conforme
    reset_demo,                 # Purge (démo publique)
)
```

### Routes webapp

| Route | Rôle |
|-------|------|
| `GET /compta` | Journal chronologique + balance + stats globales + boutons démo |
| `GET /compta/resultat` | Compte de résultat — produits vs charges → résultat net |
| `GET /compta/bilan` | Bilan comptable — actif ↔ passif + résultat injecté en capitaux propres |
| `GET /compta/export-fec` | Fichier FEC tab-separated 18 colonnes (nom : `<siren>FEC<YYYYMMDD>.txt`) |
| `GET /compta/facture-du-journal` | PDF Factur-X consolidant les ventes B2B 411/701 du journal |
| `POST /compta/generer-vente` | Ajoute vente rapide aléatoire (B2B ou B2C) |
| `POST /compta/generer-achat` | Ajoute achat aléatoire (charges 6xxx/401) |
| `POST /compta/importer-releve` | Simule import relevé banque (self_banking) : lettrage auto + prélèvements + frais |
| `POST /compta/rejouer-derniere-vente` | Démo dédup par `source_module + source_id` |
| `POST /compta/reset-demo` | Purge toutes les écritures (démo publique uniquement) |

### Conformité FR

- **Plan comptable** : PCG Agricole officiel 2026 (ANC + arrêté 1986 + règlement ANC 2019-01).
- **Export FEC** : conforme art. L47 A-I LPF + BOI-CF-IOR-60-40-10.
  18 colonnes obligatoires, tab-separated, UTF-8, montants au format `0,00`
  (virgule décimale FR), nom `<siren>FEC<YYYYMMDD>.txt`.
- **Validation équilibre** : chaque écriture doit avoir Σ(débits) = Σ(crédits),
  contrôle par Pydantic model validator (refus d'insertion sinon).
- **Traçabilité** : chaque écriture garde `source_module`, `source_id`,
  `created_at` (date validation), `metadata_json` (référence pièce d'origine).

## Localisation

- DB locale par défaut : `~/.selffarm/compta.db`
- Override via env var `SELFFARM_COMPTA_DB=/chemin/vers/compta.db`
- Démo publique : `/opt/selffarm-lite/data/compta.db` (partagée entre visiteurs
  de `selffarm.my-self.fr` — pas de multi-tenant côté démo, c'est volontaire).

## Principe hub central

Une seule source de vérité — la table `ecritures_comptables` :

```
┌────────────────────────────────────────────────────────┐
│  MODULE COMPTA (hub central — self_agri_book)          │
│  SQLite : ecritures_comptables                         │
│  (id, date, compte_dr, compte_cr, montant,             │
│   libellé, source_module, source_id, metadata_json)    │
└────▲───────▲───────▲───────▲───────▲───────────────────┘
     │       │       │       │       │
┌────┴──┐ ┌──┴───┐ ┌─┴───┐ ┌─┴────┐ ┌┴───────┐
│Invoice│ │Achats│ │Immos│ │Banking│ │Manuel │
│(701)  │ │(6xxx)│ │(215)│ │ (512) │ │ vente │
└───────┘ └──────┘ └─────┘ └───────┘ └───────┘
```

Chaque module métier :
1. Gère son périmètre fonctionnel (génération PDF facture, parsing banque…).
2. **Déclare son auto-écriture** vers le hub via `save_ecriture(...)`.
3. Fournit un `source_module` et un `source_id` uniques pour garantir l'idempotence
   (retenter la même pièce → aucun doublon créé).

## Règle d'or

Toute nouvelle fonctionnalité métier dans SelfFarm-Lite doit **déclarer
comment elle génère son écriture compta auto**. Pas de module "à part" qui
saisit dans sa propre base sans remonter vers le hub.

## Roadmap

### v0.3 (weekend 8-10 mai 2026)
- Saisie manuelle totalement libre (formulaire compte + montant + date)
- Grand livre détaillé par compte (drill-down)
- Lettrage manuel (au-delà du lettrage auto 512/411 du banking hook)

### v0.4 (été 2026)
- Amortissements d'immobilisations (tableau 2xxx + dotations 68xx auto)
- Clôture d'exercice + report à nouveau (120 → 110)
- Multi-exercice (exercice décalé supporté : `debut_exercice_mois`)
- TVA collectée/déductible séparée (44571/44566) avec déclaration mensuelle/trimestrielle

### v1.0 (automne 2026)
- Import OFX/CSV multi-banques (Crédit Agricole, Boursorama, Crédit Mutuel, Caisse d'Épargne, BNP)
- Export liasse fiscale (2031, 2139-SD, 2031-SD)
- Passerelle Ekylibre (migration compta JA → ERP)

## Licence

AGPL-3.0-or-later.
