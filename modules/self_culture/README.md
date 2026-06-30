# self_culture — catalogue de variétés + parcelles & plan de culture

Verticale **agricole** de SelfFarm-Lite. Elle porte le vocabulaire métier
« culture » (variétés, parcelles, plan de culture) — hors du noyau compta, qui
reste agnostique du métier (cf. règle « core + verticales »).

> **Statut** : `0.1.0` — branché en prod. Route `/parcelles` (parcellaire +
> plan de culture) et tableau de bord alimentés par ce module.

## Périmètre

- **Catalogue de variétés de référence** (donnée statique, typée) : 36 variétés
  AB (25 légumes, 3 aromatiques, 1 industriel = chanvre Kompolti, 7 engrais
  verts) réparties sur 13 familles botaniques.
- **Parcelles** + **plan de culture saisonnier** : CRUD branché sur la base du
  hub `self_agri_book` (une seule DB SQLite partagée), consommé par la webapp.
- **Stats parcellaire** pour le tableau de bord (surfaces par culture, par statut).

## Architecture du module

```
modules/self_culture/
├── __init__.py    # __version__, docstring
├── models.py      # vocabulaire typé : enums (FamilleBotanique, CategorieVariete,
│                  #   Saison, ModeProduction) + Variete / CalendrierCulture / RendementReference
├── catalog.py     # loader YAML unique (Pydantic) + filtres (famille, catégorie, saison, mot-clé)
├── cultures.py    # IMPLÉMENTATION PROD : CRUD parcelle/plan_culture + datalist variétés
├── data/
│   └── varietes-references.yaml   # catalogue curated (source de vérité)
├── tests/
│   └── test_catalog.py            # 17 tests (catalogue, filtres, datalist)
└── README.md
```

**Qui fait quoi :**
- `cultures.py` est le **point d'entrée de prod** (importé par
  `webapp/routes/parcelles.py` et `webapp/services/dashboard_stats.py`). Il fait
  le CRUD `parcelle` / `plan_culture` et expose le catalogue au formulaire via
  `get_varietes_for_datalist()`.
- `catalog.py` + `models.py` sont la **couche catalogue typée** : un seul loader
  (`load_catalog()` → objets Pydantic `Variete` validés), réutilisé par `cultures.py`.

## Catalogue de variétés

**Source de vérité** : `data/varietes-references.yaml`, chargé et validé en
objets `Variete` par `catalog.load_catalog()`. Couverture : 13 familles
botaniques, dont le chanvre Kompolti AB, variété de référence, et 7
engrais verts (rendement 0, non récoltés) pour la rotation.

**Sourcing agronomique** : ITAB, GEVES, retour terrain maraîcher + sélectionneur.

## Schéma

Les tables `parcelle` et `plan_culture` portent le schéma agricole de la
verticale (champs : commune, surface, statut bio/conversion, culture, variété,
dates semis/récolte prévues et réelles, rendement attendu, mode de production).
Elles vivent dans la base partagée du hub mais relèvent fonctionnellement de
cette verticale. `ecritures_comptables` (le hub) reste agnostique.

## Tests

```bash
PYTHONPATH=modules pytest modules/self_culture/tests/ -v
```

17 tests : chargement + validation Pydantic du catalogue, unicité des slugs,
présence des variétés clés, filtres (famille / catégorie / saison / mot-clé),
cohérence calendrier/rendements, diversité botanique, et format du datalist.

## Intégration écosystème

- **`self_agri_book`** (hub compta) : un achat de semence peut devenir une
  écriture comptable liée, sans double saisie.
- **`self_dnja`** (prévisionnel JA) : les rendements alimentent le prévisionnel.

Local-first, AGPL-3.0-or-later, sans cloud.

## Licence

AGPL-3.0-or-later (cohérent avec l'écosystème MySelf).
