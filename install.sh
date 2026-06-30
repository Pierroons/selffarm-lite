#!/bin/bash
# SelfFarm-Lite — script d'installation automatique (Debian/Ubuntu)
# Usage : ./install.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "════════════════════════════════════════════════"
echo "  SelfFarm-Lite — installation"
echo "  Version : $(cat VERSION)"
echo "════════════════════════════════════════════════"
echo

# 1. Vérifier les deps système (WeasyPrint)
echo "▶ Vérification des dépendances système…"
MISSING_DEPS=()
for pkg in libpango-1.0-0 libpangoft2-1.0-0 python3-venv python3-pip; do
    if ! dpkg -s "$pkg" >/dev/null 2>&1; then
        MISSING_DEPS+=("$pkg")
    fi
done

if (( ${#MISSING_DEPS[@]} > 0 )); then
    echo "  ✗ Paquets manquants : ${MISSING_DEPS[*]}"
    echo
    echo "  Installe-les avec :"
    echo "    sudo apt install -y ${MISSING_DEPS[*]}"
    exit 1
fi
echo "  ✓ Tous les paquets système sont présents"

# 2. Créer le venv si nécessaire
if [[ ! -d .venv ]]; then
    echo "▶ Création du venv Python…"
    python3 -m venv .venv
    echo "  ✓ .venv/ créé"
else
    echo "▶ venv existant détecté"
fi

# 3. Install deps Python
echo "▶ Installation des dépendances Python…"
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -e ".[dev]"
echo "  ✓ Dépendances installées"

# 4. Tests
echo "▶ Exécution des tests…"
if PYTHONPATH=modules .venv/bin/python -m pytest modules/ -q 2>&1 | tail -5; then
    echo "  ✓ Tous les tests passent"
else
    echo "  ✗ Certains tests échouent — voir la sortie ci-dessus"
    exit 1
fi

# 4b. Smoke-test webapp (détecte une dépendance webapp manquante)
echo "▶ Vérification de l'import de la webapp…"
if PYTHONPATH=modules .venv/bin/python -c "from webapp.main import app" 2>/dev/null; then
    echo "  ✓ webapp importable"
else
    echo "  ✗ La webapp ne s'importe pas — dépendance manquante ?"
    exit 1
fi

# 5. Vérification des CLI
echo "▶ Vérification des CLI…"
PYTHONPATH=modules .venv/bin/python -m self_dnja.cli --version
PYTHONPATH=modules .venv/bin/python -m self_aid.cli --version

# 6. Résumé
echo
echo "════════════════════════════════════════════════"
echo "  ✓ Installation réussie"
echo
echo "  Pour utiliser les commandes (depuis ce dossier) :"
echo "    PYTHONPATH=modules .venv/bin/python -m self_dnja.cli --help"
echo "    PYTHONPATH=modules .venv/bin/python -m self_aid.cli --help"
echo
echo "  Pour lancer l'interface web (dashboard, SelfPOS, compta) :"
echo "    PYTHONPATH=modules .venv/bin/uvicorn webapp.main:app --port 8001"
echo "    → http://localhost:8001"
echo
echo "  Ou active le venv :"
echo "    source .venv/bin/activate"
echo "    export PYTHONPATH=modules"
echo "    self-dnja --help"
echo "    self-aid --help"
echo "════════════════════════════════════════════════"
