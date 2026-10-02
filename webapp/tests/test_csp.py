"""La CSP interdit le JavaScript inline et les ressources d'un autre domaine :
aucune page ne doit en dépendre. Les pages servies sont parcourues ; les
templates et les scripts sont lus, ce qui couvre aussi les pages à paramètres
que le parcours n'atteint pas."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.responses import HTMLResponse
from starlette.routing import Route

from webapp.main import CSP, CSP_CARTO, app

WEBAPP = Path(__file__).parent.parent
TEMPLATES = sorted([*(WEBAPP / "templates").rglob("*.html"),
                    *(p for p in (WEBAPP / "static").rglob("*.html") if "vendor" not in p.parts)])
SCRIPTS = sorted(p for p in (WEBAPP / "static").rglob("*.js")
                 if "vendor" not in p.parts and p.name != "chart.umd.min.js")

SCRIPT_INLINE = re.compile(r"<script\b(?![^>]*\bsrc=)(?![^>]*application/json)[^>]*>", re.IGNORECASE)
GESTIONNAIRE = re.compile(r"<[a-z][^>]*\son[a-z]+\s*=", re.IGNORECASE)
HX_ON = re.compile(r"\bhx-on\b")
CDN = re.compile(r"unpkg\.com|jsdelivr|googleapis|gstatic|cdnjs|cloudflare", re.IGNORECASE)

PAGES = sorted(r.path for r in app.routes
               if isinstance(r, Route) and "GET" in (r.methods or set())
               and "{" not in r.path and getattr(r, "response_class", None) is HTMLResponse)


def _defauts(texte: str) -> list[str]:
    d = [f"script inline : {m.group(0)}" for m in SCRIPT_INLINE.finditer(texte)]
    d += [f"gestionnaire inline : {m.group(0)[:80]}" for m in GESTIONNAIRE.finditer(texte)]
    d += ["hx-on"] * len(HX_ON.findall(texte))
    return d


def test_le_parcours_couvre_les_pages_de_l_app():
    assert len(PAGES) >= 30


@pytest.mark.parametrize("path", PAGES)
def test_chaque_page_porte_la_csp_et_aucun_js_inline(client, path):
    r = client.get(path)
    if r.status_code != 200 or not r.headers["content-type"].startswith("text/html"):
        pytest.skip(f"{path} : {r.status_code} {r.headers.get('content-type')}")
    attendue = CSP_CARTO if path == "/parcelles/carto/embed" else CSP
    assert r.headers["content-security-policy"] == attendue
    assert _defauts(r.text) == []
    assert not CDN.search(r.text)


@pytest.mark.parametrize("tpl", TEMPLATES, ids=lambda p: str(p.relative_to(WEBAPP)))
def test_aucun_template_ne_porte_de_js_inline(tpl):
    texte = tpl.read_text(encoding="utf-8")
    assert _defauts(texte) == []
    assert not CDN.search(texte)


@pytest.mark.parametrize("js", SCRIPTS, ids=lambda p: str(p.relative_to(WEBAPP)))
def test_aucun_script_ne_fabrique_de_gestionnaire_inline(js):
    texte = js.read_text(encoding="utf-8")
    assert [m.group(0)[:80] for m in GESTIONNAIRE.finditer(texte)] == []
    assert not CDN.search(texte)


def test_les_service_workers_peuvent_controler_les_pages_pos(client):
    for sw in ("/static/pos/sw.js", "/static/pos/sw-mobile.js"):
        assert client.get(sw).headers["service-worker-allowed"] == "/pos/"
