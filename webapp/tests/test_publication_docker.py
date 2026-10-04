"""SelfFarm n'a pas de mot de passe : sous Docker, il ne doit répondre qu'au PC
qui le fait tourner. Un mappage de port sans adresse (`8001:8001`) le publie sur
toutes les interfaces de l'hôte, et sous Linux Docker passe devant le pare-feu.
Le compose est lu en YAML ; le Dockerfile, la documentation et les workflows,
qui montrent des commandes à copier, sont lus comme du texte. Seule la section
d'INSTALL-DOCKER.md qui explique comment ouvrir au réseau peut écrire `0.0.0.0`."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

RACINE = Path(__file__).resolve().parents[2]
COMPOSE = RACINE / "docker-compose.yml"
OUVERTURE_DOCUMENTEE = RACINE / "INSTALL-DOCKER.md"
FICHIERS = sorted({
    RACINE / "Dockerfile",
    COMPOSE,
    *RACINE.glob("*.md"),
    *(RACINE / "docs").rglob("*.md"),
    *(RACINE / ".github" / "workflows").glob("*.yml"),
})

# `-p 8001:8001`, `--publish 127.0.0.1:8001:8001`, ou un élément de liste YAML
# qui n'est qu'un mappage : `- "8001:8001"` (pas `- 10:30 marché`).
MAPPAGE = re.compile(
    r"(?<![\w-])(?:-p|--publish)[ =]+[\"']?(?P<cmd>[\d.]+:\d+(?::\d+)?)"
    r"|^\s*-\s*[\"']?(?P<yaml>[\d.]+:\d+(?::\d+)?)[\"']?\s*(?:#.*)?$",
    re.MULTILINE,
)


def _hote(mappage: str) -> str | None:
    parties = mappage.split(":")
    return parties[0] if len(parties) == 3 else None


def _publications() -> list[tuple[Path, str]]:
    return [(f, m.group("cmd") or m.group("yaml")) for f in FICHIERS if f.is_file()
            for m in MAPPAGE.finditer(f.read_text(encoding="utf-8"))]


def test_le_balayage_trouve_les_publications():
    vus = {f.name for f, _ in _publications()}
    assert {"docker-compose.yml", "Dockerfile", "docker-build.yml", "INSTALL-DOCKER.md"} <= vus


def test_le_compose_ne_publie_que_sur_ce_pc():
    services = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]
    ports = [(nom, p) for nom, s in services.items() for p in s.get("ports", [])]
    assert ports, "le compose ne publie plus aucun port : ce test ne contrôle plus rien"
    for nom, p in ports:
        hote = p.get("host_ip") if isinstance(p, dict) else _hote(str(p))
        assert hote == "127.0.0.1", f"{nom} : {p!r} publie hors de ce PC"


@pytest.mark.parametrize("fichier, mappage", _publications(),
                         ids=lambda v: v.name if isinstance(v, Path) else v)
def test_aucune_commande_ne_publie_sur_tout_le_reseau(fichier, mappage):
    hote = _hote(mappage)
    if hote == "0.0.0.0" and fichier == OUVERTURE_DOCUMENTEE:
        return
    assert hote == "127.0.0.1", f"{fichier.relative_to(RACINE)} : `{mappage}` publie hors de ce PC"
