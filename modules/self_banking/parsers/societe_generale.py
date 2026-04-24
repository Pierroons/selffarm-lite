"""
Parser pour relevés de compte Société Générale Particuliers (format PDF).

Gabarit supporté : SG Particuliers 2024-2026.
Testé sur fixtures générées par scripts/generate_sg_fake_statement.py.

Le parser respecte strictement le principe MySelf : 100 % local, aucune
donnée ne sort du poste utilisateur. Le PDF d'entrée est lu, parsé, et
seule la structure normalisée (Releve) est retournée.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pdfplumber

from self_banking.models import Releve, Transaction, TypeMouvement

# --- Regex réutilisables ------------------------------------------------------

RE_PERIODE = re.compile(
    r"du\s+(\d{2}/\d{2}/\d{4})\s+au\s+(\d{2}/\d{2}/\d{4})",
    re.DOTALL,
)
RE_SOLDE_PRECEDENT = re.compile(
    r"SOLDE\s+PR[ÉE]C[ÉE]DENT\s+AU\s+\d{2}/\d{2}/\d{4}\s+([\d\s\xa0]+[.,]\d{2})",
    re.DOTALL,
)
RE_SOLDE_FINAL = re.compile(
    r"\*{3}\s*SOLDE\s+AU\s+\d{2}/\d{2}/\d{4}\s*\*{3}\s+([\d\s\xa0]+[.,]\d{2})",
    re.DOTALL,
)
RE_SOLDE_DEBITEUR = re.compile(
    r"solde\s+est\s+(d[ée]biteur|cr[ée]diteur)\s+de\s+(-?\s*[\d\s\xa0]+[.,]\d{2})",
    re.DOTALL,
)
RE_NUM_COMPTE = re.compile(r"n°\s*(\d{5}\s+\d{5}\s+\d{11}\s+\d{2})")

# Ligne d'opération : "DD/MM/YYYY  DD/MM/YYYY  LIBELLE  MONTANT"
# Deux dates (op + valeur), libellé variable, puis 1 ou 2 montants en fin (débit/crédit)
RE_LIGNE_OP = re.compile(
    r"^(\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})\s+(.+?)\s+([\d\s]+[.,]\d{2})\s*$"
)

# Montant au format FR : "1 234,56" ou "1234,56" ou "12.34"
RE_MONTANT = re.compile(r"[\d\s]+[.,]\d{2}")


# --- Utilitaires --------------------------------------------------------------

def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%d/%m/%Y").date()


def _parse_montant(s: str) -> Decimal:
    """Convertit un montant format FR en Decimal.
    Exemples : '1 234,56' → 1234.56 | '12,84' → 12.84 | '- 195,80' → -195.80
    """
    cleaned = s.replace("\xa0", "").replace(" ", "").replace(",", ".").strip()
    return Decimal(cleaned)


def _detect_type_mouvement(libelle: str) -> TypeMouvement:
    """Classification du mouvement via mots-clés du libellé SG."""
    libelle_upper = libelle.upper()
    # Virements émis (toutes variantes SG : instantané, européen, SEPA, Logitel)
    if "VIR" in libelle_upper and ("EMIS" in libelle_upper or "ÉMIS" in libelle_upper):
        return TypeMouvement.VIREMENT_EMIS
    # Virements reçus
    if "VIR" in libelle_upper and ("RECU" in libelle_upper or "REÇU" in libelle_upper):
        return TypeMouvement.VIREMENT_RECU
    # Prélèvements (SEPA, européens, simples)
    if "PRLV" in libelle_upper or "PRELEVEMENT" in libelle_upper or "PRÉLÈVEMENT" in libelle_upper:
        return TypeMouvement.PRELEVEMENT
    # Carte bancaire
    if "ACHAT CB" in libelle_upper or "PAIEMENT CB" in libelle_upper or "CB " in libelle_upper:
        return TypeMouvement.CARTE_BANCAIRE
    # Chèques
    if "CHEQUE" in libelle_upper or "CHÈQUE" in libelle_upper or "CHQ" in libelle_upper:
        if "REMIS" in libelle_upper or "ENCAISS" in libelle_upper or "RECU" in libelle_upper:
            return TypeMouvement.CHEQUE_RECU
        return TypeMouvement.CHEQUE_EMIS
    # Retraits DAB
    if "RETRAIT" in libelle_upper or "DAB" in libelle_upper:
        return TypeMouvement.RETRAIT_DAB
    # Dépôts espèces
    if "DEPOT ESPECES" in libelle_upper or "VERS ESP" in libelle_upper or "VERSEMENT" in libelle_upper:
        return TypeMouvement.DEPOT_ESPECES
    # Frais bancaires
    if "COMMISSION" in libelle_upper or "FRAIS" in libelle_upper or "AGIOS" in libelle_upper or "COTISATION" in libelle_upper:
        return TypeMouvement.FRAIS_BANCAIRES
    # Intérêts
    if "INTERETS" in libelle_upper or "INTÉRÊTS" in libelle_upper:
        return TypeMouvement.INTERETS
    return TypeMouvement.INCONNU


def _extract_contrepartie(libelle: str, sous_lignes: list[str]) -> str | None:
    """Extrait la contrepartie (bénéficiaire/émetteur) depuis les sous-lignes SG.

    Formats SG observés :
      POUR: BENEFICIAIRE     → virement émis
      DE: EMETTEUR           → virement reçu
      PRLV SEPA NOM_CREANCIER → prélèvement (dans la ligne principale)
    """
    for sl in sous_lignes:
        m = re.match(r"\s*(?:POUR|DE)\s*:\s*(.+)", sl, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    # Prélèvement : contrepartie directement dans libellé après "PRLV SEPA"
    m = re.match(r"PRLV\s+SEPA\s+(.+)", libelle.upper())
    if m:
        return m.group(1).strip()
    # Achat CB : marchand après "ACHAT CB"
    m = re.match(r"ACHAT\s+CB\s+(.+?)(?:\s+\d{2}/\d{2})?$", libelle.upper())
    if m:
        return m.group(1).strip()
    return None


def _extract_reference(sous_lignes: list[str]) -> str | None:
    """Extrait la référence bancaire si présente (REF: XXXX)."""
    for sl in sous_lignes:
        m = re.search(r"REF\s*:\s*(\S+)", sl)
        if m:
            return m.group(1)
    return None


# --- Parser principal --------------------------------------------------------

def parse_sg_pdf(path: Path) -> Releve:
    """Parse un relevé SG Particuliers et retourne un objet Releve normalisé."""
    path = Path(path)

    with pdfplumber.open(str(path)) as pdf:
        # On ne se fie PAS à extract_text() — sur les relevés SG multi-colonnes
        # il casse l'ordre des mots. On reconstruit le texte à partir de
        # extract_words() en groupant les mots par (page, ligne Y) triés par X.
        all_words = []
        for page_idx, p in enumerate(pdf.pages):
            for w in p.extract_words(x_tolerance=2, y_tolerance=2):
                w["page_idx"] = page_idx
                all_words.append(w)

    full_text = _reconstruct_text_from_words(all_words)

    if "particuliers.sg.fr" not in full_text and "SOCIETE GENERALE" not in full_text.upper():
        raise ValueError(
            f"{path} n'est pas un relevé SG reconnu. "
            "Marqueur attendu : 'particuliers.sg.fr' ou 'SOCIETE GENERALE'."
        )

    # --- Extraction période ---
    periode_debut, periode_fin = _extract_periode(full_text)

    # --- Détection des colonnes Débit/Crédit par leurs en-têtes ---
    col_debit_x1, col_credit_x1 = _detect_column_positions(all_words)

    # --- Extraction soldes ---
    solde_precedent = _extract_solde_precedent(full_text)
    solde_final = _extract_solde_final(full_text)

    # --- Extraction transactions via positions X ---
    transactions = _extract_transactions_by_position(all_words, col_debit_x1, col_credit_x1)

    return Releve(
        banque="SG",
        periode_debut=periode_debut,
        periode_fin=periode_fin,
        solde_precedent=solde_precedent,
        solde_final=solde_final,
        transactions=transactions,
    )


def _reconstruct_text_from_words(words: list[dict]) -> str:
    """Reconstruit le texte ligne par ligne à partir des positions réelles des mots.

    Approche nécessaire pour les relevés SG multi-colonnes où extract_text()
    mélange les colonnes. En triant par (page, top, x0) on recrée l'ordre
    de lecture attendu.
    """
    lignes: dict[tuple[int, int], list[dict]] = {}
    for w in words:
        key = (w.get("page_idx", 0), round(w["top"] / 3) * 3)
        lignes.setdefault(key, []).append(w)
    lignes_triees = sorted(lignes.items(), key=lambda kv: (kv[0][0], kv[0][1]))
    return "\n".join(
        " ".join(w["text"] for w in sorted(mots, key=lambda x: x["x0"]))
        for _, mots in lignes_triees
    )


def _extract_periode(full_text: str) -> tuple[date, date]:
    """Extrait la période du relevé avec 3 fallbacks successifs.

    1. "du DD/MM/YYYY au DD/MM/YYYY" strict
    2. "du ... DD/MM/YYYY ... au ... DD/MM/YYYY" très tolérant (multi-ligne)
    3. Les 2 premières dates DD/MM/YYYY de l'entête
    """
    # Tentative 1 : pattern strict
    m = RE_PERIODE.search(full_text)
    if m:
        return _parse_date(m.group(1)), _parse_date(m.group(2))

    # Tentative 2 : tolérant aux retours à la ligne entre mots-clés
    m = re.search(
        r"du[\s\S]{0,50}?(\d{2}/\d{2}/\d{4})[\s\S]{0,50}?au[\s\S]{0,50}?(\d{2}/\d{2}/\d{4})",
        full_text,
    )
    if m:
        return _parse_date(m.group(1)), _parse_date(m.group(2))

    # Tentative 3 : on prend les 2 premières dates du document (toujours dans l'entête SG)
    dates_trouvees = re.findall(r"\d{2}/\d{2}/\d{4}", full_text[:2000])
    if len(dates_trouvees) >= 2:
        d1, d2 = _parse_date(dates_trouvees[0]), _parse_date(dates_trouvees[1])
        if d1 < d2 and (d2 - d1).days <= 40:  # période mensuelle cohérente
            return d1, d2

    raise ValueError(
        "Période du relevé introuvable. "
        f"Dates trouvées dans l'entête : {dates_trouvees[:4] if dates_trouvees else 'aucune'}"
    )


def _detect_column_positions(words: list[dict]) -> tuple[float, float]:
    """Détecte les positions X des colonnes Débit / Crédit via leurs en-têtes.

    Retourne (x_max_debit, x_max_credit) = positions x1 des headers + marge.
    """
    x_debit, x_credit = None, None
    for w in words:
        if w["text"] == "Débit":
            x_debit = w["x1"]
        elif w["text"] == "Crédit":
            x_credit = w["x1"]
    if x_debit is None or x_credit is None:
        # Fallback : valeurs observées gabarit SG standard (A4)
        x_debit, x_credit = 482.0, 553.0
    return x_debit, x_credit


def _extract_solde_precedent(full_text: str) -> Decimal:
    """Extrait le solde précédent avec plusieurs stratégies.

    1. "SOLDE PRÉCÉDENT AU DD/MM/YYYY  MONTANT" (même ligne)
    2. "SOLDE PRÉCÉDENT AU DD/MM/YYYY" puis montant dans les ~200 chars suivants
    3. Premier "*** SOLDE AU DD/MM/YYYY *** [+/-] MONTANT" après "SOLDE PRÉCÉDENT"
    """
    m = RE_SOLDE_PRECEDENT.search(full_text)
    if m:
        return _parse_montant(m.group(1))

    # Fallback : trouve "SOLDE PRÉCÉDENT" puis cherche un montant dans la suite
    pos_prec = re.search(r"SOLDE\s+PR[ÉE]C[ÉE]DENT\s+AU\s+\d{2}/\d{2}/\d{4}", full_text)
    if pos_prec:
        zone = full_text[pos_prec.end():pos_prec.end() + 400]

        # Fallback 2a : premier montant simple dans les 200 chars suivants
        m2 = re.search(r"([\d\s\xa0]+[.,]\d{2})", zone[:200])
        if m2:
            return _parse_montant(m2.group(1))

        # Fallback 2b : pattern "*** SOLDE AU DD/MM/YYYY *** [+/-]? MONTANT"
        m3 = re.search(
            r"\*{3}\s*SOLDE\s+AU\s+\d{2}/\d{2}/\d{4}\s*\*{3}\s*([+-])?\s*([\d\s\xa0]+[.,]\d{2})",
            zone,
        )
        if m3:
            raw = _parse_montant(m3.group(2))
            if m3.group(1) == "-":
                raw = -raw
            return raw

    raise ValueError(
        "Solde précédent introuvable. "
        "Patterns testés : 'SOLDE PRÉCÉDENT AU DD/MM/YYYY MONTANT' et "
        "fallback '*** SOLDE AU ... ***'."
    )


def _extract_solde_final(full_text: str) -> Decimal:
    """Extrait le solde final, signé si débiteur."""
    m_debit = RE_SOLDE_DEBITEUR.search(full_text)
    m_final = RE_SOLDE_FINAL.search(full_text)
    if m_final:
        raw = _parse_montant(m_final.group(1))
        if m_debit and m_debit.group(1) == "débiteur" and raw > 0:
            raw = -raw
        return raw
    if m_debit:
        raw = _parse_montant(m_debit.group(2).replace("-", "").strip())
        return -raw if m_debit.group(1) == "débiteur" else raw
    raise ValueError("Solde final introuvable.")


def _extract_transactions_by_position(
    words: list[dict],
    col_debit_x1: float,
    col_credit_x1: float,
) -> list[Transaction]:
    """Extraction via positions X des mots pour distinguer débit vs crédit.

    Règle : un montant dont x1 ∈ [col_debit_x1 ± 5] = débit ;
            un montant dont x1 ∈ [col_credit_x1 ± 5] = crédit.
    """
    # Groupe les mots par (page, ligne Y arrondie) pour ne pas mélanger les pages.
    lignes: dict[tuple[int, int], list[dict]] = {}
    for w in words:
        key = (w.get("page_idx", 0), round(w["top"] / 3) * 3)
        lignes.setdefault(key, []).append(w)

    # Trie par page puis Y croissant
    lignes_triees = sorted(lignes.items(), key=lambda kv: (kv[0][0], kv[0][1]))

    transactions: list[Transaction] = []
    current: dict | None = None
    started = False
    seuil_col = (col_debit_x1 + col_credit_x1) / 2  # ~517pt

    # Première détection : position Y du début du tableau.
    # 3 stratégies par ordre de fiabilité :
    # 1. Ligne contenant "RELEVÉ DES OPÉRATIONS"
    # 2. Ligne header avec "Débit" ET "Crédit" adjacents (~en-tête tableau)
    # 3. Première ligne qui commence par 2 dates DD/MM/YYYY
    y_debut_tableau = None
    for (_, y), mots in lignes_triees:
        mots_sorted = sorted(mots, key=lambda w: w["x0"])
        texte = " ".join(w["text"] for w in mots_sorted)
        if "RELEVÉ" in texte and "OPÉRATIONS" in texte:
            y_debut_tableau = y
            break
    if y_debut_tableau is None:
        # Fallback 2 : ligne avec Débit ET Crédit
        for (_, y), mots in lignes_triees:
            textes = {w["text"] for w in mots}
            if "Débit" in textes and "Crédit" in textes:
                y_debut_tableau = y
                break
    if y_debut_tableau is None:
        # Fallback 3 : première ligne commençant par 2 dates
        for (_, y), mots in lignes_triees:
            mots_sorted = sorted(mots, key=lambda w: w["x0"])
            if len(mots_sorted) >= 2 and _is_date(mots_sorted[0]["text"]) and _is_date(mots_sorted[1]["text"]):
                y_debut_tableau = y - 1  # un peu avant pour être sûr de l'inclure
                break

    for (page_idx, y), mots in lignes_triees:
        mots = sorted(mots, key=lambda w: w["x0"])
        texte = " ".join(w["text"] for w in mots)

        # Skip tout avant le début du tableau
        if not started:
            if y_debut_tableau is not None and y >= y_debut_tableau:
                started = True
            else:
                continue

        # SG intercale des soldes intermédiaires "*** SOLDE AU DD/MM ***" au fil
        # du mois. On SKIP ces lignes (ne pas break — le tableau continue après).
        a_etoile = any("*" in w["text"] for w in mots)
        if a_etoile and "SOLDE" in texte and "AU" in texte:
            # Flush la transaction en cours avant le solde intermédiaire
            if current:
                transactions.append(_finalize_transaction(current))
                current = None
            continue

        # Ligne d'opération : commence par 2 dates DD/MM/YYYY
        if len(mots) >= 2 and _is_date(mots[0]["text"]) and _is_date(mots[1]["text"]):
            if current:
                transactions.append(_finalize_transaction(current))
            date_op = _parse_date(mots[0]["text"])
            date_val = _parse_date(mots[1]["text"])

            # Identifier les montants dans la ligne avec leur position
            debit = credit = None
            libelle_mots = []
            for w in mots[2:]:
                if _is_montant(w["text"]):
                    montant = _parse_montant(w["text"])
                    if w["x1"] >= seuil_col:
                        credit = montant
                    else:
                        debit = montant
                else:
                    libelle_mots.append(w["text"])
            libelle = " ".join(libelle_mots).strip()

            current = {
                "date_op": date_op,
                "date_val": date_val,
                "libelle": libelle,
                "debit": debit,
                "credit": credit,
                "sous_lignes": [],
            }
        elif "SOLDE PRÉCÉDENT" in texte:
            continue
        elif current is not None:
            # Ligne de continuation
            current["sous_lignes"].append(texte)

    if current:
        transactions.append(_finalize_transaction(current))

    return transactions


def _is_date(s: str) -> bool:
    return bool(re.match(r"^\d{2}/\d{2}/\d{4}$", s))


def _is_montant(s: str) -> bool:
    """Teste si un token isolé est un montant format FR (incluant '1 234,56' séparé).
    Note : pdfplumber split parfois les montants avec espace insécable,
    on accepte donc les tokens de forme simple 'DDD,DD' ou 'D DDD,DD'.
    """
    return bool(re.match(r"^[\d\s]+[.,]\d{2}$", s))


def _finalize_transaction(d: dict) -> Transaction:
    """Construit un objet Transaction depuis le dict accumulé."""
    return Transaction(
        date_operation=d["date_op"],
        date_valeur=d["date_val"],
        libelle=d["libelle"],
        debit=d["debit"],
        credit=d["credit"],
        type_mouvement=_detect_type_mouvement(d["libelle"]),
        reference=_extract_reference(d["sous_lignes"]),
        contrepartie=_extract_contrepartie(d["libelle"], d["sous_lignes"]),
    )
