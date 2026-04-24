"""
self-agri-book — comptabilité agricole réelle simplifiée.

Objet :
- Saisie d'écritures comptables agricoles (journaux achat/vente/banque)
- Plan comptable agricole officiel pré-chargé (sourcé ANC + arrêté 1986 PCGA)
- Export FEC (Fichier des Écritures Comptables) conforme bofip.impots.gouv.fr
- Balance, grand livre, compte de résultat, bilan (version light)
- Connecteur vers self-dnja (réel historique → base hypothèses prévisionnelles)

Statut : squelette v0.1.0-dev. Le YAML du plan comptable est déjà présent
dans `data/pcg-agricole-2026.yaml` (9 classes, 396 sous-comptes, 133 agri-
spécifiques). Implémentation du moteur d'écritures prévue après SelfInvoice
v0.2 (pour que les factures puissent générer leurs écritures automatiquement).
"""

__version__ = "0.1.0-dev"
