# self-factur-x-agri

**Extension agricole du builder Factur-X de SelfInvoice.** Spécialise le
générateur Factur-X pour gérer les particularités de la facturation
agricole française :

- **TVA particulières** : 5,5 % (produits bruts), 10 % (transformés), 20 %
  (standard services), régime 298 bis CGI (micro-BA non assujetti)
- **UOM agricoles** : hectare (HAR), tonne (TNE), litre (LTR), nombre
  d'animaux (NAR), mètre carré (MTK), boîte (BX), tête (HEA) — absents du
  mapping Odoo
- **Codes produits FranceAgriMer** : chanvre_fibre, maraichage_bio, etc.
- **Mentions obligatoires** : n° SIRET + MSA + mention "TVA non applicable
  art. 293 B CGI" (franchise) ou "régime forfaitaire agricole art. 298 bis CGI"

## Statut

**Squelette v0.1.0-dev.** Implémentation prévue après SelfInvoice v0.2
(le builder abstrait de SelfInvoice fournira la classe parente).

## Ce qui est déjà défini

- `models.py` — énumérations UOM agricoles, catégories TVA UNTDID 5305,
  barème TVA agricole FR 2026, modèle `ProduitAgriFactor`

## Architecture prévue

```python
# Dans SelfInvoice :
from selfinvoice.builders.base import AbstractFormatBuilder
from selfinvoice.builders.facturx_basic import FacturXBasicBuilder

# Dans self-factur-x-agri :
class FacturXAgriBuilder(FacturXBasicBuilder):
    """Surcharge pour spécificités agricoles FR."""

    def map_uom(self, line_uom: str) -> str:
        # HAR/TNE/NAR/... au lieu des UOM commerciales génériques
        return UomAgri(line_uom).value

    def map_tax_code(self, line_tax: Tax) -> str:
        # 5.5/10/20 tous "S", 298 bis → "E"
        if line_tax.art_cgi == "298 bis CGI":
            return "E"
        return "S"

    def extra_document_notes(self, invoice: Invoice) -> list[str]:
        # Mentions obligatoires MSA, régime, bio, etc.
        ...
```

## Roadmap

1. Une fois SelfInvoice v0.2 publié → implémenter `FacturXAgriBuilder`
2. Ajouter un YAML `data/produits-agri-types.yaml` avec codes CPV et
   familles FranceAgriMer pour auto-complétion UI
3. Tests avec des factures types (vente chanvre CBD retail, vente AMAP
   maraîchage, vente producteur-producteur exo TVA)
4. Validation croisée avec Chorus Pro (portail de test public FR)

## Licence

AGPL-3.0-or-later.
