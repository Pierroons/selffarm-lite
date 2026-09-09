"""
Lecture d'une facture au format CII (Cross Industry Invoice) — le cœur Factur-X.

Ce module fait l'inverse du builder de SelfInvoice : les mêmes chemins XML, lus
au lieu d'être écrits. C'est ce qui remplace le parsing par IA, et c'est pour ça
qu'il existe — une facture structurée porte ses montants dans des balises, il n'y
a rien à deviner.

Deux règles gouvernent le code :

**On lit un XML écrit par un tiers.** Chaque champ est cherché par son nom
qualifié, jamais par sa position, et son absence est notée dans `champs_absents`
plutôt que levée en exception. Un profil MINIMUM n'a aucune ligne de détail ; le
rejeter serait rejeter une facture valide.

**Un montant illisible n'est jamais deviné.** `1234,56` n'est pas du CII (la
norme impose le point décimal), et l'interpréter reviendrait à inventer une
valeur comptable. Le champ part alors dans `champs_absents` avec sa valeur brute,
et remonte à l'humain.

Limite assumée : ce lecteur lit le CII. Super PDP accepte aussi l'UBL et le
Peppol BIS ; leur lecture est un autre module, à écrire si le besoin se présente.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree as ET

from self_pa.models import (
    FactureRecue,
    LigneFacture,
    PartieFacture,
    VentilationTva,
)

log = logging.getLogger("selffarm.self_pa.cii")

# Namespaces CII. Identiques dans tous les profils Factur-X et chez tous les
# émetteurs : ils viennent de la norme UN/CEFACT, pas du logiciel qui écrit.
NS = {
    "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    "ram": "urn:un:unece:uncefact:data:standard:"
           "ReusableAggregateBusinessInformationEntity:100",
    "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
}

# Format des dates CII : "102" = YYYYMMDD. Les autres codes existent dans la
# norme mais aucun profil Factur-X ne les emploie pour BT-2.
_FORMAT_DATE_AAAAMMJJ = "102"


class ErreurLectureCII(ValueError):
    """Le document n'est pas un CII exploitable (XML invalide, racine inconnue)."""


def _texte(noeud: ET.Element | None, chemin: str) -> str:
    """Texte d'un sous-nœud, chaîne vide s'il manque. Jamais d'exception."""
    if noeud is None:
        return ""
    trouve = noeud.find(chemin, NS)
    if trouve is None or trouve.text is None:
        return ""
    return trouve.text.strip()


def _decimal(
    noeud: ET.Element | None, chemin: str, champ: str, absents: list[str]
) -> Decimal | None:
    """Montant décimal, ou None + trace dans `absents`.

    Un champ vide et un champ illisible se distinguent : le premier est noté par
    son nom seul, le second garde sa valeur brute pour que l'humain voie ce que
    le fournisseur a écrit.
    """
    brut = _texte(noeud, chemin)
    if not brut:
        absents.append(champ)
        return None
    try:
        return Decimal(brut)
    except InvalidOperation:
        absents.append(f"{champ} (illisible : {brut!r})")
        log.warning("CII : montant illisible pour %s → %r", champ, brut)
        return None


def _date(noeud: ET.Element | None, chemin: str) -> date | None:
    """Date CII au format 102 (YYYYMMDD).

    Le code de format est porté par l'attribut `format` du DateTimeString. On le
    vérifie au lieu de le supposer : un émetteur qui daterait autrement produirait
    sinon une date fausse plutôt qu'une date absente.
    """
    if noeud is None:
        return None
    el = noeud.find(chemin, NS)
    if el is None or not el.text:
        return None
    brut = el.text.strip()
    fmt = el.get("format", _FORMAT_DATE_AAAAMMJJ)
    if fmt != _FORMAT_DATE_AAAAMMJJ:
        log.warning("CII : format de date %r non géré (valeur %r)", fmt, brut)
        return None
    try:
        return datetime.strptime(brut, "%Y%m%d").date()
    except ValueError:
        log.warning("CII : date illisible %r", brut)
        return None


def _siren(party: ET.Element) -> str:
    """SIREN de la partie (BT-30).

    Deux emplacements le portent et ils ne se valent pas :
    `SpecifiedLegalOrganization/ID` EST le BT-30, tandis que `GlobalID` est un
    identifiant d'entreprise générique où certains émetteurs déposent le SIRET.
    D'où l'ordre, et la troncature : le SIREN est les 9 premiers chiffres du
    SIRET, donc un identifiant à 14 chiffres se ramène sans perte.
    """
    valeur = _texte(party, "ram:SpecifiedLegalOrganization/ram:ID")
    if not valeur:
        valeur = _texte(party, "ram:GlobalID")
    chiffres = "".join(c for c in valeur if c.isdigit())
    if len(chiffres) == 14:
        return chiffres[:9]
    return chiffres


def _partie(parent: ET.Element | None, chemin: str) -> PartieFacture:
    """Émetteur ou destinataire — jamais None, au pire vide."""
    if parent is None:
        return PartieFacture()
    party = parent.find(chemin, NS)
    if party is None:
        return PartieFacture()
    return PartieFacture(
        nom=_texte(party, "ram:Name"),
        siren=_siren(party),
        numero_tva=_texte(party, "ram:SpecifiedTaxRegistration/ram:ID"),
        code_postal=_texte(party, "ram:PostalTradeAddress/ram:PostcodeCode"),
        ville=_texte(party, "ram:PostalTradeAddress/ram:CityName"),
        pays=_texte(party, "ram:PostalTradeAddress/ram:CountryID"),
    )


def _ligne(item: ET.Element) -> LigneFacture:
    """Une ligne de détail. Les montants manquants restent à None, sans trace :
    une ligne incomplète n'invalide pas la facture, seuls les totaux comptent
    pour l'écriture."""
    perdu: list[str] = []
    quantite_el = item.find("ram:SpecifiedLineTradeDelivery/ram:BilledQuantity", NS)
    return LigneFacture(
        numero=_texte(item, "ram:AssociatedDocumentLineDocument/ram:LineID"),
        designation=_texte(item, "ram:SpecifiedTradeProduct/ram:Name"),
        quantite=_decimal(
            item, "ram:SpecifiedLineTradeDelivery/ram:BilledQuantity", "quantite", perdu
        ),
        unite=quantite_el.get("unitCode", "") if quantite_el is not None else "",
        prix_unitaire_ht=_decimal(
            item,
            "ram:SpecifiedLineTradeAgreement/ram:NetPriceProductTradePrice/ram:ChargeAmount",
            "prix_unitaire",
            perdu,
        ),
        montant_ht=_decimal(
            item,
            "ram:SpecifiedLineTradeSettlement/"
            "ram:SpecifiedTradeSettlementLineMonetarySummation/ram:LineTotalAmount",
            "montant_ligne",
            perdu,
        ),
        taux_tva=_decimal(
            item,
            "ram:SpecifiedLineTradeSettlement/ram:ApplicableTradeTax/"
            "ram:RateApplicablePercent",
            "taux_ligne",
            perdu,
        ),
        categorie_tva=_texte(
            item,
            "ram:SpecifiedLineTradeSettlement/ram:ApplicableTradeTax/ram:CategoryCode",
        ),
    )


def _ventilation(tax: ET.Element) -> VentilationTva:
    perdu: list[str] = []
    return VentilationTva(
        base_ht=_decimal(tax, "ram:BasisAmount", "base", perdu),
        montant_tva=_decimal(tax, "ram:CalculatedAmount", "tva", perdu),
        taux=_decimal(tax, "ram:RateApplicablePercent", "taux", perdu),
        categorie=_texte(tax, "ram:CategoryCode"),
        motif_exoneration=_texte(tax, "ram:ExemptionReason"),
    )


def lire_cii(xml: bytes | str) -> FactureRecue:
    """XML CII → `FactureRecue`.

    Lève `ErreurLectureCII` si le document n'est pas un CII — c'est le seul cas
    où la lecture échoue plutôt que de signaler. Tout le reste part dans
    `champs_absents`.
    """
    try:
        racine = ET.fromstring(xml if isinstance(xml, bytes) else xml.encode("utf-8"))
    except ET.ParseError as e:
        raise ErreurLectureCII(f"XML invalide : {e}") from e

    attendue = f"{{{NS['rsm']}}}CrossIndustryInvoice"
    if racine.tag != attendue:
        raise ErreurLectureCII(
            f"Racine {racine.tag!r} — attendu un CrossIndustryInvoice. "
            "UBL et Peppol BIS ne sont pas lus par ce module."
        )

    absents: list[str] = []

    doc = racine.find("rsm:ExchangedDocument", NS)
    transaction = racine.find("rsm:SupplyChainTradeTransaction", NS)
    accord = (
        transaction.find("ram:ApplicableHeaderTradeAgreement", NS)
        if transaction is not None
        else None
    )
    reglement = (
        transaction.find("ram:ApplicableHeaderTradeSettlement", NS)
        if transaction is not None
        else None
    )
    totaux = (
        reglement.find(
            "ram:SpecifiedTradeSettlementHeaderMonetarySummation", NS
        )
        if reglement is not None
        else None
    )

    numero = _texte(doc, "ram:ID")
    if not numero:
        absents.append("numero")
    date_facture = _date(doc, "ram:IssueDateTime/udt:DateTimeString")
    if date_facture is None:
        absents.append("date_facture")

    emetteur = _partie(accord, "ram:SellerTradeParty")
    if not emetteur.siren:
        absents.append("siren_emetteur")

    facture = FactureRecue(
        numero=numero,
        date_facture=date_facture,
        type_code=_texte(doc, "ram:TypeCode"),
        devise=_texte(reglement, "ram:InvoiceCurrencyCode") or "EUR",
        profil=_texte(
            racine,
            "rsm:ExchangedDocumentContext/"
            "ram:GuidelineSpecifiedDocumentContextParameter/ram:ID",
        ),
        emetteur=emetteur,
        destinataire=_partie(accord, "ram:BuyerTradeParty"),
        lignes=[
            _ligne(item)
            for item in (
                transaction.findall("ram:IncludedSupplyChainTradeLineItem", NS)
                if transaction is not None
                else []
            )
        ],
        ventilation_tva=[
            _ventilation(tax)
            for tax in (
                reglement.findall("ram:ApplicableTradeTax", NS)
                if reglement is not None
                else []
            )
        ],
        total_ht=_decimal(totaux, "ram:TaxBasisTotalAmount", "total_ht", absents),
        total_tva=_decimal(totaux, "ram:TaxTotalAmount", "total_tva", absents),
        total_ttc=_decimal(totaux, "ram:GrandTotalAmount", "total_ttc", absents),
        net_a_payer=_decimal(totaux, "ram:DuePayableAmount", "net_a_payer", absents),
        champs_absents=absents,
    )

    log.info(
        "CII lu : %s du %s — %s lignes, TTC=%s, %d champ(s) absent(s)",
        facture.numero or "sans numéro",
        facture.date_facture or "sans date",
        len(facture.lignes),
        facture.total_ttc,
        len(absents),
    )
    return facture
