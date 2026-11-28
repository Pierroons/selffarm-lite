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
#
# Le compte apparie une ligne de lsattr à une entrée : un nom qui porte un caractère
# de contrôle (un retour à la ligne y vaudrait deux lignes) rend la mesure impossible,
# comme un dossier que find ne peut pas lire.
#
# Un lien symbolique ne porte pas d'attribut : il ne se fige jamais lui-même. Deux
# conditions le rendent sûr, et il faut les DEUX :
#   1. son dossier parent est figé — un dossier figé n'accepte ni création ni
#      suppression d'entrée, donc le lien ne peut pas y être remplacé ;
#   2. sa cible ne peut pas être réécrite par le compte qui sert l'application —
#      cible figée, ou cible hors de l'arbre et détenue par un autre compte.
# La seconde manquait. Sans elle, un lien posé pendant la fenêtre d'un déploiement et
# pointant vers un dossier de données donnait du code exécuté, réécrivable à volonté,
# et compté « figé » : le gel protégeait le lien, jamais ce qu'il désigne. Relevé par
# une relecture du 25/11/2026 ; sur la cible mesurée ce jour-là, les quatre liens d'un
# venv visaient l'interpréteur du système (root, hors arbre) ou un dossier figé, donc
# aucun n'était dans ce cas — le défaut était dans ce script, pas encore sur la machine.
#
# Depuis le 24/11/2026, .venv n'est plus exclu : un venv est du code, et prod-immutable.sh
# le fige. Un dossier nommé data reste élagué à toute profondeur, y compris dans le venv,
# pour que ce script reste le miroir exact de ce que le gel a traité.
set -uo pipefail
export LC_ALL=C

# Sans argument, le script sortait en 1 — le code réservé à « au moins une entrée
# modifiable ». Son lecteur affichait alors « PROD NON REVERROUILLÉE » sur ce qui est
# une erreur d'appel. Une mesure qu'on ne peut pas faire sort en 2.
[ -n "${1:-}" ] || { echo "mesure impossible : racine du code de prod attendue en argument"; exit 2; }
P=$1
[ -d "$P" ] || { echo "mesure impossible : $P absent"; exit 2; }
PROPRIO=$(stat -c %U "$P" 2>/dev/null || true)

EXCLUS=( -type d \( -name data -o -name uploads -o -name logs -o -name cache -o -name tmp
         -o -name sessions -o -name node_modules \) -prune )
liste() { find "$P" "${EXCLUS[@]}" -o \( -type f -o -type d \) -print0; }

erreurs=$(liste 2>&1 >/dev/null)
[ -z "$erreurs" ] || { echo "mesure impossible : ${erreurs%%$'\n'*}"; exit 2; }
piege=$(find "$P" "${EXCLUS[@]}" -o -name '*[[:cntrl:]]*' -print -quit)
[ -z "$piege" ] || { echo "mesure impossible : un nom porte un caractère de contrôle"; exit 2; }

total=$(liste | tr -cd '\0' | wc -c)
attributs=$(liste | xargs -0 -r lsattr -d 2>/dev/null)
lus=$(grep -c . <<<"$attributs")
figees=$(grep -c -E '^....i' <<<"$attributs")
fige() { case "$(lsattr -d "$1" 2>/dev/null)" in ????i*) return 0 ;; *) return 1 ;; esac; }
hors_arbre() { case "$1" in "$P"/*|"$P") return 1 ;; *) return 0 ;; esac; }

liens=""
while IFS= read -r -d '' lien; do
  cible=$(readlink -f "$lien" 2>/dev/null || true)
  if ! fige "$(dirname "$lien")"; then
    liens+="$lien — dans un dossier modifiable"$'\n'
  elif [ -z "$cible" ] || [ ! -e "$cible" ]; then
    liens+="$lien — cible absente"$'\n'
  elif fige "$cible"; then
    :
  elif hors_arbre "$cible" && [ -n "$PROPRIO" ] \
       && [ "$(stat -c %U "$cible" 2>/dev/null || true)" != "$PROPRIO" ]; then
    :
  else
    liens+="$lien → $cible — cible réécrivable"$'\n'
  fi
done < <(find "$P" "${EXCLUS[@]}" -o -type l -print0)
liens=${liens%$'\n'}

if [ "$total" -eq 0 ] || [ "$lus" -ne "$total" ]; then
  echo "mesure impossible : $lus attribut(s) lu(s) pour $total entrée(s)"
  exit 2
fi
if [ -n "$liens" ]; then
  echo "$(grep -c . <<<"$liens") lien(s) symbolique(s) que le gel ne protège pas, dont :"
  head -5 <<<"$liens" | sed 's/^/  /'
  exit 1
fi
if [ "$figees" -ne "$total" ]; then
  echo "$((total - figees)) entrée(s) de code modifiable(s) sur $total, dont :"
  grep -v -E '^....i' <<<"$attributs" | head -5 | sed 's/^/  /'
  exit 1
fi
echo "$total entrées de code figées (hors dossiers de données)"
