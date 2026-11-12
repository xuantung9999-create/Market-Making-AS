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
