"""Fixtures des tests de routes.

Deux précautions y sont prises, et l'ordre compte :

1. **La base est isolée AVANT tout import applicatif.** `self_agri_book.storage`
   lit `SELFFARM_DATA_DIR` au moment de son import, pas à chaque appel : poser
   la variable après coup n'aurait aucun effet et les tests écriraient dans la
   base réelle de l'utilisateur.

2. **L'onboarding est marqué fait.** Un middleware redirige toute requête vers
   `/onboarding/1` tant que le profil d'exploitation n'existe pas. Sans ça,
   chaque test reçoit la page du wizard avec un 200 trompeur — c'est ce qui a
   laissé 17 tests sur 18 échouer en silence, invisibles parce que
   `testpaths = ["modules"]` ne les exécutait jamais.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

BASE = Path(__file__).parent.parent.parent
sys.path.insert(0, str(BASE / "modules"))
sys.path.insert(0, str(BASE))

# ⚠️ Avant tout import de webapp/self_agri_book — voir docstring.
_TEST_DATA_DIR = tempfile.mkdtemp(prefix="selffarm-webapp-tests-")
os.environ["SELFFARM_DATA_DIR"] = _TEST_DATA_DIR

from fastapi.testclient import TestClient
from self_agri_book.exploitation import (
    is_onboarding_done,
    mark_onboarding_done,
    save_exploitation,
)

from webapp.main import app


@pytest.fixture(scope="session", autouse=True)
def _exploitation_prete():
    """Profil d'exploitation minimal, sans lequel tout redirige vers le wizard."""
    if not is_onboarding_done():
        save_exploitation({
            "nom": "Ferme de test",
            "statut": "JA",
            "commune": "Sainte-Foy",
            "saison_courante": 2026,
        })
        mark_onboarding_done()


@pytest.fixture
def client():
    return TestClient(app)


# Seul scénario d'exemple versionné : les scénarios nominatifs sont exclus du
# dépôt (.gitignore) et filtrés par _PRIVATE_SCENARIO_PATTERNS hors machine
# perso. Les tests doivent donc s'appuyer sur celui-ci, sans quoi ils ne passent
# que sur le poste de leur auteur.
SCENARIO_DEMO = "hypotheses-demo-publique"
