"""
CLI pour self-aid.

Usage:
    self-aid list
    self-aid show dnja-2026
    self-aid search --statut ja-installation
    self-aid search --bio --zone le departement
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from self_aid import __version__
from self_aid.loader import filter_aides, load_all, total_enveloppe
from self_aid.models import CategorieAide, FiltreRecherche

DEFAULT_LOG = Path.home() / "self-aid.log"


def setup_logging(enabled: bool, log_path: Path) -> logging.Logger:
    logger = logging.getLogger("self-aid")
    logger.setLevel(logging.DEBUG if enabled else logging.CRITICAL + 1)
    logger.handlers.clear()
    if enabled:
        handler = logging.FileHandler(str(log_path))
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        logger.addHandler(handler)
    return logger


def _cmd_list(args):
    aides = load_all()
    for a in aides:
        print(f"  {a.id:30} {a.nom} [{a.categorie}]")
    mn, mx = total_enveloppe(aides)
    print(f"\n{len(aides)} aide(s) — enveloppe cumulée indicative : {mn:.0f} – {mx:.0f} €")
    return 0


def _cmd_show(args):
    aides = load_all()
    found = next((a for a in aides if a.id == args.id), None)
    if not found:
        print(f"Aide inconnue : {args.id}", file=sys.stderr)
        return 2
    import json
    print(json.dumps(found.model_dump(mode="json"), indent=2, ensure_ascii=False, default=str))
    return 0


def _cmd_search(args):
    aides = load_all()
    f = FiltreRecherche(
        statut=args.statut,
        categorie=CategorieAide(args.categorie) if args.categorie else None,
        zone=args.zone,
        departement=args.departement,
        bio=args.bio,
        age=args.age,
        mot_cle=args.mot_cle,
    )
    filtered = filter_aides(aides, f)
    if not filtered:
        print("Aucune aide ne correspond aux critères.", file=sys.stderr)
        return 1
    for a in filtered:
        m = a.montant
        range_txt = f"{m.valeur_min}" if m.valeur_min == m.valeur_max else f"{m.valeur_min}–{m.valeur_max}"
        print(f"  ★ {a.nom}")
        print(f"      id      : {a.id}")
        print(f"      montant : {range_txt} {m.unite}")
        print(f"      source  : {a.source.url}")
        if a.notes:
            print(f"      note    : {a.notes[:160]}{'…' if len(a.notes) > 160 else ''}")
        print()
    mn, mx = total_enveloppe(filtered)
    print(f"{len(filtered)} aide(s) filtrée(s) — cumul indicatif : {mn:.0f} – {mx:.0f} €")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="self-aid",
        description=f"Catalogue d'aides publiques — v{__version__}",
    )
    p.add_argument("--version", action="version", version=f"self-aid {__version__}")
    p.add_argument("--no-log", action="store_true")
    p.add_argument("--log-file", type=Path, default=DEFAULT_LOG)
    sub = p.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="Liste toutes les aides")
    p_list.set_defaults(func=_cmd_list)

    p_show = sub.add_parser("show", help="Affiche une aide en détail")
    p_show.add_argument("id")
    p_show.set_defaults(func=_cmd_show)

    p_search = sub.add_parser("search", help="Filtre les aides")
    p_search.add_argument("--statut", help="Ex: ja-installation, agriculteur-bio")
    p_search.add_argument("--categorie", choices=[c.value for c in CategorieAide])
    p_search.add_argument("--zone")
    p_search.add_argument("--departement", type=int)
    p_search.add_argument("--bio", action="store_true")
    p_search.add_argument("--age", type=int)
    p_search.add_argument("--mot-cle")
    p_search.set_defaults(func=_cmd_search)

    args = p.parse_args(argv)
    setup_logging(not args.no_log, args.log_file)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
