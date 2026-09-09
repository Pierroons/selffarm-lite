"""Tests de l'adaptateur en_invoice — la facture décodée par la plateforme.

La structure des fixtures reproduit celle relevée sur l'API Super PDP en sandbox
le 9 septembre 2026 (cf. README du module). Les données sont du jeu canonique :
aucun identifiant de compte réel n'entre dans le dépôt.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from self_pa.en_invoice import ErreurLectureEnInvoice, lire_en_invoice


def en_invoice(
    *,
    numero="FA-2026-0142",
    siren="552100554",
    ttc="1200.00",
    avec_lignes=True,
) -> dict:
    return {
        "number": numero,
        "issue_date": "2026-09-03",
        "type_code": "380",
        "currency_code": "EUR",
        "payment_due_date": "2026-10-03",
        "process_control": {
            "business_process_type": "M1",
            "specification_identifier": "urn:cen.eu:en16931:2017",
        },
        "seller": {
            "name": "Outillage Pro Distribution",
            "legal_registration_identifier": {"value": siren, "scheme": "0002"},
            "vat_identifier": "FR12552100554",
            "electronic_address": {"value": f"{siren}_1", "scheme": "0225"},
            "postal_address": {"post_code": "87000", "city": "Limoges",
                               "country_code": "FR"},
        },
        "buyer": {
            "name": "Client Test",
            "legal_registration_identifier": {"value": "999999999", "scheme": "0002"},
        },
        "totals": {
            "sum_invoice_lines_amount": "1000.00",
            "total_without_vat": "1000.00",
            # Seul montant emballé dans un objet, comme le fait la plateforme.
            "total_vat_amount": {"value": "200.00", "currency_code": "EUR"},
            "total_with_vat": ttc,
            "amount_due_for_payment": ttc,
        },
        "vat_break_down": [
            {
                "vat_category_taxable_amount": "1000.00",
                "vat_category_tax_amount": "200.00",
                "vat_category_code": "S",
                "vat_identifier": "VAT",
                "vat_category_rate": "20.00",
            }
        ],
        "lines": [
            {
                "identifier": "001",
                "invoiced_quantity": "4.0000",
                "invoiced_quantity_code": "C62",
                "net_amount": "1000.00",
                "price_details": {"net_price": "250.00"},
                "vat_information": {"vat_category_code": "S", "vat_rate": "20.00"},
                "item_information": {"name": "Perceuse à percussion 18V"},
            }
        ]
        if avec_lignes
        else [],
    }


# ---------------- lecture nominale ----------------

def test_lit_les_champs_dentete():
    f = lire_en_invoice(en_invoice())

    assert f.numero == "FA-2026-0142"
    assert f.date_facture == date(2026, 9, 3)
    assert f.type_code == "380"
    assert f.devise == "EUR"
    assert f.profil == "urn:cen.eu:en16931:2017"
    assert f.champs_absents == []


def test_montants_en_decimal_exact():
    f = lire_en_invoice(en_invoice())

    assert f.total_ht == Decimal("1000.00")
    assert f.total_ttc == Decimal("1200.00")
    assert isinstance(f.total_ttc, Decimal)


def test_total_tva_emballe_dans_un_objet_est_deplie():
    """`total_vat_amount` est le seul montant que la plateforme rend sous forme
    d'objet `{value, currency_code}` — l'oublier donnerait une TVA absente sur
    toutes les factures."""
    f = lire_en_invoice(en_invoice())

    assert f.total_tva == Decimal("200.00")


def test_siren_lu_dans_legal_registration_identifier():
    f = lire_en_invoice(en_invoice())

    assert f.emetteur.siren == "552100554"
    assert f.emetteur.nom == "Outillage Pro Distribution"
    assert f.emetteur.numero_tva == "FR12552100554"
    assert f.emetteur.ville == "Limoges"


def test_lit_lignes_et_ventilation():
    f = lire_en_invoice(en_invoice())

    assert len(f.lignes) == 1
    assert f.lignes[0].designation == "Perceuse à percussion 18V"
    assert f.lignes[0].unite == "C62"
    assert f.lignes[0].montant_ht == Decimal("1000.00")
    assert f.lignes[0].taux_tva == Decimal("20.00")

    assert len(f.ventilation_tva) == 1
    assert f.ventilation_tva[0].montant_tva == Decimal("200.00")


def test_accepte_lenveloppe_complete_de_lapi():
    """`GET /v1.beta/invoices/{id}` rend l'en_invoice sous une clé ; l'appelant
    n'a pas à savoir lequel des deux niveaux il tient."""
    enveloppe = {
        "id": 84385,
        "direction": "in",
        "created_at": "2026-09-03T10:00:00Z",
        "en_invoice": en_invoice(),
        "events": [{"status_code": "fr:202", "status_text": "Reçue par la plateforme"}],
    }
    f = lire_en_invoice(enveloppe)

    assert f.numero == "FA-2026-0142"
    assert f.total_ttc == Decimal("1200.00")


# ---------------- tolérance et signalement ----------------

def test_facture_sans_lignes_reste_lisible():
    f = lire_en_invoice(en_invoice(avec_lignes=False))

    assert f.lignes == []
    assert f.total_ttc == Decimal("1200.00")
    assert f.champs_absents == []


def test_siret_a_14_chiffres_se_ramene_au_siren():
    f = lire_en_invoice(en_invoice(siren="55210055400024"))

    assert f.emetteur.siren == "552100554"


def test_total_absent_est_trace():
    charge = en_invoice()
    del charge["totals"]["total_with_vat"]
    f = lire_en_invoice(charge)

    assert f.total_ttc is None
    assert "total_ttc" in f.champs_absents


def test_montant_illisible_nest_pas_devine():
    charge = en_invoice()
    charge["totals"]["total_with_vat"] = "1 200,00"
    f = lire_en_invoice(charge)

    assert f.total_ttc is None
    assert any("total_ttc" in c and "1 200,00" in c for c in f.champs_absents)


def test_nombre_json_nu_reste_exact():
    """La plateforme rend des chaînes aujourd'hui. Si elle passait un jour à des
    nombres JSON, la conversion doit rester exacte au centime plutôt que de
    traîner une erreur de représentation binaire jusque dans une écriture."""
    charge = en_invoice()
    charge["totals"]["total_with_vat"] = 1200.10
    f = lire_en_invoice(charge)

    assert f.total_ttc == Decimal("1200.10")


def test_charge_qui_nest_pas_une_facture_est_refusee():
    with pytest.raises(ErreurLectureEnInvoice):
        lire_en_invoice({"foo": "bar"})

    with pytest.raises(ErreurLectureEnInvoice):
        lire_en_invoice(["pas", "un", "objet"])  # type: ignore[arg-type]


# ---------------- contrôle croisé entre les deux chemins ----------------

def test_les_deux_lecteurs_produisent_la_meme_cle_metier():
    """Le XML embarqué et l'en_invoice décrivent la même facture. Leurs lectures
    doivent converger — c'est ce qui rend le contrôle croisé possible, et ce qui
    garantit qu'une facture reçue deux fois par deux canaux ne fera qu'une
    écriture."""
    from self_pa.cii_reader import lire_cii
    from self_pa.tests.test_cii_reader import facture_xml

    par_json = lire_en_invoice(en_invoice())
    par_xml = lire_cii(facture_xml())

    assert par_json.cle_metier == par_xml.cle_metier
    assert par_json.total_ht == par_xml.total_ht
    assert par_json.total_tva == par_xml.total_tva
    assert par_json.total_ttc == par_xml.total_ttc
    assert par_json.date_facture == par_xml.date_facture
    assert par_json.emetteur.siren == par_xml.emetteur.siren
