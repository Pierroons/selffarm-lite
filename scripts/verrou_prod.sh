#!/usr/bin/env bash
# Mesure, sans sudo, que le code de prod est figé (attribut immuable, chattr +i).
# deploy.sh l'envoie par ssh après l'étape 4 : le reverrouillage se lit, il ne se
# suppose pas d'un code de retour.
#
# Usage : bash verrou_prod.sh <racine du code>
# Sortie : 0 tout est figé · 1 au moins une entrée modifiable · 2 mesure impossible.
#
# Les dossiers exclus sont ceux que prod-immutable.sh laisse inscriptibles, par nom
# et à toute profondeur. Un dossier qu'il exclurait sans figurer ici fait sortir 1 :
# l'écart se voit, il ne passe pas.
set -uo pipefail

P=${1:?racine du code de prod}
[ -d "$P" ] || { echo "mesure impossible : $P absent"; exit 2; }

liste() {
  find "$P" -type d \( -name data -o -name uploads -o -name logs -o -name cache -o -name tmp \
    -o -name sessions -o -name .venv -o -name node_modules \) -prune \
    -o \( -type f -o -type d \) -print0
}

total=$(liste | tr -cd '\0' | wc -c)
attributs=$(liste | xargs -0 -r lsattr -d 2>/dev/null)
lus=$(grep -c . <<<"$attributs")
figees=$(grep -c -E '^....i' <<<"$attributs")

if [ "$total" -eq 0 ] || [ "$lus" -ne "$total" ]; then
  echo "mesure impossible : $lus attribut(s) lu(s) pour $total entrée(s)"
  exit 2
fi
if [ "$figees" -ne "$total" ]; then
  echo "$((total - figees)) entrée(s) de code modifiable(s) sur $total, dont :"
  grep -v -E '^....i' <<<"$attributs" | head -5 | sed 's/^/  /'
  exit 1
fi
echo "$total entrées de code figées"
