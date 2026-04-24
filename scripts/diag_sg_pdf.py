"""
Diagnostic NON-SENSIBLE d'un relevé SG pour debugger le parser.

Affiche UNIQUEMENT des infos structurelles :
- Présence/absence de mots-clés
- Nombre d'occurrences
- Positions relatives
- PAS de montants, PAS de noms, PAS de libellés complets

Résultat partageable sans risque pour ton intimité.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/diag_sg_pdf.py <chemin_pdf>", file=sys.stderr)
        return 1

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"✗ Fichier introuvable : {path}", file=sys.stderr)
        return 1

    try:
        import pdfplumber
    except ImportError:
        print("✗ pdfplumber absent. Lance depuis .venv du projet.", file=sys.stderr)
        return 1

    with pdfplumber.open(str(path)) as pdf:
        full_text = "\n".join(p.extract_text() or "" for p in pdf.pages)
        layout_text = "\n".join(p.extract_text(layout=True) or "" for p in pdf.pages)
        nb_pages = len(pdf.pages)

    print("=" * 70)
    print(f"DIAGNOSTIC PDF — {path.name}")
    print("=" * 70)
    print(f"Pages                     : {nb_pages}")
    print(f"Taille texte (sans layout): {len(full_text)} chars")
    print(f"Taille texte (avec layout): {len(layout_text)} chars")
    print()

    keywords = [
        "RELEVÉ DE COMPTE",
        "particuliers.sg.fr",
        "SOLDE PRÉCÉDENT",
        "SOLDE\nPRÉCÉDENT",
        "PRÉCÉDENT",
        "SOLDE",
        "*** SOLDE AU",
        "**",
        "RELEVÉ DES OPÉRATIONS",
        "COMPTE DE PARTICULIER",
        "Nature de l'opération",
        "Débit",
        "Crédit",
        "Date",
        "Valeur",
    ]

    print("Mots-clés (extract_text SANS layout) :")
    for kw in keywords:
        count = full_text.count(kw)
        print(f"  {repr(kw):40} : {count} occurrence(s)")

    print()
    print("Mots-clés (extract_text AVEC layout=True) :")
    for kw in keywords:
        count = layout_text.count(kw)
        print(f"  {repr(kw):40} : {count} occurrence(s)")

    # Regex tolérants sur les deux textes
    print()
    print("Regex tolérants (layout=True) :")
    patterns = [
        (r"SOLDE\s+PR[ÉE]C[ÉE]DENT", "SOLDE\\s+PRÉCÉDENT (tolérant)"),
        (r"SOLDE\s+PR[ÉE]C[ÉE]DENT\s+AU\s+\d{2}/\d{2}/\d{4}", "SOLDE PRÉCÉDENT AU DATE"),
        (r"\*+\s*SOLDE\s+AU", "*** SOLDE AU (tolérant *)"),
        (r"SOLDE\s+AU\s+\d{2}/\d{2}/\d{4}", "SOLDE AU DATE (sans étoiles)"),
    ]
    for regex, label in patterns:
        found_simple = len(re.findall(regex, full_text))
        found_layout = len(re.findall(regex, layout_text))
        print(f"  {label:40} : sans_layout={found_simple}  avec_layout={found_layout}")

    # --- Premières positions des dates ---
    dates = re.findall(r"\d{2}/\d{2}/\d{4}", full_text)
    print()
    print(f"Dates DD/MM/YYYY trouvées : {len(dates)} total")
    if dates:
        print(f"  4 premières : {dates[:4]}")

    # --- Pattern période "du XX/XX/XXXX au XX/XX/XXXX" ---
    m = re.search(r"du\s+(\d{2}/\d{2}/\d{4})\s+au\s+(\d{2}/\d{2}/\d{4})", full_text)
    print()
    print(f"Pattern 'du DATE au DATE' strict : {'✓ trouvé' if m else '✗ non trouvé'}")
    m2 = re.search(r"du[\s\S]{0,80}?(\d{2}/\d{2}/\d{4})[\s\S]{0,80}?au[\s\S]{0,80}?(\d{2}/\d{2}/\d{4})", full_text)
    print(f"Pattern 'du DATE au DATE' tolérant : {'✓ trouvé' if m2 else '✗ non trouvé'}")

    # --- Zones "SOLDE PRÉCÉDENT" et "*** SOLDE AU" ---
    print()
    print("Contexte autour de 'SOLDE PRÉCÉDENT' :")
    for m in re.finditer(r"SOLDE\s+PR[ÉE]C[ÉE]DENT", full_text, re.IGNORECASE):
        # Affiche UNIQUEMENT les caractères de structure (retours ligne, espaces, ponctuation)
        # et masque les lettres/chiffres par des 'X'/'9'
        context = full_text[m.start(): m.start() + 120]
        masked = "".join(
            "9" if c.isdigit() else
            "X" if c.isalpha() and c not in "SOLDEPRÉCÉDENTAU*" else
            c
            for c in context
        )
        print(f"  pos={m.start()}  structure: {masked[:120]!r}")

    print()
    print("Contexte autour de '*** SOLDE AU' (3 premières occurrences) :")
    count = 0
    for m in re.finditer(r"\*{3}\s*SOLDE\s+AU", full_text):
        context = full_text[m.start(): m.start() + 80]
        masked = "".join(
            "9" if c.isdigit() else
            "X" if c.isalpha() and c not in "SOLDEAU*+-" else
            c
            for c in context
        )
        print(f"  pos={m.start()}  structure: {masked[:80]!r}")
        count += 1
        if count >= 3:
            break

    # --- Pattern montant générique ---
    print()
    montants = re.findall(r"[\d\s\xa0]+[.,]\d{2}", full_text)
    print(f"Tokens 'montant' (format DDD,DD) trouvés : {len(montants)}")

    # --- Structure de ligne (layout) : stats sans contenu ---
    print()
    print("Stats extract_text(layout=True) :")
    lignes_layout = layout_text.splitlines()
    print(f"  Nombre de lignes : {len(lignes_layout)}")
    lignes_non_vides = [l for l in lignes_layout if l.strip()]
    print(f"  Lignes non vides : {len(lignes_non_vides)}")

    # --- Structure des lignes du tableau (masquée) ---
    print()
    print("Structure des 25 premières lignes après le début du tableau :")
    print("(D=date, M=montant, A=mot alpha, n=chiffre isolé, *=astérisque)")
    print("-" * 70)
    with pdfplumber.open(str(path)) as pdf:
        all_words = []
        for page_idx, p in enumerate(pdf.pages):
            for w in p.extract_words(x_tolerance=2, y_tolerance=2):
                w["page_idx"] = page_idx
                all_words.append(w)
    lignes = {}
    for w in all_words:
        k = (w.get("page_idx", 0), round(w["top"] / 3) * 3)
        lignes.setdefault(k, []).append(w)
    lignes_triees = sorted(lignes.items(), key=lambda kv: (kv[0][0], kv[0][1]))

    # Trouve début tableau par header "Débit" + "Crédit"
    y_debut = None
    for (_, y), mots in lignes_triees:
        textes_set = {w["text"] for w in mots}
        if "Débit" in textes_set and "Crédit" in textes_set:
            y_debut = y
            break
    if y_debut is None:
        # Fallback : 1ère ligne avec 2 dates au début
        for (_, y), mots in lignes_triees:
            mots_s = sorted(mots, key=lambda w: w["x0"])
            if (len(mots_s) >= 2
                and re.match(r"^\d{2}/\d{2}/\d{4}$", mots_s[0]["text"])
                and re.match(r"^\d{2}/\d{2}/\d{4}$", mots_s[1]["text"])):
                y_debut = y - 1
                break

    print(f"Y_début_tableau détecté : {y_debut}")
    if y_debut is None:
        print("  → Aucune détection du début de tableau")
    else:
        count = 0
        for (page_idx, y), mots in lignes_triees:
            if y < y_debut:
                continue
            mots_s = sorted(mots, key=lambda w: w["x0"])
            # Forme masquée
            formes = []
            for w in mots_s:
                t = w["text"]
                if re.match(r"^\d{2}/\d{2}/\d{4}$", t):
                    formes.append(f"D[x={int(w['x0'])}-{int(w['x1'])}]")
                elif re.match(r"^[\d\s\xa0]+[.,]\d{2}$", t):
                    formes.append(f"M[x={int(w['x0'])}-{int(w['x1'])}]")
                elif t.isalpha():
                    formes.append(f"A[x={int(w['x0'])},len={len(t)}]")
                elif t.isdigit():
                    formes.append(f"n[x={int(w['x0'])},len={len(t)}]")
                elif "*" in t:
                    formes.append(f"*[x={int(w['x0'])}]")
                else:
                    formes.append(f"?[x={int(w['x0'])},len={len(t)}]")
            print(f"  page={page_idx} y={y:4} nb={len(mots_s):2} : {' '.join(formes)[:120]}")
            count += 1
            if count >= 25:
                break

    print()
    print("Pour me partager cette sortie : copie-colle le tout,")
    print("AUCUNE info financière n'y figure (uniquement structure).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
