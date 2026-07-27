"""
modules_catalog — catalogue déclaratif des modules SelfFarm-Lite.

Source UNIQUE de vérité pour :
- la composition de la sidebar (onglets > modules > items)
- les 3 modes d'install (lite / full / perso) = presets de modules ACTIFS
- la "vue complète" (afficher aussi les modules non actifs / 🔜 à venir, grisés)

Principe directeur (cf project_selffarm_modes_modulaires) :
    Activer/désactiver un module = montrer/cacher son interface. JAMAIS toucher aux données.
    Les modules `core=True` (compta, backup, profil, modules) sont TOUJOURS actifs.

`status` :
- "live" : module développé, activable
- "soon" : cible à venir → affiché grisé "bientôt" en vue complète, jamais "actif"

`modes` : presets où le module est actif par défaut à l'install ("lite" et/ou "full").
`perso` = preset = tous les `live` actifs au départ, puis ajustable à la carte.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Onglets de la sidebar (ordre = ordre d'affichage)
TABS = (
    ("production", "Production", "sprout"),
    ("vente", "Vente", "cart"),
    ("gestion", "Gestion", "chart"),
    ("pilotage", "Pilotage", "gauge"),
    ("assistant", "Assistant IA", "robot"),
    ("parametres", "Paramètres", "settings"),
)


@dataclass(frozen=True)
class NavItem:
    label: str
    route: str
    match: str = ""          # préfixe d'URL pour l'état actif (défaut = route)

    @property
    def active_match(self) -> str:
        return self.match or self.route


@dataclass(frozen=True)
class Module:
    id: str
    label: str               # titre de section dans la sidebar
    tab: str                 # clé d'onglet (voir TABS)
    icon: str                # clé d'icône (mappée vers SVG dans le template)
    status: str = "live"     # "live" | "soon"
    items: tuple[NavItem, ...] = ()
    modes: tuple[str, ...] = ("full",)   # presets où actif par défaut
    core: bool = False       # True = jamais désactivable
    desc: str = ""           # description (page placeholder "bientôt")


# ─────────────────────────────────────────────────────────────────────────────
# CATALOGUE
# ─────────────────────────────────────────────────────────────────────────────
CATALOG: tuple[Module, ...] = (
    # ===================== PRODUCTION =====================
    Module("parcelles", "Parcellaire", "production", "map", "live",
           (NavItem("Mes parcelles", "/parcelles", "/parcelles"),
            NavItem("Carte parcellaire IGN", "/parcelles/carto")),
           modes=("lite", "full"), core=True,
           desc="Le foncier + localisation — socle transversal (cultures, prairies, pâtures, ruchers). Toujours actif."),
    Module("cultures", "Cultures", "production", "sprout", "live",
           (NavItem("Assolement", "/cultures", "/cultures"),),
           modes=("full",),
           desc="Activité végétale : plan de culture, assolement & rotations, semis → récolte."),
    Module("interventions", "Interventions", "production", "tractor", "soon",
           modes=("full",),
           desc="Itinéraires techniques : semis, traitements, récolte, traçabilité parcelle."),
    Module("intrants", "Stocks intrants", "production", "box", "soon",
           modes=("full",),
           desc="Intrants de production (amont) : semences/plants, engrais & amendements, produits de traitement (phyto/biocontrôle), aliments du bétail — stocks et mouvements (achats, consommation par culture). ≠ stock de produits finis (aval) ≠ matériel (immos)."),
    Module("elevage", "Élevage", "production", "cow", "live",
           (NavItem("Ponte du jour", "/elevage", "/elevage"),
            NavItem("Bandes & mouvements", "/elevage/bandes"),
            NavItem("Lots d'œufs", "/elevage/lots"),
            NavItem("Aliment", "/elevage/aliment"),
            NavItem("Registre d'élevage", "/elevage/registre")),
           modes=("full",),
           desc="Toutes pratiques d'élevage — cheptel (bovins, ovins, caprins…), volailles, apiculture (ruchers, miel), sanitaire/soins, reproduction, alimentation, pâturage, traçabilité (boucles, registre)."),
    Module("transformation", "Transformation", "production", "jar", "soon",
           modes=("full",),
           desc="Atelier de transformation : recettes, lots, DLC/DLUO, étiquetage."),

    # ===================== VENTE =====================
    Module("invoice", "Facturation", "vente", "invoice", "live",
           (NavItem("Factures Factur-X", "/invoice"),),
           modes=("lite", "full")),
    Module("pos", "Caisse marché", "vente", "cart", "live",
           (NavItem("SelfPOS — Caisse", "/pos", "/pos"),
            NavItem("Catalogue produits", "/pos/produits"),
            NavItem("Connecter le mobile", "/pos/mode-marche"),
            NavItem("Exporter pour mobile", "/pos/catalogue-export"),
            NavItem("Import retour marché", "/pos/import-marche"),
            NavItem("Statistiques produits", "/pos/stats"),
            NavItem("Stock résiduel", "/pos/stock-revue")),
           modes=("full",)),
    Module("pos_collectif", "Point de vente collectif", "vente", "store", "live",
           (NavItem("Magasins & dépôts", "/pos/collectifs"),),
           modes=("full",)),
    Module("clients", "Clients & circuits", "vente", "users", "soon",
           modes=("full",),
           desc="Clients, circuits de vente (AMAP, magasins, pro), historique."),
    Module("devis", "Devis & tarifs", "vente", "tag", "soon",
           modes=("full",),
           desc="Devis, grilles tarifaires, conditions de vente."),

    # ===================== GESTION =====================
    Module("compta", "Comptabilité", "gestion", "chart", "live",
           (NavItem("Tableau de bord", "/compta"),),
           modes=("lite", "full"), core=True),
    Module("import_compta", "Reprise de compta", "gestion", "box", "soon",
           modes=("full",),
           desc="Importer une compta existante d'un autre logiciel. FEC en pivot (format légal universel) ; les formats exotiques sont reconnus par le LLM (import assisté)."),
    Module("dnja", "DNJA / Prévisionnel", "gestion", "clock", "live",
           (NavItem("Saisir DNJA", "/dnja", "/dnja"),
            NavItem("Comparer", "/dnja/compare"),
            NavItem("Éditeur", "/dnja/editor")),
           modes=("lite", "full")),
    Module("aides", "Aides publiques", "gestion", "gift", "live",
           (NavItem("Catalogue aides", "/aides"),),
           modes=("full",)),
    Module("banking", "Banque & rapprochement", "gestion", "bank", "soon",
           modes=("full",),
           desc="Import de relevés bancaires, rapprochement avec les écritures."),
    Module("tva", "TVA & déclarations", "gestion", "receipt", "soon",
           modes=("full",),
           desc="Calcul TVA, déclarations (CA12/CA3), échéancier fiscal."),
    Module("immos", "Immobilisations", "gestion", "building", "soon",
           modes=("full",),
           desc="Suivi des immobilisations, amortissements, plan d'amortissement."),
    Module("social", "Social (MSA, salariés)", "gestion", "id-card", "soon",
           modes=("full",),
           desc="Cotisations MSA, salariés, contrats, bulletins simplifiés."),
    Module("admin", "Administratif", "gestion", "folder", "soon",
           modes=("full",),
           desc="Déclaration PAC, contrats, documents administratifs."),

    # ===================== PILOTAGE =====================
    Module("dashboard", "Tableau de bord global", "pilotage", "gauge", "soon",
           modes=("full",),
           desc="Vue d'ensemble : indicateurs, météo, alertes, échéances."),
    Module("sentinelle", "Sentinelle épidémio", "pilotage", "radar", "soon",
           modes=("full",),
           desc="Réseau citoyen de signalement épidémio — cultures, élevage, ruchers (opt-in)."),

    # ===================== ASSISTANT IA (LLM local SelfHub) =====================
    Module("ia_chat", "Assistant local", "assistant", "robot", "soon",
           modes=("full",),
           desc="LLM local (SelfHub) : questions sur l'app, aide à la saisie, recherche dans tes données — 100 % hors-ligne."),
    Module("ia_debug", "Debug assisté", "assistant", "robot", "soon",
           modes=("full",),
           desc="Le LLM applique des règles de diagnostic sur l'app, corrige ce qu'il peut, et produit un rapport clair (fait / vu / reste à faire)."),

    # ===================== PARAMÈTRES =====================
    Module("backup", "Sauvegarde", "parametres", "download", "live",
           (NavItem("Backup local", "/backup"),),
           modes=("lite", "full"), core=True),
    Module("modules", "Modules", "parametres", "grid", "live",
           (NavItem("Gérer les modules", "/parametres/modules"),),
           modes=("lite", "full"), core=True),
    Module("roadmap", "Évolutions", "parametres", "clock", "live",
           (NavItem("Roadmap V1 beta", "/roadmap"),),
           modes=("lite", "full")),
    Module("docs", "Documentation", "parametres", "book", "live",
           (NavItem("API Swagger", "/docs"),),
           modes=("full",)),
)

_BY_ID = {m.id: m for m in CATALOG}
_TAB_LABELS = {k: (label, icon) for k, label, icon in TABS}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def all_modules() -> tuple[Module, ...]:
    return CATALOG


def module_by_id(mid: str) -> Module | None:
    return _BY_ID.get(mid)


def modules_by_tab(tab_key: str) -> tuple[Module, ...]:
    """Modules d'un onglet, dans l'ordre du catalogue."""
    return tuple(m for m in CATALOG if m.tab == tab_key)


def core_ids() -> set[str]:
    """Modules jamais désactivables."""
    return {m.id for m in CATALOG if m.core}


def live_ids() -> set[str]:
    """Modules développés (activables)."""
    return {m.id for m in CATALOG if m.status == "live"}


def default_active_ids(mode: str) -> set[str]:
    """Set d'ids actifs pour un preset d'install.

    - lite  : modules `live` marqués mode 'lite' (socle) + core
    - full  : tous les `live` + core
    - perso : comme full au départ (tous les live), puis ajustable à la carte
    """
    core = core_ids()
    if mode == "lite":
        return core | {m.id for m in CATALOG if m.status == "live" and "lite" in m.modes}
    # full + perso : tous les modules développés
    return core | live_ids()


def tabs() -> tuple[tuple[str, str, str], ...]:
    return TABS


def tab_meta(tab_key: str) -> tuple[str, str]:
    """(label, icon) d'un onglet."""
    return _TAB_LABELS.get(tab_key, (tab_key.capitalize(), "grid"))


VALID_MODES = ("lite", "full", "perso")
VALID_VIEW_MODES = ("mine", "full")
