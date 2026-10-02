"""Le cookie de session n'est jamais signé avec une clé lisible dans le dépôt :
qui la lirait pourrait fabriquer un cookie valide. Chaque installation a la sienne.
"""

from __future__ import annotations

import os
import stat

import pytest
from starlette.middleware.sessions import SessionMiddleware

from webapp.session_key import session_key_path, session_secret


@pytest.fixture
def sans_variable(tmp_path, monkeypatch):
    monkeypatch.delenv("SELFFARM_SESSION_SECRET", raising=False)
    monkeypatch.setenv("SELFFARM_COMPTA_DB", str(tmp_path / "compta.db"))
    return tmp_path


def test_la_variable_prime_et_rien_ne_s_ecrit(sans_variable, monkeypatch):
    monkeypatch.setenv("SELFFARM_SESSION_SECRET", "posee-par-l-hote")
    assert session_secret() == "posee-par-l-hote"
    assert not session_key_path().exists()


def test_sans_variable_une_cle_propre_est_tiree_puis_reprise(sans_variable):
    cle = session_secret()
    p = session_key_path()
    assert p.parent == sans_variable
    assert len(cle) == 64 and int(cle, 16) >= 0
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert session_secret() == cle
    assert [f.name for f in sans_variable.iterdir()] == ["session.key"]


def test_une_cle_existante_est_reprise_telle_quelle(sans_variable):
    session_key_path().write_text("cle-d-une-version-precedente\n", encoding="ascii")
    assert session_secret() == "cle-d-une-version-precedente"


def test_le_worker_qui_perd_la_course_garde_la_cle_du_gagnant(sans_variable):
    from webapp.session_key import _create

    p = session_key_path()
    p.write_text("cle-du-gagnant", encoding="ascii")
    _create(p)
    assert p.read_text(encoding="ascii") == "cle-du-gagnant"
    assert [f.name for f in sans_variable.iterdir()] == ["session.key"]


def test_une_cle_vide_empeche_le_demarrage(sans_variable):
    session_key_path().write_text("", encoding="ascii")
    with pytest.raises(RuntimeError, match="vide"):
        session_secret()


@pytest.mark.skipif(os.geteuid() == 0, reason="root écrit malgré les permissions")
def test_un_dossier_non_inscriptible_empeche_le_demarrage(sans_variable):
    sans_variable.chmod(0o500)
    try:
        with pytest.raises(RuntimeError, match="SELFFARM_SESSION_SECRET"):
            session_secret()
    finally:
        sans_variable.chmod(0o700)


def test_l_application_signe_avec_la_cle_de_l_installation():
    from webapp.main import app

    (session,) = [m for m in app.user_middleware if m.cls is SessionMiddleware]
    assert session.kwargs["secret_key"] == session_secret()
