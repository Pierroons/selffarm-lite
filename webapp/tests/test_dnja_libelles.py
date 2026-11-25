"""Les libellés des scénarios DNJA vivent hors du dépôt.

Ce qui est éprouvé ici n'est pas un affichage, c'est une frontière. Le libellé
d'un scénario nominatif décrit une exploitation réelle — sa filière, l'état de
son dossier d'installation. Aucun de ces libellés n'est reproduit dans ce
fichier : un test qui énumère ce qu'il interdit le publie. Deux propriétés
doivent tenir ensemble, et la seconde est celle qu'on oublie :

1. le dépôt public ne nomme aucun scénario privé, ni par son slug ni par son
   libellé ;
2. l'application reste utilisable **sans** le fichier local — c'est l'état de
   toute installation qui n'est pas celle de son auteur, donc le cas normal.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from webapp.routes import dnja as route_dnja

# Deux slugs factices, qui portent les motifs réservés sans reprendre le nom
# d'un scénario réel : le test éprouve le filtre, pas un fichier particulier.
PRIVES = ("hypotheses-pierroons-a", "hypotheses-perso-b")
PUBLIC = "hypotheses-demo-publique"


@pytest.fixture
def examples(tmp_path, monkeypatch):
    """Un dossier examples/ jetable : un scénario public, deux privés, pas de fichier local."""
    for slug in (PUBLIC, *PRIVES):
        (tmp_path / f"{slug}.yaml").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(route_dnja, "EXAMPLES_DIR", tmp_path)
    monkeypatch.setattr(route_dnja, "_LIBELLES_LOCAUX", tmp_path / "libelles.local.json")
    monkeypatch.delenv("SELFFARM_ENV", raising=False)
    return tmp_path


def _ecrire_local(dossier: Path, contenu) -> None:
    chemin = dossier / "libelles.local.json"
    chemin.write_text(contenu if isinstance(contenu, str) else json.dumps(contenu), encoding="utf-8")


def test_hors_machine_perso_seule_la_demo_est_listee(examples):
    listes = route_dnja._list_examples()
    assert [e["slug"] for e in listes] == [PUBLIC]
    assert listes[0]["label"] == "Démo publique 🌻"


def test_sans_fichier_local_un_scenario_prive_porte_son_slug(examples, monkeypatch):
    monkeypatch.setenv("SELFFARM_ENV", "perso")
    par_slug = {e["slug"]: e for e in route_dnja._list_examples()}
    assert set(par_slug) == {PUBLIC, *PRIVES}
    for slug in PRIVES:
        assert par_slug[slug]["label"] == slug, "sans fichier local, le libellé est le slug"
        assert par_slug[slug]["desc"] == ""


def test_le_fichier_local_nomme_les_scenarios(examples, monkeypatch):
    monkeypatch.setenv("SELFFARM_ENV", "perso")
    _ecrire_local(examples, {"libelles": {PRIVES[0]: {"label": "Officiel", "desc": "une phrase"}}})
    par_slug = {e["slug"]: e for e in route_dnja._list_examples()}
    assert par_slug[PRIVES[0]]["label"] == "Officiel"
    assert par_slug[PRIVES[0]]["desc"] == "une phrase"
    assert par_slug[PRIVES[1]]["label"] == PRIVES[1], "un scénario non nommé garde son slug"


def test_un_fichier_local_ne_fait_pas_apparaitre_un_scenario_prive(examples):
    """Le fichier local nomme ; il n'autorise rien. Seul SELFFARM_ENV ouvre la porte."""
    _ecrire_local(examples, {"libelles": {PRIVES[0]: {"label": "Officiel", "desc": "x"}}})
    assert [e["slug"] for e in route_dnja._list_examples()] == [PUBLIC]


def test_defauts_de_compare_sans_fichier_local(examples, monkeypatch):
    monkeypatch.setenv("SELFFARM_ENV", "perso")
    listes = route_dnja._list_examples()
    a, b = route_dnja._defauts_compare(listes)
    assert (a, b) == (listes[0]["slug"], listes[1]["slug"]), "les deux premiers de la liste"


def test_defauts_de_compare_lus_dans_le_fichier_local(examples, monkeypatch):
    monkeypatch.setenv("SELFFARM_ENV", "perso")
    _ecrire_local(examples, {"compare": {"a": PRIVES[1], "b": PRIVES[0]}})
    assert route_dnja._defauts_compare(route_dnja._list_examples()) == (PRIVES[1], PRIVES[0])


def test_un_slug_absent_est_ignore_au_lieu_d_etre_propose(examples):
    """Hors machine perso, les slugs privés du fichier local ne sont pas chargeables :
    la page ne doit pas les proposer, sinon elle ouvre sur une erreur."""
    _ecrire_local(examples, {"compare": {"a": PRIVES[0], "b": "hypotheses-inexistant"}})
    assert route_dnja._defauts_compare(route_dnja._list_examples()) == (PUBLIC, PUBLIC)


def test_un_fichier_local_illisible_ne_casse_rien(examples, monkeypatch):
    monkeypatch.setenv("SELFFARM_ENV", "perso")
    _ecrire_local(examples, "{ceci n'est pas du JSON")
    par_slug = {e["slug"]: e for e in route_dnja._list_examples()}
    assert par_slug[PRIVES[0]]["label"] == PRIVES[0]
    assert route_dnja._defauts_compare(route_dnja._list_examples())[0] in par_slug


def test_une_liste_vide_ne_leve_pas(examples, monkeypatch):
    """L'ancien code indexait examples[0] sans garde : un dossier vide levait IndexError."""
    for p in examples.glob("*.yaml"):
        p.unlink()
    assert route_dnja._defauts_compare(route_dnja._list_examples()) == ("", "")


def test_la_route_ne_nomme_aucun_scenario_prive():
    """Canari permanent, et il ne cite aucun libellé.

    Un test qui énumérerait les termes interdits les publierait : le dépôt
    dirait quels mots on a retirés, donc ce qu'ils décrivaient. Il éprouve donc
    une propriété de FORME, qui attrape en plus tout libellé privé futur :
    la route ne nomme qu'un seul scénario, la démo publique, et aucun slug ne
    porte un motif réservé — sauf la constante qui définit ces motifs.
    """
    source = Path(route_dnja.__file__).read_text(encoding="utf-8")
    assert list(route_dnja._LIBELLES_PUBLICS) == [PUBLIC], (
        "le dépôt ne nomme que la démo publique ; tout autre libellé vit dans le fichier local")
    for motif in route_dnja._PRIVATE_SCENARIO_PATTERNS:
        # Un slug nommé en dur, voilà ce qui ne doit pas revenir. Le motif seul
        # apparaît légitimement (la constante, et le nom du mode d'environnement).
        en_dur = [l.strip() for l in source.splitlines() if f"hypotheses-{motif}" in l]
        assert not en_dur, f"un slug « hypotheses-{motif}… » est nommé en dur : {en_dur[:2]}"
