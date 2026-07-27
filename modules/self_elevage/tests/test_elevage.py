"""Tests du module self_elevage — socle bande / ponte / mouvements / lots."""

from __future__ import annotations

import tempfile
from datetime import date, timedelta

import pytest


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch):
    """Chaque test travaille sur une base neuve et jetable."""
    tmp = tempfile.mkdtemp(prefix="selffarm-elevage-")
    monkeypatch.setenv("SELFFARM_DATA_DIR", tmp)
    for mod in ("self_agri_book.storage", "self_elevage.elevage"):
        import importlib
        import sys
        if mod in sys.modules:
            importlib.reload(sys.modules[mod])
    yield tmp


def _elevage():
    import importlib
    return importlib.import_module("self_elevage.elevage")


def _bande(**kw):
    e = _elevage()
    data = {
        "nom": "Pondeuses 2026",
        "espece": "poule_pondeuse",
        "race": "Marans",
        "effectif_initial": 120,
        "date_mise_en_place": "2026-03-01",
        "mode_elevage": "bio",
    }
    data.update(kw)
    return e.save_bande(data)


# ============================ BANDES ============================

def test_creation_bande():
    b = _bande()
    assert b["id"] > 0
    assert b["nom"] == "Pondeuses 2026"
    assert b["effectif_initial"] == 120
    assert b["statut"] == "active"


def test_bande_nom_obligatoire():
    with pytest.raises(ValueError, match="nom"):
        _bande(nom="")


def test_bande_effectif_doit_etre_positif():
    with pytest.raises(ValueError, match="effectif|Effectif"):
        _bande(effectif_initial=0)


def test_bande_espece_invalide_rejetee():
    with pytest.raises(ValueError, match="espèce"):
        _bande(espece="licorne")


def test_bande_mode_elevage_invalide_rejete():
    with pytest.raises(ValueError, match="mode"):
        _bande(mode_elevage="hors_sol")


def test_mise_a_jour_bande():
    e = _elevage()
    b = _bande()
    b2 = e.save_bande({"id": b["id"], "nom": "Pondeuses renommées",
                       "effectif_initial": 120, "date_mise_en_place": "2026-03-01"})
    assert b2["id"] == b["id"]
    assert b2["nom"] == "Pondeuses renommées"


# ======================== EFFECTIF VIVANT ========================

def test_effectif_vivant_sans_mouvement():
    e = _elevage()
    b = _bande()
    assert e.effectif_vivant(b["id"]) == 120


def test_effectif_vivant_apres_mortalite_et_ajout():
    e = _elevage()
    b = _bande()
    e.add_mouvement({"bande_id": b["id"], "type_mouvement": "mortalite", "nombre": 3})
    e.add_mouvement({"bande_id": b["id"], "type_mouvement": "reforme", "nombre": 5})
    e.add_mouvement({"bande_id": b["id"], "type_mouvement": "ajout", "nombre": 10})
    assert e.effectif_vivant(b["id"]) == 122  # 120 - 3 - 5 + 10


def test_effectif_vivant_jamais_negatif():
    e = _elevage()
    b = _bande(effectif_initial=5)
    e.add_mouvement({"bande_id": b["id"], "type_mouvement": "mortalite", "nombre": 5})
    e.add_mouvement({"bande_id": b["id"], "type_mouvement": "reforme", "nombre": 3})
    assert e.effectif_vivant(b["id"]) == 0


def test_mouvement_type_invalide_rejete():
    e = _elevage()
    b = _bande()
    with pytest.raises(ValueError, match="type"):
        e.add_mouvement({"bande_id": b["id"], "type_mouvement": "evasion", "nombre": 1})


def test_mouvement_bande_inexistante_rejete():
    e = _elevage()
    with pytest.raises(ValueError, match="Bande"):
        e.add_mouvement({"bande_id": 9999, "type_mouvement": "mortalite", "nombre": 1})


# ============================ PONTE ============================

def test_saisie_ponte():
    e = _elevage()
    b = _bande()
    p = e.save_ponte({"bande_id": b["id"], "date_ponte": "2026-07-20", "nb_oeufs": 98})
    assert p["nb_oeufs"] == 98


def test_ponte_meme_jour_corrige_au_lieu_de_dupliquer():
    e = _elevage()
    b = _bande()
    e.save_ponte({"bande_id": b["id"], "date_ponte": "2026-07-20", "nb_oeufs": 98})
    e.save_ponte({"bande_id": b["id"], "date_ponte": "2026-07-20", "nb_oeufs": 104})
    releves = e.list_ponte(bande_id=b["id"])
    assert len(releves) == 1
    assert releves[0]["nb_oeufs"] == 104


def test_ponte_negative_rejetee():
    e = _elevage()
    b = _bande()
    with pytest.raises(ValueError, match="négatives|invalide"):
        e.save_ponte({"bande_id": b["id"], "date_ponte": "2026-07-20", "nb_oeufs": -5})


def test_taux_ponte_sur_effectif_vivant():
    """Le taux doit chuter quand l'effectif baisse, pas rester figé sur l'initial."""
    e = _elevage()
    b = _bande(effectif_initial=100)
    e.save_ponte({"bande_id": b["id"], "date_ponte": "2026-07-20", "nb_oeufs": 80})
    t1 = e.taux_ponte(b["id"])
    assert t1["effectif_vivant"] == 100
    assert t1["taux_ponte_pct"] == 80.0

    e.add_mouvement({"bande_id": b["id"], "type_mouvement": "mortalite", "nombre": 20})
    t2 = e.taux_ponte(b["id"])
    assert t2["effectif_vivant"] == 80
    assert t2["taux_ponte_pct"] == 100.0  # 80 œufs pour 80 poules


def test_taux_ponte_sans_releve_renvoie_none():
    """Aucun relevé ≠ 0 % de ponte — il faut None pour afficher « — »."""
    e = _elevage()
    b = _bande()
    t = e.taux_ponte(b["id"])
    assert t["taux_ponte_pct"] is None
    assert t["moyenne_jour"] is None
    assert t["jours_releves"] == 0


def test_ponte_avec_declasses():
    e = _elevage()
    b = _bande()
    p = e.save_ponte({"bande_id": b["id"], "date_ponte": "2026-07-20",
                      "nb_oeufs": 100, "nb_casses": 3, "nb_declasses": 7})
    assert p["nb_declasses"] == 7


def test_declasses_par_defaut_a_zero():
    """Une saisie qui ignore le champ ne doit pas casser — c'est le cas courant."""
    e = _elevage()
    b = _bande()
    p = e.save_ponte({"bande_id": b["id"], "date_ponte": "2026-07-20", "nb_oeufs": 90})
    assert p["nb_declasses"] == 0


def test_casses_et_declasses_ne_depassent_pas_le_total():
    """nb_oeufs est le TOTAL ramassé : casses et déclassés en sont des sous-ensembles."""
    e = _elevage()
    b = _bande()
    with pytest.raises(ValueError, match="dépassent le total"):
        e.save_ponte({"bande_id": b["id"], "date_ponte": "2026-07-20",
                      "nb_oeufs": 10, "nb_casses": 6, "nb_declasses": 8})


def test_taux_ponte_compte_les_declasses_mais_pas_le_vendable():
    """Un œuf sale a bien été pondu : il compte dans le taux, pas dans le vendable."""
    e = _elevage()
    b = _bande(effectif_initial=100)
    e.save_ponte({"bande_id": b["id"], "date_ponte": "2026-07-20",
                  "nb_oeufs": 80, "nb_casses": 2, "nb_declasses": 8})
    t = e.taux_ponte(b["id"])
    assert t["taux_ponte_pct"] == 80.0        # 80 pondus / 100 poules
    assert t["total_vendables"] == 70          # 80 − 2 − 8
    assert t["taux_vendable_pct"] == 87.5


# ============================ ALIMENT ============================

def test_ajout_livraison_aliment():
    e = _elevage()
    b = _bande()
    a = e.add_aliment({"bande_id": b["id"], "date_livraison": "2026-07-01",
                       "type_aliment": "ponte", "quantite_kg": 500,
                       "prix_total_eur": 320, "fournisseur": "Coop"})
    assert a["quantite_kg"] == 500
    assert a["prix_total_eur"] == 320


def test_aliment_prix_facultatif():
    """On doit pouvoir suivre la conso sans connaître le prix."""
    e = _elevage()
    b = _bande()
    a = e.add_aliment({"bande_id": b["id"], "quantite_kg": 100})
    assert a["prix_total_eur"] is None
    assert e.stats_aliment(b["id"])["total_kg"] == 100


def test_aliment_accepte_la_virgule_decimale():
    """Un clavier français saisit « 12,5 » — pas « 12.5 »."""
    e = _elevage()
    b = _bande()
    a = e.add_aliment({"bande_id": b["id"], "quantite_kg": "12,5", "prix_total_eur": "9,80"})
    assert a["quantite_kg"] == 12.5
    assert a["prix_total_eur"] == 9.8


def test_aliment_quantite_doit_etre_positive():
    e = _elevage()
    b = _bande()
    with pytest.raises(ValueError, match="quantité|Quantité"):
        e.add_aliment({"bande_id": b["id"], "quantite_kg": 0})


def test_aliment_type_invalide_rejete():
    e = _elevage()
    b = _bande()
    with pytest.raises(ValueError, match="aliment"):
        e.add_aliment({"bande_id": b["id"], "quantite_kg": 50, "type_aliment": "granules_magiques"})


def test_stats_aliment_sans_livraison_ne_renvoie_pas_de_none_parasite():
    e = _elevage()
    b = _bande()
    s = e.stats_aliment(b["id"])
    assert s["nb_livraisons"] == 0
    assert s["total_kg"] == 0.0
    assert s["conso_g_jour_poule"] is None


def test_stats_aliment_conso_et_cout_par_oeuf():
    e = _elevage()
    b = _bande(effectif_initial=100)
    depuis = (date.today() - timedelta(days=10)).isoformat()
    e.add_aliment({"bande_id": b["id"], "date_livraison": depuis,
                   "quantite_kg": 120, "prix_total_eur": 60})
    e.save_ponte({"bande_id": b["id"], "date_ponte": date.today().isoformat(), "nb_oeufs": 600})

    s = e.stats_aliment(b["id"])
    assert s["total_kg"] == 120.0
    assert s["total_eur"] == 60.0
    assert s["prix_moyen_kg"] == 0.5
    # 120 kg sur 10 j pour 100 poules → 120 g/poule/jour
    assert s["conso_g_jour_poule"] == 120.0
    assert s["cout_par_oeuf_eur"] == 0.1     # 60 € / 600 œufs


def test_cout_aliment_remonte_dans_le_bandeau():
    e = _elevage()
    b = _bande()
    e.add_aliment({"bande_id": b["id"], "quantite_kg": 50, "prix_total_eur": 40})
    e.add_aliment({"bande_id": b["id"], "quantite_kg": 50, "prix_total_eur": 35})
    assert e.stats_elevage()["cout_aliment_eur"] == 75.0


# ============================ LOTS ============================

def test_creation_lot_calcule_date_limite_21_jours():
    """Le délai réglementaire de la vente directe est de 21 jours, pas 28."""
    e = _elevage()
    b = _bande()
    lot = e.creer_lot({
        "bande_id": b["id"], "date_ponte_debut": "2026-07-01",
        "date_ponte_fin": "2026-07-05", "nb_oeufs": 240,
    })
    assert lot["date_limite"] == "2026-07-26"  # 5 juillet + 21 jours


def test_lot_periode_incoherente_rejetee():
    e = _elevage()
    b = _bande()
    with pytest.raises(ValueError, match="fin de période"):
        e.creer_lot({"bande_id": b["id"], "date_ponte_debut": "2026-07-10",
                     "date_ponte_fin": "2026-07-01", "nb_oeufs": 100})


def test_lot_vide_rejete():
    e = _elevage()
    b = _bande()
    with pytest.raises(ValueError, match="au moins un œuf"):
        e.creer_lot({"bande_id": b["id"], "date_ponte_debut": "2026-07-01",
                     "date_ponte_fin": "2026-07-05", "nb_oeufs": 0})


def test_alerte_lots_a_ecouler():
    e = _elevage()
    b = _bande()
    # Lot ancien : ponte il y a 20 jours → limite dans 1 jour
    vieux = (date.today() - timedelta(days=20)).isoformat()
    e.creer_lot({"bande_id": b["id"], "date_ponte_debut": vieux,
                 "date_ponte_fin": vieux, "nb_oeufs": 60})
    # Lot frais : ponte aujourd'hui → limite dans 21 jours
    e.creer_lot({"bande_id": b["id"], "date_ponte_debut": date.today().isoformat(),
                 "date_ponte_fin": date.today().isoformat(), "nb_oeufs": 90})

    alertes = e.lots_a_ecouler(marge_jours=5)
    assert len(alertes) == 1
    assert alertes[0]["nb_oeufs"] == 60


def test_lot_perime_reste_signale():
    """Un lot dépassé ne disparaît pas de l'alerte — il devient prioritaire."""
    e = _elevage()
    b = _bande()
    tres_vieux = (date.today() - timedelta(days=30)).isoformat()
    e.creer_lot({"bande_id": b["id"], "date_ponte_debut": tres_vieux,
                 "date_ponte_fin": tres_vieux, "nb_oeufs": 40})
    alertes = e.lots_a_ecouler()
    assert len(alertes) == 1
    assert alertes[0]["jours_restants"] < 0


# ============================ STATS ============================

def test_stats_base_vide_sans_none():
    """Aucune donnée ne doit produire None ou NaN dans le bandeau."""
    e = _elevage()
    s = e.stats_elevage()
    assert s["nb_bandes"] == 0
    assert s["effectif_total"] == 0
    assert s["oeufs_7j"] == 0
    assert s["nb_alertes"] == 0


def test_stats_agrege_plusieurs_bandes():
    e = _elevage()
    b1 = _bande(nom="Bande A", effectif_initial=100)
    b2 = _bande(nom="Bande B", effectif_initial=50)
    e.add_mouvement({"bande_id": b1["id"], "type_mouvement": "mortalite", "nombre": 4})
    e.save_ponte({"bande_id": b1["id"], "date_ponte": date.today().isoformat(), "nb_oeufs": 70})
    e.save_ponte({"bande_id": b2["id"], "date_ponte": date.today().isoformat(), "nb_oeufs": 30})

    s = e.stats_elevage()
    assert s["nb_bandes"] == 2
    assert s["effectif_total"] == 146  # (100-4) + 50
    assert s["oeufs_7j"] == 100
