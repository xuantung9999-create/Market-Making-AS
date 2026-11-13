"""Static checks on the dashboard files (read as text, no browser)."""
import re
from pathlib import Path

DASH = Path(__file__).resolve().parent.parent / "dashboard"
RESEARCH_VIEWS = ["simulator", "model", "replication", "real-data", "backtest",
                  "universe", "informed", "tuning", "about"]
DESK_VIEWS = ["overview", "pnl", "execution", "risk", "model-health",
              "signals", "market", "simlive", "health"]


def _html():
    return (DASH / "index.html").read_text(encoding="utf-8")


def _js_files():
    return [p for p in (DASH / "js").rglob("*.js")]


def test_research_view_ids_present():
    html = _html()
    for v in RESEARCH_VIEWS:
        assert f'id="view-{v}"' in html, v


def test_desk_view_ids_present():
    html = _html()
    for v in DESK_VIEWS:
        assert f'id="view-{v}"' in html, v


def test_no_long_inline_scripts():
    html = _html()
    for body in re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, flags=re.S):
        assert body.count("\n") <= 20, "inline <script> longer than 20 lines"


def test_script_src_paths_exist():
    html = _html()
    for src in re.findall(r'<script[^>]*\bsrc="([^"]+)"', html):
        if src.startswith(("http://", "https://")):
            continue
        assert (DASH / src).exists(), src


def test_no_fetch_anywhere_except_live_poller():
    files = [DASH / "index.html"] + _js_files()
    for f in files:
        if f.name == "live.js":
            continue
        assert "fetch(" not in f.read_text(encoding="utf-8"), f.name


def test_source_js_has_no_fetch():
    src = DASH / "js" / "source.js"
    assert src.exists()
    assert "fetch(" not in src.read_text(encoding="utf-8")


# ---------------------------------------------------------------- redesign shell (R1)
from html.parser import HTMLParser

OLD_NESTED = ["model", "replication", "signals", "market", "simlive", "health"]


class _Tree(HTMLParser):
    """Records tab links and, for every element with an id, the data-tab ancestors it sits under."""
    def __init__(self):
        super().__init__()
        self.stack, self.tab_links, self.in_nav, self.under = [], [], False, {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "nav" and "tabs" in (a.get("class") or ""):
            self.in_nav = True
        if self.in_nav and tag == "a":
            self.tab_links.append(a)
        if a.get("id"):
            self.under[a["id"]] = [t for t in self.stack if t]
        if tag not in ("br", "img", "input", "meta", "link", "hr"):
            self.stack.append(a.get("data-tab"))

    def handle_endtag(self, tag):
        if tag == "nav":
            self.in_nav = False
        if self.stack:
            self.stack.pop()


def _tree():
    t = _Tree()
    t.feed(_html())
    return t


def test_tab_row_has_exactly_eleven_links():
    assert len(_tree().tab_links) == 11


def test_tab_row_has_no_link_to_a_nested_view():
    views = {a.get("data-view") for a in _tree().tab_links}
    assert not views & set(OLD_NESTED)


def test_live_and_book_views_exist():
    html = _html()
    assert 'id="view-live"' in html and 'id="view-book"' in html


def test_model_and_replication_live_under_the_simulator_tab():
    under = _tree().under
    assert "simulator" in under["view-model"] and "simulator" in under["view-replication"]


def test_every_tab_link_points_at_a_tab_wrapper_and_every_view_is_in_one():
    t = _tree()
    html = _html()
    wrappers = set(re.findall(r'class="tab-wrap" data-tab="([^"]+)"', html))
    assert {a["data-view"] for a in t.tab_links} == wrappers
    for v in RESEARCH_VIEWS + DESK_VIEWS + ["live", "book"]:
        assert t.under[f"view-{v}"], f"view-{v} is not inside a tab"


def test_every_old_hash_resolves_to_a_tab_in_core_js():
    core = (DASH / "js" / "core.js").read_text(encoding="utf-8")
    assert "const TABS" in core and "function subtabs" in core
    for v in RESEARCH_VIEWS + DESK_VIEWS + ["live", "book", "archive", "data"]:
        assert f'"{v}"' in core, v


def test_demo_run_is_hidden_unless_asked_for():
    assert "demo=1" in (DASH / "js" / "core.js").read_text(encoding="utf-8")
