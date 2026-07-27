"""
Tests du catalogue de variétés (data/varietes-references.yaml + catalog.py).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from self_culture.catalog import (
    categories_presentes,
    familles_presentes,
    filter_varietes,
    find_by_id,
    load_catalog,
)
from self_culture.models import (
    CategorieVariete,
    FamilleBotanique,
    Saison,
    Variete,
)


@pytest.fixture(scope="module")
def varietes() -> list[Variete]:
    """Charge le catalogue une fois pour tous les tests du module."""
    return load_catalog()


def test_load_catalog_returns_at_least_30_varietes(varietes):
    """Le catalogue de base doit contenir au moins 30 variétés."""
    assert len(varietes) >= 30, f"Catalogue trop léger : {len(varietes)} variétés"


def test_all_varietes_are_validated_pydantic(varietes):
    """Toutes les variétés du YAML passent la validation Pydantic v2."""
    for v in varietes:
        assert isinstance(v, Variete)
        assert v.id
        assert v.nom_commun
        assert v.nom_botanique
        assert v.famille in FamilleBotanique
        assert v.categorie in CategorieVariete


def test_ids_are_unique(varietes):
    """Aucune collision d'identifiant slug dans le catalogue."""
    ids = [v.id for v in varietes]
    assert len(ids) == len(set(ids)), "Doublons d'id dans le catalogue"


def test_chanvre_kompolti_present(varietes):
    """Le chanvre Kompolti AB, variété de référence du catalogue, est présent."""
    chanvre = find_by_id(varietes, "chanvre-kompolti-ab")
    assert chanvre is not None, "Chanvre Kompolti AB absent du catalogue"
    assert chanvre.famille == FamilleBotanique.CANNABACEAE
    assert chanvre.categorie == CategorieVariete.INDUSTRIEL
    assert "Genscore" in chanvre.fournisseurs_recommandes


def test_engrais_verts_legumineuses_presents(varietes):
    """Au moins 3 légumineuses engrais verts pour la rotation AB."""
    legumineuses_engrais = filter_varietes(
        varietes,
        famille=FamilleBotanique.FABACEAE,
        categorie=CategorieVariete.ENGRAIS_VERT,
    )
    assert len(legumineuses_engrais) >= 3, (
        f"Pas assez de légumineuses engrais verts : {len(legumineuses_engrais)}"
    )


def test_filter_by_famille_solanaceae(varietes):
    """Le filtre par famille Solanaceae renvoie tomate, pdt, aubergine, poivron."""
    solanaceae = filter_varietes(varietes, famille=FamilleBotanique.SOLANACEAE)
    noms = [v.nom_commun.lower() for v in solanaceae]
    assert any("tomate" in n for n in noms)
    assert any("pomme de terre" in n for n in noms)
    assert any("aubergine" in n for n in noms)
    assert any("poivron" in n for n in noms)


def test_filter_by_categorie_aromatique(varietes):
    """Au moins 2 aromatiques (basilic, persil, menthe…)."""
    aromatiques = filter_varietes(varietes, categorie=CategorieVariete.AROMATIQUE)
    assert len(aromatiques) >= 2


def test_filter_by_saison_ete(varietes):
    """Filtre saison été retourne au moins 5 variétés."""
    ete = filter_varietes(varietes, saison=Saison.ETE)
    assert len(ete) >= 5


def test_filter_by_motcle_chou(varietes):
    """Recherche par mot-clé 'chou' renvoie au moins le chou pommé et le brocoli."""
    chous = filter_varietes(varietes, mot_cle="chou")
    assert len(chous) >= 2


def test_calendrier_coherent(varietes):
    """Pour chaque variété, semis_mois_min ≤ semis_mois_max (avec tolérance hivernale)."""
    for v in varietes:
        cal = v.calendrier
        # Cas normal
        if cal.semis_mois_min <= cal.semis_mois_max:
            assert cal.semis_mois_min >= 1 and cal.semis_mois_max <= 12
        # Cas hivernal (ex: fève semis 10→3) : autorisé
        assert 1 <= cal.semis_mois_min <= 12
        assert 1 <= cal.semis_mois_max <= 12
        assert cal.duree_jours_min <= cal.duree_jours_max


def test_rendement_coherent(varietes):
    """Le rendement min ≤ rendement max et densité > 0."""
    for v in varietes:
        r = v.rendement
        assert r.valeur_min_kg_m2 <= r.valeur_max_kg_m2
        assert r.densite_plants_m2 > 0, f"Densité nulle pour {v.id}"


def test_engrais_verts_ont_rendement_zero(varietes):
    """Convention : engrais verts ont rendement 0 (pas récoltés pour vente)."""
    engrais = filter_varietes(varietes, categorie=CategorieVariete.ENGRAIS_VERT)
    assert len(engrais) >= 3
    for ev in engrais:
        assert ev.rendement.valeur_min_kg_m2 == Decimal(0)
        assert ev.rendement.valeur_max_kg_m2 == Decimal(0)


def test_familles_presentes_couvre_au_moins_8_familles(varietes):
    """Diversité botanique : au moins 8 familles différentes pour une rotation correcte."""
    familles = familles_presentes(varietes)
    assert len(familles) >= 8, f"Trop peu de familles botaniques : {len(familles)}"


def test_categories_presentes_couvre_legume_et_engrais_vert(varietes):
    """Le catalogue doit couvrir au moins légume + engrais vert."""
    cats = categories_presentes(varietes)
    assert CategorieVariete.LEGUME in cats
    assert CategorieVariete.ENGRAIS_VERT in cats


def test_find_by_id_inexistant_renvoie_none(varietes):
    """find_by_id renvoie None pour un id absent."""
    assert find_by_id(varietes, "variete-fictive-zzz") is None


def test_filter_combinaison_famille_et_motcle(varietes):
    """Combinaison de filtres : Brassicaceae + 'chou' = au moins 2 variétés."""
    out = filter_varietes(varietes, famille=FamilleBotanique.BRASSICACEAE, mot_cle="chou")
    assert len(out) >= 2


def test_get_varietes_for_datalist(varietes):
    """get_varietes_for_datalist : structure, tri, et slugs cohérents avec le catalogue."""
    from self_culture.cultures import get_varietes_for_datalist

    options = get_varietes_for_datalist()
    assert len(options) == len(varietes)

    # Structure exacte de chaque entrée
    for o in options:
        assert set(o.keys()) == {"value", "label_attr", "slug", "famille", "categorie"}
        assert o["value"] and o["slug"]
        # value = "<emoji> <nom>[ (AB)]" → commence par un caractère non alphanumérique (emoji/•)
        assert not o["value"][0].isalnum()

    # Tri par (categorie, value)
    keys = [(o["categorie"], o["value"]) for o in options]
    assert keys == sorted(keys)

    # Chaque slug correspond à un id réel du catalogue
    ids = {v.id for v in varietes}
    assert all(o["slug"] in ids for o in options)

    # Au moins une variété AB (suffixe " (AB)") présente
    assert any(o["value"].endswith("(AB)") for o in options)
