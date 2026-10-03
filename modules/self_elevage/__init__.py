"""self_elevage — verticale élevage (ateliers avicoles, pondeuses en premier).

Suivi de bande, ponte quotidienne, mouvements (mortalité / réforme / ajout) et
lots d'œufs destinés à la vente directe.

Le module produit le **stock** ; la vente est assurée par SelfPOS (marché,
dépôt en point de vente collectif) et la remontée comptable par self_agri_book.
Rien de cette chaîne aval n'est réimplémenté ici.
"""

# Inscrit les migrations du module au registre du noyau, dont la restauration
# a besoin pour mettre une sauvegarde à niveau.
from self_elevage import elevage as _elevage  # noqa: F401
