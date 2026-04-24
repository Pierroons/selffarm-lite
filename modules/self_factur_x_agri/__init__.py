"""
self-factur-x-agri — extension agricole pour la génération Factur-X.

Objet :
- Spécialiser le builder Factur-X de SelfInvoice aux spécificités agricoles :
  TVA particulières (5.5 % produits bruts, 10 % transformés, exo élevage),
  UOM agricoles (HAR hectare, TNE tonne, NAR nombre d'animaux, LTR, MTK, BX),
  codes produits FranceAgriMer, régime micro-BA vs réel agricole.

- Mapper le PCG agricole (classes 70xx ventes agri, 60xx intrants agri) vers
  les codes Factur-X (UNTDID 5305 catégories taxe, UNTDID 7161 allocations,
  UNECE UOM).

Statut : squelette v0.1.0-dev. Implémentation prévue après SelfInvoice v0.2
(le builder abstrait de SelfInvoice fournira la classe parente).
"""

__version__ = "0.1.0-dev"
