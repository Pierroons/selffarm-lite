# self_culture — plan de culture, assolement, planning hebdo

Module agricole opérationnel pour piloter une exploitation maraîchère ou
polyculture : catalogue de variétés, parcelles, plan de culture annuel,
assolement pluriannuel et planning hebdomadaire des tâches.

> **Statut actuel** : `0.1.0-prep` — squelette + catalogue YAML + modèles +
> migrations en draft + tests. **Pas encore wiré** dans `webapp/main.py`.
> Activation officielle prévue Phase 1 le 11 mai 2026 (cf. plan).

## Objectifs

Combler le seul angle mort fonctionnel restant de SelfFarm-Lite face à
*Ouvretaferme* : le **pilotage opérationnel** de la production.

- Catalogue de **38 variétés AB** maraîchage + chanvre Kompolti + 7 engrais verts (catalogue de base, extensible par l'utilisateur)
- **Parcelles cadastrales** + **planches** maraîchères (extension du module `self_parcelles`)
- **Plan de culture annuel** : qui se sème où, quand, à quelle densité, pour quel rendement attendu
- **Assolement pluriannuel** (5-7 ans) avec validation de rotation et suggestion d'engrais verts intercalaires
- **Planning hebdomadaire** auto-généré depuis le plan de culture, suivi temps de travail prévi vs réel, export ICS
- **Intégration native** au hub compta `self_agri_book` (achat semence → écriture 601 auto liée au plan de culture)
- **Intégration native** au prévisionnel `self_dnja` (rendements prévus alimentent le RDA SMIC du dossier JA)

## Architecture

```
modules/self_culture/
├── __init__.py                     # __version__, docstring
├── models.py                       # Pydantic v2 (Variete, Parcelle, Planche, PlanCulture, AssolementCycle, Tache)
├── catalog.py                      # Loader YAML + filtres (famille, catégorie, saison, mot-clé)
├── storage.py                      # SQLite + 6 migrations (4→9, draft non wirées)
├── data/
│   └── varietes-references.yaml    # 38 variétés curated AB + chanvre + engrais verts
├── tests/
│   └── test_catalog.py             # 16 tests pytest (catalogue + filtres)
└── README.md
```

## Catalogue de variétés

**Source de vérité** : `data/varietes-references.yaml` versionné dans le repo.

**Couverture actuelle** :
- 9 familles botaniques (Solanaceae, Apiaceae, Brassicaceae, Amaryllidaceae, Fabaceae, Cucurbitaceae, Amaranthaceae, Asteraceae, Poaceae, Lamiaceae, Polygonaceae, Boraginaceae, Cannabaceae)
- 31 légumes courants en AB (tomate, carotte, salade, pomme de terre, courgette, etc.)
- 2 aromatiques (basilic, persil, menthe)
- 1 industriel (chanvre Kompolti AB Genscore)
- 7 engrais verts (sarrasin, phacélie, moutarde, vesce, trèfle incarnat, féverole, luzerne)

**Sourcing agronomique** : ITAB, GEVES, retours de terrain de maraîchers + sélectionneurs spécialisés (chanvre).

**Extension** : l'utilisateur peut ajouter ses propres variétés via la table SQL `varietes_user` (formulaire UI prévu Phase 1 webapp).

## Modèle de données SQL (draft)

6 tables nouvelles, migrations 4 → 9 (poursuit la séquence du hub compta `self_agri_book`).

| Migration | Table | Rôle |
|---|---|---|
| 4 | `varietes_user` | Catalogue (héritage YAML + ajouts perso) |
| 5 | `parcelles` | Parcelles cadastrales (étend `self_parcelles`) |
| 6 | `planches` | Subdivisions des parcelles |
| 7 | `plan_culture` | Assignation `(planche × variété × campagne)` |
| 8 | `assolement_cycle` | Vue pluriannuelle pour rotation |
| 9 | `taches_planning` | Tâches hebdo (auto-générées + manuelles) |

**Toutes les tables incluent `metadata_json TEXT`** pour l'extensibilité future et un FK logique vers `ecritures_comptables` via `source_module='self_culture'` quand pertinent.

## Tests

```bash
PYTHONPATH=modules pytest modules/self_culture/tests/ -v
```

**16 tests verts** couvrant :
- Chargement du catalogue YAML + validation Pydantic v2
- Unicité des slugs
- Présence des variétés clés (chanvre Kompolti, légumineuses engrais verts)
- Filtres par famille / catégorie / saison / mot-clé
- Cohérence calendaire et rendements
- Diversité botanique (≥ 8 familles)

## Roadmap

| Phase | Cible | Calendrier | Livrables |
|---|---|---|---|
| **0.1.0-prep** | ✅ Fait | 28 avril 2026 | Squelette + catalogue + modèles + migrations draft + 16 tests |
| **0.1.0** Phase 1 | À démarrer | 11-17 mai 2026 | Wiring webapp + routes `/culture/varietes` `/culture/parcelles` + UI |
| **0.2.0** Phase 2 | À démarrer | 18-24 mai 2026 | Plan de culture annuel + intégration `self_dnja` + `self_agri_book` |
| **0.3.0** Phase 3 | À démarrer | 25-31 mai 2026 | Assolement pluriannuel + export PDF CDOA |
| **0.4.0** Phase 4 | À démarrer | 1-7 juin 2026 | Planning hebdo + export ICS |
| **0.5.0** Phase 5 | À démarrer | 8-14 juin 2026 | Polish + dogfooding + tests E2E + bump SelfFarm v0.3.0 |

## Référentiels externes (post-V0.3)

- **Lexicon Ekylibre** (AGPL) : référentiel variétés/produits agricoles. Synergie avec David Joulin, SelfFarm pourrait être le premier consommateur Lexicon hors Ekylibre.
- **GEVES** : catalogue officiel français des variétés autorisées.
- **ITAB** : référence agronomique AB.
- Mode offline-first : cache local synchronisé périodiquement.

## Différenciation revendiquée vs *Ouvretaferme*

Là où *Ouvretaferme* gère le plan de culture comme une fonction isolée d'un
SaaS centralisé, **`self_culture` l'intègre nativement** au hub compta agricole
et au prévisionnel DNJA :

- Un achat de semence devient une écriture 601 sans double saisie
- Un rendement prévisionnel alimente automatiquement le RDA SMIC du dossier JA
- Chaque tâche du planning peut être tracée comme charge de main-d'œuvre
- Le tout en **local-first**, **AGPL-3.0-or-later**, **sans cloud**

## Licence

AGPL-3.0-or-later (cohérent avec l'écosystème MySelf)
