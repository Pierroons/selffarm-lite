"""Tests du chargeur et filtrage self-aid."""

from __future__ import annotations

from pathlib import Path

from self_aid.loader import filter_aides, load_all, total_enveloppe
from self_aid.models import CategorieAide, FiltreRecherche

DATA_DIR = Path(__file__).parent.parent / "data"


def test_load_all_au_moins_10_aides():
    aides = load_all()
    assert len(aides) >= 10, f"Trop peu d'aides : {len(aides)}"


def test_toutes_aides_ont_source_datee():
    aides = load_all()
    for a in aides:
        assert a.source.date_maj_vu, f"{a.id} sans date_maj_vu"
        assert a.source.url, f"{a.id} sans url"


def test_ids_uniques():
    aides = load_all()
    ids = [a.id for a in aides]
    assert len(set(ids)) == len(ids), "Doublons d'ID dans les aides"


def test_aide_nationale_presente():
    """Les tests ne ciblent que des aides VERSIONNÉES.

    Les aides départementales vivent dans data/local/, hors dépôt : un test
    qui en dépend passe sur le poste de son auteur et échoue partout ailleurs.
    """
    aides = load_all()
    ids = {a.id for a in aides}
    assert "acja-2026" in ids


def test_filter_par_statut_ja_installation():
    aides = load_all()
    f = FiltreRecherche(statut="ja-installation")
    filtered = filter_aides(aides, f)
    # ACJA, exo MSA JA, article 73 B, prêt d'honneur… doivent matcher
    assert len(filtered) >= 3
    ids = {a.id for a in filtered}
    assert "acja-2026" in ids


def test_filter_par_categorie_credit_impot():
    aides = load_all()
    f = FiltreRecherche(categorie=CategorieAide.CREDIT_IMPOT)
    filtered = filter_aides(aides, f)
    ids = {a.id for a in filtered}
    assert "ci-ab-2026" in ids
    assert "ci-hve-2026" in ids


def test_filter_par_zone_nationale():
    aides = load_all()
    f = FiltreRecherche(zone="France")
    filtered = filter_aides(aides, f)
    assert len(filtered) > 0
    for a in filtered:
        assert any("france" in z.lower() or "na" in z.lower() or "ue" in z.lower()
                   for z in a.zones_applicables)


def test_filter_mot_cle_chanvre():
    aides = load_all()
    f = FiltreRecherche(mot_cle="chanvre")
    filtered = filter_aides(aides, f)
    ids = {a.id for a in filtered}
    assert "chanvre-couple-2026" in ids


def test_cumul_declare_mutuellement():
    """Un cumul déclaré d'un côté doit l'être de l'autre.

    Paire choisie parmi les aides versionnées : ACJA et l'écorégime bio.
    """
    aides = load_all()
    acja = next(a for a in aides if a.id == "acja-2026")
    eco = next(a for a in aides if a.id == "ecoregime-bio-2026")
    assert "ecoregime-bio-2026" in acja.cumul_possible_avec
    assert "acja-2026" in eco.cumul_possible_avec


def test_total_enveloppe_coherente():
    aides = load_all()
    mn, mx = total_enveloppe(aides)
    assert mn > 0
    assert mx > mn
    # Sanity check : DNJA seul fait 15k-34,5k, donc mx >> 30 000
    assert mx > 30000


def test_dep_exclut_micro_ba():
    """DEP ne s'applique pas en micro-BA (BOFiP)."""
    aides = load_all()
    dep = next(a for a in aides if a.id == "dep-73-cgi-2026")
    assert "regime-micro-ba" in dep.exclut


def test_montant_min_le_max():
    aides = load_all()
    for a in aides:
        assert a.montant.valeur_min <= a.montant.valeur_max, \
            f"{a.id} : min > max"


def test_filter_vide_renvoie_tout():
    aides = load_all()
    f = FiltreRecherche()  # aucun filtre
    assert len(filter_aides(aides, f)) == len(aides)
