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

__version__ = "0.1.0-prep"
