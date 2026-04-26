#!/usr/bin/env bash
# SelfFarm-Lite — démo publique (selffarm.my-self.fr style)
#
# SELFFARM_ENV=demo → boutons démo activés, génération facture aléatoire OK.
# Idéal pour tester l'expérience d'un visiteur de la démo publique.
#
# Port : 8004 (différent de 8003 perso/prod)

set -euo pipefail

cd "$(dirname "$0")/.."

DEMO_DIR="$HOME/.selffarm-demo-publique"
mkdir -p "$DEMO_DIR/aides"

export SELFFARM_ENV=demo
export SELFFARM_HOST=127.0.0.1
export SELFFARM_PORT=8004
export SELFFARM_COMPTA_DB="$DEMO_DIR/compta.db"
export SELFFARM_AIDES_CACHE="$DEMO_DIR/aides"
export SELFFARM_LOG_LEVEL=INFO
export PYTHONPATH="$PWD/modules:$PWD"

echo "==========================================="
echo " SelfFarm-Lite — DÉMO PUBLIQUE (env=demo)"
echo "==========================================="
echo " URL    : http://127.0.0.1:8004"
echo " DB     : $SELFFARM_COMPTA_DB"
echo " Boutons démo : ACTIFS"
echo "==========================================="
echo ""

exec .venv/bin/uvicorn webapp.main:app \
    --host "$SELFFARM_HOST" \
    --port "$SELFFARM_PORT" \
    --reload
