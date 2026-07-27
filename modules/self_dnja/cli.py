"""
CLI pour self-dnja.

Usage:
    self-dnja calcul hypotheses.yaml
    self-dnja calcul hypotheses.yaml --output previsionnel.json
    self-dnja pdf hypotheses.yaml --output dossier-dnja.pdf

Un fichier de log `~/self-dnja.log` est systématiquement produit (désactivable
avec `--no-log`) — toggle + versioning standardisés par convention MySelf.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import yaml

from self_dnja import __version__
from self_dnja.engine import calculer
from self_dnja.models import Hypotheses

DEFAULT_LOG = Path.home() / "self-dnja.log"


def setup_logging(enabled: bool, log_path: Path) -> logging.Logger:
    logger = logging.getLogger("self-dnja")
    logger.setLevel(logging.DEBUG if enabled else logging.CRITICAL + 1)
    logger.handlers.clear()
    if enabled:
        handler = logging.FileHandler(str(log_path))
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(handler)
    # aussi sur stdout pour visibilité immédiate en CLI
    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(logging.Formatter("%(levelname)s — %(message)s"))
    logger.addHandler(stream)
    return logger


def _load_hypotheses(path: Path) -> Hypotheses:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return Hypotheses.model_validate(data)


def _cmd_calcul(args: argparse.Namespace) -> int:
    hyp = _load_hypotheses(Path(args.hypotheses))
    result = calculer(hyp)
    payload = result.model_dump(mode="json")
    text = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"Prévisionnel écrit dans {args.output}")
    else:
        print(text)
    _print_summary(result)
    return 0


def _cmd_pdf(args: argparse.Namespace) -> int:
    from self_dnja.pdf import render_pdf
    hyp = _load_hypotheses(Path(args.hypotheses))
    result = calculer(hyp)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    render_pdf(result, out_path)
    size_kb = out_path.stat().st_size // 1024
    print(f"✓ Dossier DNJA PDF : {out_path} ({size_kb} Ko)", file=sys.stderr)
    _print_summary(result)
    return 0


def _print_summary(result) -> None:
    print("\n=== SYNTHÈSE DNJA ===", file=sys.stderr)
    for l in result.lignes:
        print(
            f"  Année {l.annee}: CA={l.produits_exploitation:>12}€  "
            f"EBE={l.ebe:>12}€  Résultat={l.resultat:>12}€",
            file=sys.stderr,
        )
    verdict = "✓ ATTEINT" if result.ebe_uth_atteint else "✗ INSUFFISANT"
    print(
        f"  EBE/UTH année {result.lignes[-1].annee}: "
        f"{result.ebe_uth_annee_cible} € (seuil {result.ebe_uth_seuil} €) → {verdict}",
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="self-dnja",
        description=f"Moteur de prévisionnel DNJA/DJA (v{__version__})",
    )
    parser.add_argument("--version", action="version", version=f"self-dnja {__version__}")
    parser.add_argument("--no-log", action="store_true", help="Désactive le log")
    parser.add_argument("--log-file", type=Path, default=DEFAULT_LOG)

    sub = parser.add_subparsers(dest="cmd", required=True)

    p_calcul = sub.add_parser("calcul", help="Calcule le prévisionnel à partir d'un YAML")
    p_calcul.add_argument("hypotheses", help="Chemin du fichier YAML d'hypothèses")
    p_calcul.add_argument("-o", "--output", help="Fichier JSON de sortie (sinon stdout)")
    p_calcul.set_defaults(func=_cmd_calcul)

    p_pdf = sub.add_parser("pdf", help="Génère le dossier PDF pour la DDT (à venir)")
    p_pdf.add_argument("hypotheses")
    p_pdf.add_argument("-o", "--output", required=True)
    p_pdf.set_defaults(func=_cmd_pdf)

    args = parser.parse_args(argv)
    logger = setup_logging(not args.no_log, args.log_file)
    logger.info("self-dnja v%s démarré, commande=%s", __version__, args.cmd)

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
