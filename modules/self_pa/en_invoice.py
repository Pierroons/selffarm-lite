"""
Lecture de la facture décodée par la plateforme (`en_invoice`, EN 16931).

C'est le chemin principal : la plateforme agréée a déjà décodé le Factur-X et
rend une structure JSON normalisée. Il n'y a plus qu'à la transposer.

`cii_reader` reste utile ailleurs — canal mail, et contrôle croisé du XML
embarqué contre ce que la plateforme annonce. Les deux modules produisent le même
`FactureRecue`, ce qui rend cette comparaison possible sans conversion.

Sur les montants : Super PDP les rend en **chaînes** (`"1863.79"`), et c'est ce
qui permet de les charger en `Decimal` sans jamais passer par un `float`. Le code
convertit malgré tout via `str()` — si un jour la plateforme rendait des nombres
JSON nus, la conversion resterait exacte au lieu de traîner une erreur de
représentation binaire jusque dans une écriture comptable.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from self_pa.models import (
    FactureRecue,
    LigneFacture,
    PartieFacture,
    VentilationTva,
)

log = logging.getLogger("selffarm.self_pa.en_invoice")


class ErreurLectureEnInvoice(ValueError):
    """La charge utile n'a pas la forme d'un `en_invoice`."""


def _decimal(valeur: object, champ: str, absents: list[str] | None = None) -> Decimal | None:
    """Montant → Decimal. Les dicts `{value, currency_code}` sont dépliés."""
    if isinstance(valeur, dict):
        valeur = valeur.get("value")
    if valeur is None or valeur == "":
        if absents is not None:
            absents.append(champ)
        return None
    try:
        return Decimal(str(valeur))
    except InvalidOperation:
        if absents is not None:
            absents.append(f"{champ} (illisible : {valeur!r})")
        log.warning("en_invoice : montant illisible pour %s → %r", champ, valeur)
        return None


def _date(valeur: object) -> date | None:
    """Date ISO (`2025-06-30`) — le format que rend la plateforme."""
    if not isinstance(valeur, str) or not valeur:
        return None
    try:
        return datetime.strptime(valeur[:10], "%Y-%m-%d").date()
    except ValueError:
        log.warning("en_invoice : date illisible %r", valeur)
        return None


def _partie(donnees: object) -> PartieFacture:
    if not isinstance(donnees, dict):
        return PartieFacture()
    legal = donnees.get("legal_registration_identifier")
    siren = legal.get("value", "") if isinstance(legal, dict) else ""
    # Le SIREN est le préfixe du SIRET : une valeur à 14 chiffres se ramène sans
    # perte, comme dans le lecteur CII.
    chiffres = "".join(c for c in str(siren) if c.isdigit())
    if len(chiffres) == 14:
        chiffres = chiffres[:9]
    adresse = donnees.get("postal_address") or {}
    return PartieFacture(
        nom=donnees.get("name") or "",
        siren=chiffres,
        numero_tva=donnees.get("vat_identifier") or "",
        code_postal=adresse.get("post_code") or adresse.get("postcode") or "",
        ville=adresse.get("city") or adresse.get("city_name") or "",
        pays=adresse.get("country_code") or "",
    )


def _ligne(donnees: dict) -> LigneFacture:
    prix = donnees.get("price_details") or {}
    tva = donnees.get("vat_information") or {}
    article = donnees.get("item_information") or {}
    return LigneFacture(
        numero=str(donnees.get("identifier") or ""),
        designation=article.get("name") or article.get("item_name") or "",
        quantite=_decimal(donnees.get("invoiced_quantity"), "quantite"),
        unite=donnees.get("invoiced_quantity_code") or "",
        prix_unitaire_ht=_decimal(
            prix.get("net_price") or prix.get("item_net_price"), "prix_unitaire"
        ),
        montant_ht=_decimal(donnees.get("net_amount"), "montant_ligne"),
        taux_tva=_decimal(tva.get("vat_rate") or tva.get("rate"), "taux_ligne"),
        categorie_tva=tva.get("vat_category_code") or tva.get("category_code") or "",
    )


def _ventilation(donnees: dict) -> VentilationTva:
    return VentilationTva(
        base_ht=_decimal(donnees.get("vat_category_taxable_amount"), "base"),
        montant_tva=_decimal(donnees.get("vat_category_tax_amount"), "tva"),
        taux=_decimal(donnees.get("vat_category_rate"), "taux"),
        categorie=donnees.get("vat_category_code") or "",
        motif_exoneration=donnees.get("vat_exemption_reason_text") or "",
    )


def lire_en_invoice(charge: dict) -> FactureRecue:
    """`en_invoice` → `FactureRecue`.

    Accepte aussi l'enveloppe complète de `GET /v1.beta/invoices/{id}`, qui porte
    l'`en_invoice` sous cette clé — l'appelant n'a pas à savoir lequel des deux
    il tient.
    """
    if not isinstance(charge, dict):
        raise ErreurLectureEnInvoice(f"Attendu un objet, reçu {type(charge).__name__}.")
    if "en_invoice" in charge and isinstance(charge["en_invoice"], dict):
        charge = charge["en_invoice"]
    if "number" not in charge and "totals" not in charge:
        raise ErreurLectureEnInvoice(
            "Ni 'number' ni 'totals' — ce n'est pas un en_invoice."
        )

    absents: list[str] = []
    totaux = charge.get("totals") or {}

    numero = charge.get("number") or ""
    if not numero:
        absents.append("numero")
    date_facture = _date(charge.get("issue_date"))
    if date_facture is None:
        absents.append("date_facture")

    emetteur = _partie(charge.get("seller"))
    if not emetteur.siren:
        absents.append("siren_emetteur")

    facture = FactureRecue(
        numero=numero,
        date_facture=date_facture,
        type_code=str(charge.get("type_code") or ""),
        devise=charge.get("currency_code") or "EUR",
        profil=(charge.get("process_control") or {}).get("specification_identifier", ""),
        emetteur=emetteur,
        destinataire=_partie(charge.get("buyer")),
        lignes=[_ligne(x) for x in (charge.get("lines") or []) if isinstance(x, dict)],
        ventilation_tva=[
            _ventilation(x)
            for x in (charge.get("vat_break_down") or [])
            if isinstance(x, dict)
        ],
        total_ht=_decimal(totaux.get("total_without_vat"), "total_ht", absents),
        total_tva=_decimal(totaux.get("total_vat_amount"), "total_tva", absents),
        total_ttc=_decimal(totaux.get("total_with_vat"), "total_ttc", absents),
        net_a_payer=_decimal(totaux.get("amount_due_for_payment"), "net_a_payer", absents),
        champs_absents=absents,
    )

    log.info(
        "en_invoice lu : %s du %s — %d ligne(s), TTC=%s, %d champ(s) absent(s)",
        facture.numero or "sans numéro",
        facture.date_facture or "sans date",
        len(facture.lignes),
        facture.total_ttc,
        len(absents),
    )
    return facture
