"""
webapp.modules_state — état des modules actifs + mode de vue.

S'appuie sur :
- webapp.modules_catalog  (catalogue déclaratif)
- self_agri_book.exploitation  (persistance : colonnes modules_actifs, view_mode)

Sémantique (cf project_selffarm_modes_modulaires) :
- modules ACTIFS = ids que l'utilisateur a activés (seuls les 'live' comptent).
  Fallback si jamais configuré (NULL en DB) = tous les 'live' (rétrocompat : rien ne disparaît).
- view_mode : 'mine' (n'afficher que mes modules) | 'full' (afficher AUSSI les
  modules non actifs / à venir, grisés "bientôt").
- Les modules core=True sont TOUJOURS actifs (jamais retirables).

⚠️ Principe non négociable : (dés)activer = montrer/cacher l'UI. JAMAIS supprimer de données.
"""
from __future__ import annotations

import os

from webapp import modules_catalog as cat
from self_agri_book.exploitation import get_exploitation, save_exploitation


def get_active_ids() -> set[str]:
    """Ids des modules actifs. Fallback = tous les 'live' si jamais configuré."""
    expl = get_exploitation()
    raw = expl.get("modules_actifs") if expl else None
    active = cat.live_ids() if raw is None else set(raw)
    return active | cat.core_ids()  # core toujours actif


def is_module_active(mid: str) -> bool:
    m = cat.module_by_id(mid)
    if m is None:
        return False
    return True if m.core else (mid in get_active_ids())


def get_view_mode() -> str:
    # Démo publique : vue complète forcée → on montre TOUS les modules (actifs
    # + à venir grisés "bientôt") pour exposer la feuille de route SelfFarm.
    if os.environ.get("SELFFARM_ENV", "prod") == "demo":
        return "full"
    expl = get_exploitation()
    vm = (expl or {}).get("view_mode")
    return vm if vm in cat.VALID_VIEW_MODES else "mine"


def is_module_visible(mid: str, view_mode: str | None = None) -> bool:
    """Visible dans la sidebar si actif (affiché normal) OU view_mode == 'full'
    (affiché grisé 'bientôt' / 'à activer')."""
    if cat.module_by_id(mid) is None:
        return False
    if is_module_active(mid):
        return True
    return (view_mode or get_view_mode()) == "full"


# ── Mutations (passent par save_exploitation : UPDATE partiel, aucune perte) ──
def set_view_mode(mode: str) -> None:
    if mode not in cat.VALID_VIEW_MODES:
        raise ValueError(f"view_mode invalide : {mode}")
    save_exploitation({"view_mode": mode})


def set_active_ids(ids) -> None:
    """Persiste l'ensemble actif (core forcé dedans, restreint aux 'live')."""
    clean = (set(ids) & cat.live_ids()) | cat.core_ids()
    save_exploitation({"modules_actifs": sorted(clean)})


def toggle_module(mid: str, active: bool) -> None:
    """Active ou désactive UN module (refuse de toucher au core)."""
    m = cat.module_by_id(mid)
    if m is None or m.core or m.status != "live":
        return  # core/soon/inconnu : pas de bascule
    current = get_active_ids()
    if active:
        current.add(mid)
    else:
        current.discard(mid)
    set_active_ids(current)


def apply_mode_preset(mode: str) -> None:
    """Applique un preset d'install (lite/full/perso) = set initial de modules actifs."""
    if mode not in cat.VALID_MODES:
        raise ValueError(f"mode invalide : {mode}")
    set_active_ids(cat.default_active_ids(mode))


# ── Navigation : déterminer le contexte actif depuis l'URL ───────────────────
def active_module_id(path: str) -> str | None:
    """Id du module dont un item matche le path (match le plus long gagne)."""
    best, best_len = None, -1
    for m in cat.all_modules():
        for it in m.items:
            am = it.active_match
            if path.startswith(am) and len(am) > best_len:
                best, best_len = m.id, len(am)
    return best


def active_tab(path: str) -> str:
    """Onglet actif déduit de l'URL (défaut : production)."""
    mid = active_module_id(path)
    m = cat.module_by_id(mid) if mid else None
    return m.tab if m else "production"


def first_visible_route(tab_key: str) -> str:
    """Route cible quand on clique un onglet : 1er module actif avec items,
    sinon 1er module visible (placeholder), sinon '#'."""
    vm = get_view_mode()
    for m in cat.modules_by_tab(tab_key):
        if is_module_active(m.id) and m.items:
            return m.items[0].route
    for m in cat.modules_by_tab(tab_key):
        if is_module_visible(m.id, vm):
            return f"/m/{m.id}/bientot"
    return "#"


def visible_tabs() -> list[tuple[str, str, str]]:
    """Onglets ayant au moins un module visible (selon le view_mode courant)."""
    vm = get_view_mode()
    return [
        (key, label, ic)
        for key, label, ic in cat.tabs()
        if any(is_module_visible(m.id, vm) for m in cat.modules_by_tab(key))
    ]
