"""SelfFarm-Lite — webapp FastAPI + htmx + Tailwind dark."""

from pathlib import Path

# Le fichier VERSION est la source unique : pyproject.toml le lit déjà
# (`version = { file = "VERSION" }`) et il est embarqué à la racine de l'image
# Docker. La version était auparavant recopiée ici en dur, et les deux avaient
# fini par diverger — 0.1.0-dev affiché en pied de page alors que le tag et la
# release publiée annonçaient 0.1.1.
_VERSION_FILE = Path(__file__).parent.parent / "VERSION"

try:
    __version__ = _VERSION_FILE.read_text(encoding="utf-8").strip()
except OSError:  # arborescence inattendue : mieux vaut « inconnue » qu'une fausse version
    __version__ = "0.0.0+unknown"
