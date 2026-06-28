#!/usr/bin/env bash
#
# serve-lan.sh — Lance SelfFarm-Lite uvicorn accessible depuis le LAN
# Usage : ./serve-lan.sh
#
# Variables d'env définies :
# - SELFFARM_ENV=perso              → bandeau "ENV PERSO" + isolement données
# - SELFFARM_DATA_DIR=.selffarm-perso → BDD compta + parcelles + POS
# - SELFFARM_AIDES_CACHE=.selffarm-perso/aides → cache catalogue aides
#
# uvicorn écoute sur 0.0.0.0:8003 pour être joignable depuis mobile/tablette LAN.

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

PORT="${SELFFARM_PORT:-8003}"

# ─── Vérifications préalables ───────────────────────────────────────────────
if [ ! -d ".venv" ]; then
  echo "✗ Virtualenv .venv/ introuvable dans $PROJECT_DIR"
  echo "  Crée-le avec : python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

if [ ! -f ".venv/bin/uvicorn" ]; then
  echo "✗ uvicorn pas installé dans .venv"
  exit 1
fi

# IP LAN auto-détectée (première IP non-loopback, non-libvirt, non-docker)
LAN_IP=$(ip -4 addr show 2>/dev/null \
  | awk '/inet 192\.168\./{print $2}' \
  | grep -v "^192.168.122\." \
  | head -1 \
  | cut -d/ -f1)

if [ -z "$LAN_IP" ]; then
  LAN_IP=$(hostname -I | awk '{print $1}')
fi

# ─── Avertissement UFW ──────────────────────────────────────────────────────
if ! command -v ufw >/dev/null 2>&1; then
  echo "⚠  UFW non installé — recommandé pour sécuriser l'expo LAN :"
  echo "   sudo apt install ufw && sudo ufw allow from 192.168.1.0/24 to any port $PORT proto tcp && sudo ufw enable"
  echo ""
elif ! sudo -n ufw status 2>/dev/null | grep -q "Status: active"; then
  echo "⚠  UFW pas actif — règle conseillée :"
  echo "   sudo ufw allow from 192.168.1.0/24 to any port $PORT proto tcp && sudo ufw enable"
  echo ""
fi

# ─── Vérification BDD existante ─────────────────────────────────────────────
DATA_DIR="${HOME}/.selffarm-perso"
if [ ! -f "$DATA_DIR/compta.db" ]; then
  echo "⚠  BDD perso introuvable : $DATA_DIR/compta.db"
  echo "   uvicorn va la créer vide au démarrage. Si tu as déjà des données,"
  echo "   vérifie SELFFARM_DATA_DIR dans ce script."
  echo ""
fi

# ─── Affichage URLs ─────────────────────────────────────────────────────────
echo "═══════════════════════════════════════════════════════════════"
echo "  SelfFarm-Lite — Serveur LAN"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "  📍 PC local       : http://127.0.0.1:$PORT"
echo "  📱 Mobile LAN     : http://$LAN_IP:$PORT"
echo "  📱 PWA SelfPOS    : http://$LAN_IP:$PORT/pos/mobile"
echo "  💾 BDD            : $DATA_DIR/compta.db"
echo ""
echo "  Ctrl+C pour arrêter."
echo "═══════════════════════════════════════════════════════════════"
echo ""

# ─── Lancement ──────────────────────────────────────────────────────────────
exec env \
  SELFFARM_ENV=perso \
  SELFFARM_DATA_DIR="$DATA_DIR" \
  SELFFARM_AIDES_CACHE="$DATA_DIR/aides" \
  SELFFARM_HOST=0.0.0.0 \
  .venv/bin/uvicorn webapp.main:app \
    --host 0.0.0.0 \
    --port "$PORT" \
    --reload
