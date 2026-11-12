"""Build a publishable copy of the dashboard (Dashboard Guide D12, --public step).

    python -m scripts.publish_dashboard                       # every non-demo run in dashboard/runs
    python -m scripts.publish_dashboard --runs qb-2026-11-12,wf-2026-11-12-q1

Writes dashboard_public/: the page, its scripts, data.js, and pub-<run_id>.js copies of the chosen
runs with curves thinned to 30-minute points (demo runs are refused). The live strip never appears
on a published copy because it only runs when the page is served by the local server.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from mm.report import JS_PREFIX, public_bundle, validate_bundle

DASH = Path("dashboard")


def load_run(path: Path) -> dict:
    s = path.read_text(encoding="utf-8")
    return json.loads(s[s.index("= {") + 2: s.rstrip().rstrip(";").rindex("}") + 1])


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m scripts.publish_dashboard")
    ap.add_argument("--runs", default=None, help="comma-separated run ids (default: every non-demo run)")
    ap.add_argument("--out", default="dashboard_public")
    ap.add_argument("--every-min", type=int, default=30)
    args = ap.parse_args(argv)
    idx_txt = (DASH / "runs" / "index.js").read_text(encoding="utf-8")
    index = json.loads(idx_txt[idx_txt.index("["): idx_txt.rindex("]") + 1])
    wanted = args.runs.split(",") if args.runs else [r["run_id"] for r in index if r["kind"] != "demo" and not r["run_id"].startswith("pub-")]
    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    (out / "runs").mkdir(parents=True)
    shutil.copytree(DASH / "js", out / "js")
    for f in ("index.html", "data.js"):
        shutil.copy2(DASH / f, out / f)
    pub_index = []
    for rid in wanted:
        entry = next((r for r in index if r["run_id"] == rid), None)
        if entry is None:
            print(f"skip {rid}: not in dashboard/runs/index.js")
            continue
        b = public_bundle(load_run(DASH / "runs" / f"{rid}.js"), every_min=args.every_min)
        problems = validate_bundle(b)
        if problems:
            raise SystemExit(f"{rid}: invalid bundle: {problems[:3]}")
        text = f'{JS_PREFIX}\nwindow.RUNS["{b["run_id"]}"] = {json.dumps(b, separators=(",", ":"))};\n'
        (out / "runs" / f"{b['run_id']}.js").write_text(text, encoding="utf-8")
        pub_index.append({**entry, "run_id": b["run_id"]})
        print(f"{rid} -> runs/{b['run_id']}.js ({len(text) / 1e6:.1f} MB)")
    (out / "runs" / "index.js").write_text("window.RUN_INDEX = " + json.dumps(pub_index, indent=1) + ";\n", encoding="utf-8")
    big = [p for p in out.rglob("*") if p.is_file() and p.stat().st_size > 3e6 and p.name != "data.js"]
    if big:
        print("warning: files above 3 MB:", ", ".join(str(p) for p in big))
    print(f"publishable copy -> {out}/")


if __name__ == "__main__":
    main()
