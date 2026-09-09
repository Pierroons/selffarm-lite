"""Tests du lecteur CII — self_pa.cii_reader."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from self_pa.cii_reader import ErreurLectureCII, lire_cii

EN_TETE = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<rsm:CrossIndustryInvoice'
    ' xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"'
    ' xmlns:ram="urn:un:unece:uncefact:data:standard:'
    'ReusableAggregateBusinessInformationEntity:100"'
    ' xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100">'
)


def facture_xml(
    *,
    numero: str = "FA-2026-0142",
    siren_vendeur: str = "552100554",
    montant_ttc: str = "1200.00",
    avec_lignes: bool = True,
    identifiant_legal: bool = True,
) -> bytes:
    """Un CII de fournisseur d'outillage, paramétrable pour chaque cas."""
    legal = (
        f'<ram:SpecifiedLegalOrganization><ram:ID schemeID="0002">'
        f"{siren_vendeur}</ram:ID></ram:SpecifiedLegalOrganization>"
        if identifiant_legal
        else ""
    )
    lignes = (
        "<ram:IncludedSupplyChainTradeLineItem>"
        "<ram:AssociatedDocumentLineDocument><ram:LineID>1</ram:LineID>"
        "</ram:AssociatedDocumentLineDocument>"
        "<ram:SpecifiedTradeProduct><ram:Name>Perceuse à percussion 18V</ram:Name>"
        "</ram:SpecifiedTradeProduct>"
        "<ram:SpecifiedLineTradeAgreement><ram:NetPriceProductTradePrice>"
        "<ram:ChargeAmount>250.00</ram:ChargeAmount>"
        "</ram:NetPriceProductTradePrice></ram:SpecifiedLineTradeAgreement>"
        '<ram:SpecifiedLineTradeDelivery><ram:BilledQuantity unitCode="C62">4'
        "</ram:BilledQuantity></ram:SpecifiedLineTradeDelivery>"
        "<ram:SpecifiedLineTradeSettlement><ram:ApplicableTradeTax>"
        "<ram:CategoryCode>S</ram:CategoryCode>"
        "<ram:RateApplicablePercent>20.00</ram:RateApplicablePercent>"
        "</ram:ApplicableTradeTax>"
        "<ram:SpecifiedTradeSettlementLineMonetarySummation>"
        "<ram:LineTotalAmount>1000.00</ram:LineTotalAmount>"
        "</ram:SpecifiedTradeSettlementLineMonetarySummation>"
        "</ram:SpecifiedLineTradeSettlement>"
        "</ram:IncludedSupplyChainTradeLineItem>"
        if avec_lignes
        else ""
    )
    return (
        EN_TETE
        + "<rsm:ExchangedDocumentContext>"
        "<ram:GuidelineSpecifiedDocumentContextParameter>"
        "<ram:ID>urn:cen.eu:en16931:2017</ram:ID>"
        "</ram:GuidelineSpecifiedDocumentContextParameter>"
        "</rsm:ExchangedDocumentContext>"
        f"<rsm:ExchangedDocument><ram:ID>{numero}</ram:ID>"
        "<ram:TypeCode>380</ram:TypeCode>"
        '<ram:IssueDateTime><udt:DateTimeString format="102">20260903'
        "</udt:DateTimeString></ram:IssueDateTime>"
        "</rsm:ExchangedDocument>"
        "<rsm:SupplyChainTradeTransaction>"
        f"{lignes}"
        "<ram:ApplicableHeaderTradeAgreement>"
        "<ram:SellerTradeParty>"
        f'<ram:GlobalID schemeID="0002">{siren_vendeur}</ram:GlobalID>'
        "<ram:Name>Outillage Pro Distribution</ram:Name>"
        f"{legal}"
        "<ram:PostalTradeAddress><ram:PostcodeCode>87000</ram:PostcodeCode>"
        "<ram:CityName>Limoges</ram:CityName>"
        "<ram:CountryID>FR</ram:CountryID></ram:PostalTradeAddress>"
        '<ram:SpecifiedTaxRegistration><ram:ID schemeID="VA">FR12552100554'
        "</ram:ID></ram:SpecifiedTaxRegistration>"
        "</ram:SellerTradeParty>"
        "<ram:BuyerTradeParty><ram:Name>Client Test</ram:Name>"
        "</ram:BuyerTradeParty>"
        "</ram:ApplicableHeaderTradeAgreement>"
        "<ram:ApplicableHeaderTradeSettlement>"
        "<ram:InvoiceCurrencyCode>EUR</ram:InvoiceCurrencyCode>"
        "<ram:ApplicableTradeTax>"
        "<ram:CalculatedAmount>200.00</ram:CalculatedAmount>"
        "<ram:TypeCode>VAT</ram:TypeCode>"
        "<ram:BasisAmount>1000.00</ram:BasisAmount>"
        "<ram:CategoryCode>S</ram:CategoryCode>"
        "<ram:RateApplicablePercent>20.00</ram:RateApplicablePercent>"
        "</ram:ApplicableTradeTax>"
        "<ram:SpecifiedTradeSettlementHeaderMonetarySummation>"
        "<ram:LineTotalAmount>1000.00</ram:LineTotalAmount>"
        "<ram:TaxBasisTotalAmount>1000.00</ram:TaxBasisTotalAmount>"
        '<ram:TaxTotalAmount currencyID="EUR">200.00</ram:TaxTotalAmount>'
        f"<ram:GrandTotalAmount>{montant_ttc}</ram:GrandTotalAmount>"
        f"<ram:DuePayableAmount>{montant_ttc}</ram:DuePayableAmount>"
        "</ram:SpecifiedTradeSettlementHeaderMonetarySummation>"
        "</ram:ApplicableHeaderTradeSettlement>"
        "</rsm:SupplyChainTradeTransaction>"
        "</rsm:CrossIndustryInvoice>"
    ).encode("utf-8")


# ---------------- lecture nominale ----------------

def test_lit_une_facture_complete():
    f = lire_cii(facture_xml())

    assert f.numero == "FA-2026-0142"
    assert f.date_facture == date(2026, 9, 3)
    assert f.type_code == "380"
    assert f.devise == "EUR"
    assert f.profil == "urn:cen.eu:en16931:2017"
    assert f.champs_absents == []


def test_lit_les_montants_en_decimal_exact():
    f = lire_cii(facture_xml())

    # Decimal et non float : 0.1 + 0.2 != 0.3 n'a pas sa place en comptabilité.
    assert f.total_ht == Decimal("1000.00")
    assert f.total_tva == Decimal("200.00")
    assert f.total_ttc == Decimal("1200.00")
    assert isinstance(f.total_ttc, Decimal)


def test_lit_emetteur_et_ventilation():
    f = lire_cii(facture_xml())

    assert f.emetteur.nom == "Outillage Pro Distribution"
    assert f.emetteur.siren == "552100554"
    assert f.emetteur.numero_tva == "FR12552100554"
    assert f.emetteur.ville == "Limoges"

    assert len(f.ventilation_tva) == 1
    assert f.ventilation_tva[0].taux == Decimal("20.00")
    assert f.ventilation_tva[0].montant_tva == Decimal("200.00")


def test_lit_les_lignes_avec_unite():
    f = lire_cii(facture_xml())

    assert len(f.lignes) == 1
    ligne = f.lignes[0]
    assert ligne.designation == "Perceuse à percussion 18V"
    assert ligne.quantite == Decimal(4)
    assert ligne.unite == "C62"
    assert ligne.montant_ht == Decimal("1000.00")
    assert ligne.taux_tva == Decimal("20.00")


# ---------------- tolérance : ce qui ne doit PAS casser ----------------

def test_profil_sans_lignes_reste_lisible():
    """En profil MINIMUM, une facture n'a aucune ligne de détail. Elle est
    valide, et les totaux suffisent à produire l'écriture."""
    f = lire_cii(facture_xml(avec_lignes=False))

    assert f.lignes == []
    assert f.total_ttc == Decimal("1200.00")
    assert f.champs_absents == []


def test_siret_a_14_chiffres_se_ramene_au_siren():
    """Certains émetteurs déposent le SIRET dans GlobalID. Le SIREN en est le
    préfixe : la troncature est exacte, pas une approximation."""
    f = lire_cii(facture_xml(siren_vendeur="55210055400024", identifiant_legal=False))

    assert f.emetteur.siren == "552100554"


def test_identifiant_legal_prime_sur_global_id():
    """BT-30 est SpecifiedLegalOrganization/ID. GlobalID n'est qu'un repli."""
    xml = facture_xml().replace(
        b'<ram:GlobalID schemeID="0002">552100554</ram:GlobalID>',
        b'<ram:GlobalID schemeID="0002">99999999900011</ram:GlobalID>',
    )
    f = lire_cii(xml)

    assert f.emetteur.siren == "552100554"


# ---------------- ce que le lecteur doit SIGNALER ----------------

def test_montant_illisible_nest_jamais_devine():
    """Le point crucial : `1 200,00` n'est pas du CII. Le lire comme 1200.00
    reviendrait à inventer une valeur comptable à partir d'un XML malformé.
    Le champ doit remonter à l'humain, avec sa valeur brute."""
    xml = facture_xml().replace(
        b"<ram:GrandTotalAmount>1200.00</ram:GrandTotalAmount>",
        b"<ram:GrandTotalAmount>1 200,00</ram:GrandTotalAmount>",
    )
    f = lire_cii(xml)

    assert f.total_ttc is None
    assert any("total_ttc" in c and "1 200,00" in c for c in f.champs_absents)


def test_totaux_absents_sont_traces():
    xml = facture_xml().replace(
        b"<ram:GrandTotalAmount>1200.00</ram:GrandTotalAmount>", b""
    )
    f = lire_cii(xml)

    assert f.total_ttc is None
    assert "total_ttc" in f.champs_absents


def test_siren_emetteur_absent_est_trace():
    xml = facture_xml(identifiant_legal=False).replace(
        b'<ram:GlobalID schemeID="0002">552100554</ram:GlobalID>', b""
    )
    f = lire_cii(xml)

    assert f.emetteur.siren == ""
    assert "siren_emetteur" in f.champs_absents


def test_date_dans_un_format_non_gere_ne_produit_pas_de_date_fausse():
    """Le code de format est vérifié, pas supposé : une date lue avec le mauvais
    format donnerait un jour faux plutôt qu'une absence."""
    xml = facture_xml().replace(b'format="102"', b'format="203"')
    f = lire_cii(xml)

    assert f.date_facture is None
    assert "date_facture" in f.champs_absents


# ---------------- refus explicites ----------------

def test_xml_invalide_leve_une_erreur():
    with pytest.raises(ErreurLectureCII):
        lire_cii(b"<pas-du-xml")


def test_ubl_est_refuse_explicitement():
    """Super PDP accepte aussi l'UBL. Ce module ne le lit pas — il doit le dire,
    pas rendre une facture vide qui passerait pour une lecture réussie."""
    ubl = (
        b'<?xml version="1.0"?>'
        b'<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2">'
        b"<ID>FA-2026-0142</ID></Invoice>"
    )
    with pytest.raises(ErreurLectureCII, match="UBL"):
        lire_cii(ubl)


# ---------------- la clé de déduplication ----------------

def test_meme_facture_par_deux_canaux_donne_la_meme_cle():
    """Le cœur du dispositif anti-doublon. Pendant la transition, la même facture
    arrive par mail ET par la plateforme : deux fichiers, deux empreintes. Si la
    clé changeait, l'écriture serait passée deux fois — double comptabilisation
    et double déduction de TVA (guide DGFiP, questions 5 et 15)."""
    par_plateforme = lire_cii(facture_xml())
    # Même facture, XML régénéré différemment par un autre outil : les lignes de
    # détail ont sauté, le fichier n'a plus rien à voir octet pour octet.
    par_mail = lire_cii(facture_xml(avec_lignes=False))

    assert par_plateforme.cle_metier == par_mail.cle_metier == "552100554:FA-2026-0142"


def test_deux_factures_distinctes_ont_des_cles_distinctes():
    a = lire_cii(facture_xml(numero="FA-2026-0142"))
    b = lire_cii(facture_xml(numero="FA-2026-0143"))

    assert a.cle_metier != b.cle_metier
