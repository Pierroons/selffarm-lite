"""self_elevage — verticale élevage (ateliers avicoles, pondeuses en premier).

Suivi de bande, ponte quotidienne, mouvements (mortalité / réforme / ajout) et
lots d'œufs destinés à la vente directe.

Le module produit le **stock** ; la vente est assurée par SelfPOS (marché,
dépôt en point de vente collectif) et la remontée comptable par self_agri_book.
Rien de cette chaîne aval n'est réimplémenté ici.
"""

__version__ = "0.1.0"
