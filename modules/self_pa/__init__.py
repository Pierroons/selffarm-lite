"""
self-pa — réception des factures fournisseurs via une Plateforme Agréée.

Depuis le 1er septembre 2026, toute entreprise assujettie à la TVA doit être en
mesure de recevoir ses factures sous forme électronique (CGI art. 289 bis), par
l'intermédiaire d'une plateforme agréée. Les fournisseurs grandes entreprises et
ETI y sont tenus dès cette date, les autres au 1er septembre 2027.

Conséquence pratique : les factures fournisseurs arrivent **structurées**. Leurs
montants sont dans des balises, pas dans une image — il n'y a rien à parser, rien
à deviner, et aucun document à envoyer à un service tiers pour le faire lire.

Le module couvre le sens ENTRANT. L'émission vit dans SelfInvoice.

Chaîne : plateforme → `cii_reader` → `FactureRecue` → imputation proposée →
validation humaine → `self_agri_book.save_ecriture()`. Le dernier maillon n'est
jamais franchi tout seul : une écriture comptable naît d'une décision, pas d'un
automatisme.
"""

__version__ = "0.1.0-dev"
