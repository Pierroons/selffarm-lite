"""L'étape 4 de `scripts/deploy.sh`, telle qu'elle part au serveur : extraite du fichier,
développée avec de fausses valeurs, jouée avec un faux `sudo` qui journalise. Le filet de
reverrouillage s'arme avant l'unlock, le lock du trap va au bout sous ^C et ^\\, et le
filet ne se désarme qu'après un lock réussi."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[2] / "scripts" / "deploy.sh"
IMMUT = "/faux/prod-immutable.sh"
DESARMER = "SUDO systemctl stop selffarm-relock.timer"

# Le vrai lock fige entrée par entrée par des processus enfants (find, chattr) : un
# signal qui les tue l'arrête à mi-chemin. bash, lui, ignore SIGQUIT en toutes
# circonstances : le faux lock doit donc dépendre de son enfant, comme le vrai.
FAUX_SUDO = f"""#!/usr/bin/env bash
echo "SUDO $*" >> "$JOURNAL"
case "$1 ${{2:-}}" in
  "{IMMUT} lock") echo LOCK-DEBUT >> "$JOURNAL"
     sleep 1.2 || {{ echo LOCK-INTERROMPU >> "$JOURNAL"; exit 1; }}
     [ "${{LOCK_ECHOUE:-0}}" = 1 ] && {{ echo LOCK-ECHEC >> "$JOURNAL"; exit 1; }}
     echo LOCK-FIN >> "$JOURNAL" ;;
  rsync*) sleep 1.5 ;;
esac
exit 0
"""


def _etape4() -> str:
    """Le texte que `ssh -t "$REMOTE" "…"` envoie, une fois les variables développées."""
    bloc = DEPLOY.read_text(encoding="utf-8").split('ssh -t "$REMOTE" "', 1)[1]
    bloc = bloc.split('\n" || deploiement=$?', 1)[0]
    for variable, valeur in {"$IMMUT": IMMUT, "$STAGE": "stage", "$PROD": "/faux/prod",
                             "$SERVICE": "svc"}.items():
        bloc = bloc.replace(variable, valeur)
    return bloc.replace('\\"', '"')


@pytest.fixture
def banc(tmp_path):
    outils = tmp_path / "outils"
    outils.mkdir()
    (outils / "sudo").write_text(FAUX_SUDO)
    (outils / "sudo").chmod(0o755)
    script = tmp_path / "etape4.sh"
    script.write_text(_etape4())
    return tmp_path, outils, script


def _jouer(banc, signaux=(), **env) -> list[str]:
    dossier, outils, script = banc
    journal = dossier / "journal"
    journal.write_text("")
    environ = {**os.environ, "JOURNAL": str(journal), "PATH": f"{outils}:{os.environ['PATH']}", **env}
    p = subprocess.Popen(["bash", str(script)], env=environ, start_new_session=True)
    for attente, sig in signaux:
        time.sleep(attente)
        try:
            os.killpg(p.pid, sig)
        except ProcessLookupError:
            pass
    p.wait(timeout=30)
    return [ligne.strip() for ligne in journal.read_text().splitlines()]


def _arme_avant_unlock(lignes: list[str]) -> bool:
    arme = next(i for i, l in enumerate(lignes) if "systemd-run" in l and f"{IMMUT} lock" in l)
    ouvre = next(i for i, l in enumerate(lignes) if l == f"SUDO {IMMUT} unlock")
    return arme < ouvre


def test_sans_signal_le_filet_s_arme_puis_se_desarme(banc):
    lignes = _jouer(banc)
    assert _arme_avant_unlock(lignes)
    assert "LOCK-FIN" in lignes
    assert lignes[-1] == DESARMER


@pytest.mark.parametrize("second", [signal.SIGINT, signal.SIGQUIT], ids=["^C", "^\\"])
def test_un_second_signal_pendant_le_lock_ne_l_interrompt_pas(banc, second):
    lignes = _jouer(banc, [(0.8, signal.SIGINT), (0.7, second)])
    assert _arme_avant_unlock(lignes)
    assert "LOCK-FIN" in lignes
    assert lignes[-1] == DESARMER


def test_un_lock_qui_echoue_laisse_le_filet_arme(banc):
    lignes = _jouer(banc, LOCK_ECHOUE="1")
    assert "LOCK-ECHEC" in lignes
    assert lignes.count(DESARMER) == 1   # le nettoyage d'avant l'unlock, pas de désarmement
