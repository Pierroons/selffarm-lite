#!/usr/bin/env bash
# SelfFarm-Lite — simulation install grand public
# Reproduit fidèlement ce que voit un paysan lambda après `docker compose up -d`
#
# Différences vs run-perso.sh :
#   - SELFFARM_ENV=prod (pas de bandeau ENV PERSO)
#   - DB vierge à chaque lancement (~/.selffarm-demo-client/)
#   - port 8003 (même que perso)

set -euo pipefail

cd "$(dirname "$0")/.."

DEMO_DIR="$HOME/.selffarm-demo-client"
rm -rf "$DEMO_DIR"
mkdir -p "$DEMO_DIR/aides"

export SELFFARM_ENV=prod
export SELFFARM_HOST=127.0.0.1
export SELFFARM_PORT=8003
export SELFFARM_COMPTA_DB="$DEMO_DIR/compta.db"
export SELFFARM_AIDES_CACHE="$DEMO_DIR/aides"
export SELFFARM_LOG_LEVEL=INFO
export PYTHONPATH="$PWD/modules:$PWD"

echo "=================================================="
echo " SelfFarm-Lite — DEMO INSTALL CLIENT LAMBDA"
echo "=================================================="
echo " Vue paysan lambda post-install (env=prod, DB vide)"
echo " URL    : http://127.0.0.1:8003"
echo " DB     : $SELFFARM_COMPTA_DB (vierge)"
echo " Bandeau: AUCUN (prod propre)"
echo " Stop   : Ctrl+C"
echo "=================================================="
echo ""

exec .venv/bin/uvicorn webapp.main:app \
    --host "$SELFFARM_HOST" \
    --port "$SELFFARM_PORT" \
    --reload
