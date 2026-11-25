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
# Un lien symbolique ne porte pas d'attribut : il ne se fige jamais lui-même. Il n'est
# un trou que si son DOSSIER PARENT est modifiable — un dossier figé n'accepte ni
# création ni suppression d'entrée, donc le lien ne peut pas y être remplacé. Un lien
# dont le parent est figé compte donc pour sûr : c'est le cas des quatre liens qu'un
# venv Python pose vers son interpréteur.
#
# Depuis le 24/11/2026, .venv n'est plus exclu : un venv est du code, et prod-immutable.sh
# le fige. Un dossier nommé data reste élagué à toute profondeur, y compris dans le venv,
# pour que ce script reste le miroir exact de ce que le gel a traité.
set -uo pipefail
export LC_ALL=C

P=${1:?racine du code de prod}
[ -d "$P" ] || { echo "mesure impossible : $P absent"; exit 2; }

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
liens=""
while IFS= read -r -d '' lien; do
  case "$(lsattr -d "$(dirname "$lien")" 2>/dev/null)" in
    ????i*) continue ;;
  esac
  liens+="$lien"$'\n'
done < <(find "$P" "${EXCLUS[@]}" -o -type l -print0)
liens=${liens%$'\n'}

if [ "$total" -eq 0 ] || [ "$lus" -ne "$total" ]; then
  echo "mesure impossible : $lus attribut(s) lu(s) pour $total entrée(s)"
  exit 2
fi
if [ -n "$liens" ]; then
  echo "$(grep -c . <<<"$liens") lien(s) symbolique(s) dans un dossier modifiable, dont :"
  head -5 <<<"$liens" | sed 's/^/  /'
  exit 1
fi
if [ "$figees" -ne "$total" ]; then
  echo "$((total - figees)) entrée(s) de code modifiable(s) sur $total, dont :"
  grep -v -E '^....i' <<<"$attributs" | head -5 | sed 's/^/  /'
  exit 1
fi
echo "$total entrées de code figées (hors dossiers de données)"
