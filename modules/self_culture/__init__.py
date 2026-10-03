"""
self_culture — plan de culture, assolement pluriannuel, planning hebdomadaire.

Module agricole pour piloter une exploitation maraîchère ou polyculture :
- catalogue de variétés (référentiel YAML curated + ajouts utilisateur)
- parcelles cadastrales et planches maraîchères
- plan de culture annuel (assignation variété × planche × campagne)
- assolement pluriannuel avec validation de rotation (familles botaniques)
- planning hebdomadaire des tâches (semis, repiquage, désherbage, récolte)
- intégration native au hub compta self_agri_book et au prévisionnel self_dnja

Conventions :
- Tables SQLite préfixées par migration (4..9) dans storage.py
- Tâches générées avec source_module='self_culture' pour traçabilité PAF
- Dates en ISO 8601, semaines au format ISO `AAAA-Wnn`
"""

from __future__ import annotations

# Inscrit les migrations du module au registre du noyau, dont la restauration
# a besoin pour mettre une sauvegarde à niveau.
from self_culture import cultures as _cultures  # noqa: F401
