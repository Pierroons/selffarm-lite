#!/usr/bin/env bash
# Déploiement blindé SelfFarm-Lite → serveur de prod.
# Audit OPSEC AVANT toute copie + cycle prod-immutable (anti-tamper) + exclusions strictes.
#
# Configuration : renseigne `scripts/.env.deploy` (gitignoré, cf. .env.deploy.example)
# ou exporte les variables à la main.
#
#   SELFFARM_DEPLOY_REMOTE   user@hôte SSH du serveur de prod          (obligatoire)
#   SELFFARM_DEPLOY_STAGE    répertoire de transit, relatif au home distant
#   SELFFARM_DEPLOY_PROD     racine du code en production
#   SELFFARM_DEPLOY_IMMUT    script anti-tamper {lock|unlock|status}
#   SELFFARM_DEPLOY_SERVICE  unité systemd à redémarrer
#   SELFFARM_DEPLOY_HEALTH   URL(s) vérifiées à l'arrivée, séparées par des espaces
#
# Usage : ./scripts/deploy.sh
set -euo pipefail

# L'etape 4 lance des sudo sur la machine distante : sans terminal, sudo ne peut
# pas demander le mot de passe et le deploiement echoue au milieu, apres avoir
# deja pousse le lot sur le stage. Autant le dire avant de commencer.
if [ ! -t 0 ]; then
  echo "❌ Pas de terminal (stdin n'est pas un TTY)."
  echo "   L'etape 4 a besoin de saisir le mot de passe sudo de la prod."
  echo "   Lance ce script depuis un vrai terminal."
  exit 1
fi

ROOT="$(git rev-parse --show-toplevel)"
[ -f "$ROOT/scripts/.env.deploy" ] && . "$ROOT/scripts/.env.deploy"

REMOTE="${SELFFARM_DEPLOY_REMOTE:?renseigne scripts/.env.deploy (cf. .env.deploy.example)}"
STAGE="${SELFFARM_DEPLOY_STAGE:-selffarm-stage}"
PROD="${SELFFARM_DEPLOY_PROD:-/opt/selffarm-lite}"
IMMUT="${SELFFARM_DEPLOY_IMMUT:-/usr/local/sbin/prod-immutable.sh}"
SERVICE="${SELFFARM_DEPLOY_SERVICE:-selffarm-webapp}"
HEALTH="${SELFFARM_DEPLOY_HEALTH:-}"

EXCLUDES=(--exclude='.git' --exclude='.venv' --exclude='/data' --exclude='__pycache__'
          --exclude='*.pyc' --exclude='*.bak*' --exclude='.pytest_cache' --exclude='*.egg-info'
          --exclude='.mypy_cache' --exclude='.ruff_cache' --exclude='node_modules' --exclude='_perso'
          --exclude='scripts/.env.deploy'
          # OPSEC : les scénarios DNJA nominatifs (identité civile) ne sortent JAMAIS de la machine perso.
          --exclude='hypotheses-pierroons*' --exclude='hypotheses-perso*')

# Hors du depot : un stage a l'interieur se recopierait dans lui-meme, et il
# faudrait maintenir une exclusion de plus.
STAGE_LOCAL="${TMPDIR:-/tmp}/selffarm-deploy-stage-$(id -u)"

echo "→ [1/5] Construction du lot à déployer (exclusions strictes)…"
mkdir -p "$STAGE_LOCAL"
rsync -a --delete "${EXCLUDES[@]}" "$ROOT/" "$STAGE_LOCAL/"
echo "  $(find "$STAGE_LOCAL" -type f | wc -l) fichiers retenus"

echo "→ [2/5] Audit OPSEC (gitleaks) sur le lot…"
# On audite ce qui PART, pas ce qui traine dans le repertoire de travail : sinon
# un cache local fait echouer le deploiement d'un lot parfaitement propre, et
# l'echec pousse a contourner le garde-fou.
if command -v gitleaks >/dev/null 2>&1; then
  gitleaks detect --no-git --source "$STAGE_LOCAL" -c "$ROOT/.gitleaks.toml" --no-banner --redact \
    || { echo "❌ Déploiement ANNULÉ — donnée sensible dans le lot. Corrige avant de déployer."; exit 1; }
elif [ "${SELFFARM_DEPLOY_SKIP_AUDIT:-0}" = "1" ]; then
  echo "⚠ gitleaks absent — audit SAUTÉ sur demande explicite (SELFFARM_DEPLOY_SKIP_AUDIT=1)."
else
  # Sans cette barriere, une machine sans gitleaks deploie sans audit et le dit
  # sur une ligne d'avertissement que personne ne lit. On refuse plutot.
  echo "❌ Déploiement ANNULÉ — gitleaks absent, l'audit OPSEC ne peut pas tourner."
  echo "   Installe-le (sudo apt install gitleaks), ou force avec SELFFARM_DEPLOY_SKIP_AUDIT=1."
  exit 1
fi

echo "→ [3/5] Sync vers le stage distant…"
rsync -az --delete -e ssh "$STAGE_LOCAL/" "$REMOTE:$STAGE/"

echo "→ [4/5] Déploiement prod (unlock immutable → rsync → lock)…"
ssh -t "$REMOTE" "
  set -e
  # Quoi qu'il arrive ensuite, la prod se reverrouille : un echec entre unlock et
  # lock la laisserait modifiable sans que personne ne le sache.
  trap 'sudo \"$IMMUT\" lock' EXIT
  sudo '$IMMUT' unlock
  sudo rsync -a --delete --exclude=/data --exclude=.venv --exclude='*.egg-info' --exclude=__pycache__ --exclude=.git --exclude=_perso --exclude='hypotheses-pierroons*' --exclude='hypotheses-perso*' '$STAGE/' '$PROD/'
  sudo chown -R www-data:www-data '$PROD'
  sudo systemctl restart '$SERVICE'
  sudo '$IMMUT' lock
"

echo "→ [5/5] Vérification chez le destinataire…"
if [ -z "$HEALTH" ]; then
  echo "⚠ SELFFARM_DEPLOY_HEALTH non défini — déploiement non vérifié à l'arrivée."
else
  # Plusieurs URL, pas seulement /healthz : le 08/09/2026 un deploiement a rendu
  # healthz 200 pendant que la page d'accueil rendait 500 (schema de base
  # incompatible). Une sonde qui ne touche pas les donnees ne dit rien d'elles.
  echec=0
  for url in $HEALTH; do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "$url" || echo 000)
    printf '  %-52s HTTP %s\n' "$url" "$code"
    [ "$code" = "200" ] || echec=1
  done
  [ "$echec" -eq 0 ] || { echo "❌ Une URL au moins ne répond pas 200 — vérifie les journaux."; exit 1; }
fi
echo "✓ Déployé."
