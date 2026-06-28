#!/usr/bin/env bash
#
# install-ufw.sh — Hardening firewall UFW pour Pierroons
# Cible : Debian 13 Trixie x64, usage perso + dev + gaming cloud (GFN)
#
# Politique :
#   - INCOMING : deny par défaut (tout fermé sauf règles explicites)
#   - OUTGOING : allow (GFN, Discord, jeux web, etc. fonctionnent natifs)
#   - LOOPBACK : allow auto
#   - LAN seul autorisé sur SelfFarm port 8003
#
# GeForce Now (GFN) :
#   GFN est un client STREAMING (NVIDIA serveurs distants). Toutes les
#   connexions sont INITIÉES par ton PC → trafic SORTANT.
#   `default allow outgoing` couvre 100% du trafic GFN, aucune règle
#   inbound spéciale nécessaire. Idem Discord, Steam (achat), Twitch, etc.
#
# Idempotent : relançable sans casser.

set -e

# ─── Préchecks ──────────────────────────────────────────────────────────────
if [ "$EUID" -ne 0 ]; then
  echo "✗ Ce script doit être lancé avec sudo :"
  echo "  sudo $0"
  exit 1
fi

LAN_SUBNET="${LAN_SUBNET:-192.168.1.0/24}"
SELFFARM_PORT="${SELFFARM_PORT:-8003}"

echo "═══════════════════════════════════════════════════════════════"
echo "  Hardening UFW — Pierroons"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "  LAN subnet       : $LAN_SUBNET"
echo "  SelfFarm port    : $SELFFARM_PORT"
echo ""

# ─── 1. Installation UFW ────────────────────────────────────────────────────
if ! command -v ufw >/dev/null 2>&1; then
  echo "📦 Installation UFW…"
  apt update -qq
  apt install -y ufw
else
  echo "✓ UFW déjà installé ($(ufw --version | head -1))"
fi

# ─── 2. Activation IPv6 dans UFW ────────────────────────────────────────────
if grep -q "^IPV6=no" /etc/default/ufw 2>/dev/null; then
  echo "🔧 Activation IPv6 dans /etc/default/ufw"
  sed -i 's/^IPV6=no/IPV6=yes/' /etc/default/ufw
fi

# ─── 3. Reset des règles existantes ─────────────────────────────────────────
echo ""
echo "⚠  Reset des règles UFW existantes dans 5 secondes (Ctrl+C pour annuler)…"
sleep 5
ufw --force reset >/dev/null

# ─── 4. Politiques par défaut ───────────────────────────────────────────────
echo "🔧 Politiques par défaut : deny incoming, allow outgoing"
ufw default deny incoming
ufw default allow outgoing
ufw default deny routed   # pas de forwarding (sauf VPN/conteneurs si besoin → ajouter manuellement)

# ─── 5. Logging ─────────────────────────────────────────────────────────────
ufw logging low   # niveau low = juste les drops, pas le flood des connexions normales

# ─── 6. Loopback (automatique mais explicite pour clarté) ───────────────────
ufw allow in on lo
ufw deny in from 127.0.0.0/8   # anti-spoof loopback depuis interface réelle

# ─── 7. SelfFarm-Lite — LAN uniquement ──────────────────────────────────────
echo "🔧 Autorisation SelfFarm-Lite ($SELFFARM_PORT) depuis $LAN_SUBNET"
ufw allow from "$LAN_SUBNET" to any port "$SELFFARM_PORT" proto tcp comment 'SelfFarm-Lite LAN'

# ─── 8. mDNS / Bonjour (auto-discovery LAN — optionnel) ─────────────────────
# Décommente si tu utilises l'auto-discovery (NAS, imprimantes, AirPlay…)
# ufw allow from "$LAN_SUBNET" to any port 5353 proto udp comment 'mDNS / Bonjour'

# ─── 9. SSH (commenté par défaut — décommente seulement si SSH serveur actif) ─
# Vérifie d'abord : ss -tlnp | grep :22
# Si rien, ne décommente PAS.
# ufw limit from "$LAN_SUBNET" to any port 22 proto tcp comment 'SSH LAN anti-brute'

# ─── 10. Réponses ping ICMP (autorisées par défaut, mais expliciter) ────────
# Ping sortant (toi qui pingues) : déjà autorisé par allow outgoing
# Ping entrant (autres qui te pingues) : laissé bloqué pour réduire surface

# ─── 11. Anti-spoof IP privées sur interface non-LAN ────────────────────────
# Si tu as une interface ethernet/wifi avec IP publique directe (rare en domestique
# derrière box ISP), tu peux refuser les RFC1918 entrantes pour anti-spoof :
# ufw deny in on eth0 from 10.0.0.0/8
# ufw deny in on eth0 from 172.16.0.0/12

# ─── 12. Activation ─────────────────────────────────────────────────────────
echo ""
echo "🔧 Activation UFW…"
ufw --force enable

# ─── 13. Affichage status ───────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════════"
ufw status verbose
echo "═══════════════════════════════════════════════════════════════"

# ─── 14. Récap configuration ───────────────────────────────────────────────
echo ""
echo "✅ Hardening UFW appliqué."
echo ""
echo "Trafic SORTANT autorisé (allow outgoing) → GFN, Discord, Twitch,"
echo "Steam, navigation, mises à jour, jeux web : tout fonctionne natif."
echo ""
echo "Trafic ENTRANT autorisé (allow incoming) :"
echo "  • SelfFarm-Lite TCP $SELFFARM_PORT depuis $LAN_SUBNET seulement"
echo ""
echo "Logs UFW : sudo journalctl -u ufw -f"
echo "Status   : sudo ufw status verbose"
echo "Reset    : sudo ufw --force reset && sudo ufw disable"
echo ""
echo "Si un service ne marche plus :"
echo "  1. Identifier le port : ss -tlnp | grep LISTEN"
echo "  2. Logs UFW : sudo journalctl -u ufw --since '5 min ago' | grep BLOCK"
echo "  3. Ajouter la règle : sudo ufw allow from $LAN_SUBNET to any port <PORT> proto <tcp|udp>"
echo ""
