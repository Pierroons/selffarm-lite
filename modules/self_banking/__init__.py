"""
self_banking — import et parsing de relevés bancaires pour SelfFarm-Lite.

Principe MySelf : 100 % local, aucun agrément DSP2 requis, zéro capture.
L'utilisateur exporte son relevé depuis l'app bancaire, dépose le fichier
dans SelfFarm-Lite, et le module extrait les transactions normalisées
prêtes à être rapprochées de la compta (self_agri_book) et des factures
(self_invoice).

Parsers supportés :
- SG (Société Générale) particuliers — format PDF
- (à venir : Crédit Agricole, Boursorama, Crédit Mutuel, Caisse d'Épargne)
"""

from __future__ import annotations

__version__ = "0.1.0-dev"

from self_banking.models import Releve, Transaction, TypeMouvement

__all__ = ["Releve", "Transaction", "TypeMouvement", "__version__"]
