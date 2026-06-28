# SelfFarm-Lite webapp

**Interface web** FastAPI + htmx + Tailwind qui enveloppe les modules CLI de
SelfFarm-Lite. Dark mode, léger, AGPL, self-hosted.

## Lancement

```bash
cd selffarm-lite
PYTHONPATH=modules:. .venv/bin/uvicorn webapp.main:app --reload --port 8001
```

Ouvre http://localhost:8001 dans ton navigateur.

## Écrans disponibles

| URL | Description |
|---|---|
| `/` | Dashboard avec 4 tuiles d'accès |
| `/dnja` | Simulateur DNJA — liste scénarios + calcul inline HTMX |
| `/dnja/compare` | Comparaison 2 scénarios côte-à-côte avec deltas colorés |
| `/dnja/editor` | Éditeur YAML — modifier un scénario, recalculer, sauvegarder |
| `/dnja/pdf?example=X` | Télécharger PDF d'un scénario |
| `/aides` | Catalogue aides agricoles 2026 filtrable (htmx) |
| `/aides/{id}` | Fiche détaillée d'une aide avec conditions + cumul + source |
| `/parcelles` | Cartographie IGN (orthophoto + cadastre) |
| `/docs` | Swagger UI (API REST introspection) |

## Features HTMX

- **Calcul DNJA inline** : clique sur un scénario → résultat injecté dans #result (pas de reload)
- **Filtrage aides en direct** : tape/sélectionne un filtre → liste mise à jour
- **Comparaison scénarios** : change un select → tableau recalculé
- **Éditeur hypothèses** : modifie un champ → clique Calculer → résultat inline

## Thème

Dark natif (cohérent préférences utilisateur customtkinter dark). Tailwind CSS via CDN. Couleurs :
- Fond : `#0f172a` (slate-950)
- Cartes : `#1e293b` (slate-800)
- Accent : `#16a34a` (green-600)

## Stack

- **FastAPI** 0.136
- **Starlette** < 1.0 (épinglé — breakpoint Jinja2Templates sur 1.0.0)
- **Jinja2** 3.1
- **htmx** 1.9.12 (CDN)
- **Tailwind CSS** (CDN)
- **Pydantic v2** (modèles cohérents avec self_dnja + self_aid)

## Structure

```
webapp/
├── __init__.py (VERSION)
├── main.py (FastAPI + routers)
├── routes/
│   ├── home.py
│   ├── dnja.py (index, calcul, pdf, compare, editor)
│   ├── aides.py (list, filter, detail)
│   └── parcelles.py (iframe carto)
├── templates/
│   ├── base.html (header + nav + footer commun)
│   ├── home.html
│   ├── dnja/ (index, result, compare, compare_result, editor, editor_form)
│   ├── aides/ (list, _fragment, detail)
│   └── parcelles/index.html
├── static/ (vide, prévu pour assets v0.3)
├── tests/
└── README.md
```

## Licence

AGPL-3.0-or-later.
