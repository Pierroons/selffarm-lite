# Roadmap `self-parcelles` — module cartographique SelfFarm-Lite

Date : 22 avril 2026
Statut : concept validé, prototype démo OK (`demo-carto.html`)

Ce document consigne les besoins fonctionnels et les décisions de
conception pour le futur module de cartographie parcellaire.

## Périmètre v0.3 (post-SelfInvoice)

Module Python `self_parcelles/` qui fournit :

- Recherche par n° cadastre (INSEE + section + numéro)
- Recherche par clic sur carte (point GPS → parcelle)
- Stockage parcelles dans SQLite+SpatiaLite (ou PostgreSQL+PostGIS)
- Association parcelle ↔ culture ↔ campagne (intégration self-agri-book)
- Alimentation auto de `self-dnja` (surfaces par activité)
- API FastAPI + UI Leaflet intégrée à l'app web SelfFarm-Lite

## Besoin terrain CRITIQUE — multi-commune

**Feedback Pierroons 22/04/2026** : « Certains paysans ont des parcelles
sur plusieurs communes. »

→ Le module `self-parcelles` DOIT gérer dès v0.3 :

- Ajout successif de parcelles sur **plusieurs communes différentes**
  (département, région, voire pays pour bassins transfrontaliers)
- **Autocomplete sur le nom de commune** (utilise l'API
  api-adresse.data.gouv.fr qui est gratuite et ne nécessite pas d'auth)
- **Carte capable de dézoomer** pour voir toutes les parcelles de
  l'utilisateur, même à 100 km de distance
- **Filtres** : "afficher uniquement les parcelles de la commune X"
- **Stats par commune** (surface totale par commune, par culture)
- **Export multi-commune** vers TéléPAC ou FEC (écritures par commune
  pour la comptabilité analytique)

Architecture recommandée :

```python
class Parcelle(BaseModel):
    id_cadastre: str          # IDU complet (14 caractères, ex: 33220000A0001)
    code_insee: str           # 5 digits, permet filtre/groupement
    commune_nom: str          # humain, pour UI
    section: str
    numero: str
    geometry: GeoJSONPolygon
    surface_m2: int
    cultures_par_campagne: dict[int, str]  # {2026: "chanvre_cbd_bio", 2027: ...}
```

Table SQL :
```sql
CREATE TABLE parcelles (
    id_cadastre TEXT PRIMARY KEY,     -- ex: 33220000A0001
    code_insee TEXT NOT NULL,          -- indexed, pour filtre/groupement
    commune_nom TEXT NOT NULL,
    section TEXT NOT NULL,
    numero TEXT NOT NULL,
    geometry GEOMETRY(Polygon, 4326) NOT NULL,
    surface_m2 INTEGER NOT NULL,
    user_id INTEGER REFERENCES users(id)
);
CREATE INDEX idx_parcelles_commune ON parcelles(code_insee);
CREATE INDEX idx_parcelles_geom ON parcelles USING GIST(geometry);
```

## Prototype actuel — état

`docs/demo-carto.html` (standalone, zéro backend) :

- ✅ Fond orthophoto IGN / Plan IGN / Sat + Cadastre
- ✅ Mode ✋ Déplacer / 🎯 Sélectionner par clic
- ✅ Recherche par INSEE + section + numéro
- ✅ Popup parcelle : IDU, commune, surface, bouton "Ajouter au PE"
- ✅ Barre de statut en bas
- ❌ **Multi-commune pas encore géré** — le champ INSEE ne propose pas
  d'autocomplete. À ajouter dans la v0.3 du vrai module.

## APIs utilisées (toutes gratuites, open data gouv)

| API | URL | Usage |
|---|---|---|
| IGN Api Carto cadastre | `apicarto.ign.fr/api/cadastre/parcelle` | Polygone par section/numéro ou par point |
| IGN Api Carto commune | `apicarto.ign.fr/api/cadastre/commune` | Polygone commune + surface |
| IGN Géoplateforme WMTS | `data.geopf.fr/wmts` | Tuiles orthophoto, plan, cadastre |
| api-adresse.data.gouv.fr | `api-adresse.data.gouv.fr/search/` | **Autocomplete commune par nom** |
| cadastre.data.gouv.fr | `cadastre.data.gouv.fr/` | Export GeoJSON brut communal |

## Autres besoins à creuser plus tard

- [ ] **Tiers-détention** : certains paysans louent des parcelles ; cohabiter
      propriétaire / fermier sur une même parcelle (dates de bail)
- [ ] **Historique cultures** : rotation sur N années pour prime à la
      diversification
- [ ] **Export TéléPAC GeoJSON** : flux direct vers la déclaration PAC
      annuelle (15 mai)
- [ ] **Dessin libre** : si une parcelle n'a pas de référence cadastre
      claire (ex: morceaux de prairie commune), permettre de tracer
      à la main un polygone
- [ ] **Import KML/GPX** depuis terrain (drone, tracker GPS)
- [ ] **Mode offline** : cache des tuiles pour usage sans réseau au champ

## Frontend — leaflet vs MapLibre GL

Actuellement : Leaflet (simple, éprouvé, AGPL-compatible).

À évaluer à la v0.4 : **MapLibre GL JS** (fork libre de Mapbox GL JS) →
rendu WebGL plus rapide, vecteur natif, styles custom. Mais complexifie
le stack (doit servir des tuiles vectorielles).

## Licence

AGPL-3.0-or-later. Toutes les données sont sous **Licence Ouverte 2.0
Etalab** (compatible AGPL).
