"""v2 Task 8: agent walk-forward on history, and Gate A.

Per v2-universe coin, days in date order. One CalibrationAgent per coin lives across all
days (end_day between days). The first ``--warmup-days`` (7) are warm-up: the agent trades on
paper and learns, but those days are not counted. Every later day counts.

The whole run is done three times: queue_mult 1.0 (headline), 2.0 (stress), 0.5 (optimistic).
Baselines on the same days: Join touch, and the EdgePolicy fixed at the agent's starting
(most conservative) setting with the table frozen at the end of warm-up.

Gate A is computed, not judged (agent rows, headline queue, counted days with >= 20 fills):
  1. mean daily net P&L > 0 and t > 3 across coin-days
  2. at least 3 coins with positive total net P&L
  3. at least 60% of coin-days positive
  4. mean daily net P&L still > 0 at queue_mult 2.0
  5. agent total net P&L >= Join touch total on the same coin-days
  pass = all five. If it fails, nothing is adjusted to make it pass.

    python -m scripts.run_agent_walkforward
    python -m scripts.run_agent_walkforward --export-state      # also save final tables for paper trading
Writes results/agent_walkforward.csv, results/agent_history.json, results/gate_a.json.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from datetime import datetime, timezone

from mm import report
from mm.agent import MENU, START_ARM, AgentConfig, CalibrationAgent, run_agent
from mm.edge import EdgePolicy, EdgeTable
from mm.features import FeatureEngine
from mm.metrics import summarize
from mm.queue_sim import JoinTouch, QSConfig, run_queue_sim
from scripts.v2_common import fee_note, load_day, symbol_days, t_stat, v2_universe

QUEUES = (("headline", 1.0), ("stress", 2.0), ("optimistic", 0.5))
FEES = (0.0, 7.5, 10.0)
MIN_FILLS = 20


def _row(res, **kw) -> dict:
    s = summarize(res, fee_bps_scenarios=FEES)
    f = res.fills
    s["net_edge_bp_mean"] = float(np.nanmean(f["net_edge_bp"])) if len(f) and f["net_edge_bp"].notna().any() else np.nan
    s.update(kw)
    return s


def run_symbol(sym: str, qname: str, qmult: float, warmup_days: int, data_dir: str, keep: list | None = None):
    cfg = replace(QSConfig(), queue_mult=qmult)
    rows, agent, frozen, last_tick, day_no = [], None, None, None, 0
    for day in symbol_days(sym, data_dir):
        got = load_day(sym, day, data_dir)
        if got is None:
            continue
        trades, tick, tape = got
        if agent is None or not np.isclose(tick, last_tick):
            if agent is not None:
                print(f"WARNING {sym} {day}: tick changed {last_tick:g} -> {tick:g}; edge table reset")
            agent = CalibrationAgent(AgentConfig(), cfg, tick)
            frozen = None if day_no < warmup_days else frozen
        last_tick = tick
        d_idx = agent.live._day
        run_agent(tape, trades, agent, cfg.decision_ms)
        agent.end_day()
        counted = day_no >= warmup_days
        common = dict(symbol=sym, day=day, queue=qname, queue_mult=qmult, counted=counted, day_no=day_no + 1,
                      live_arm=agent.live_arm)
        out = [("agent", agent.result(day=d_idx)), ("join_touch", run_queue_sim(tape, trades, JoinTouch(), cfg, tick))]
        if frozen is not None:
            spec = MENU[START_ARM]
            pol = EdgePolicy(frozen, spec.e_min_bp, spec.z, spec.gamma_bp, name="Frozen start arm")
            out.append(("frozen_start", run_queue_sim(tape, trades, pol, cfg, tick, features=FeatureEngine(tick))))
        for var, res in out:
            rows.append(_row(res, variant=var, **common))
            if keep is not None and counted:
                keep.append((sym, day, var, res, agent.live_arm))
        if day_no + 1 == warmup_days:
            frozen = EdgeTable.from_dict(agent.table.to_dict())
        day_no += 1
        print(f"done {sym} {day} [{qname}] {'counted' if counted else 'warm-up'}", flush=True)
    return rows, agent


def gate_a(df: pd.DataFrame) -> dict:
    c = df[df["counted"] & (df["fills"] >= MIN_FILLS)]
    head = c[(c["variant"] == "agent") & (c["queue"] == "headline")]
    stress = c[(c["variant"] == "agent") & (c["queue"] == "stress")]
    keys = set(zip(head["symbol"], head["day"]))
    jt = df[(df["variant"] == "join_touch") & (df["queue"] == "headline") & df["counted"]]
    jt = jt[np.array([k in keys for k in zip(jt["symbol"], jt["day"])], dtype=bool)]
    x = head["net_10bp"].to_numpy(float)
    mean, t = (float(x.mean()) if x.size else float("nan")), t_stat(x)
    per_sym = head.groupby("symbol")["net_10bp"].sum()
    share = float((x > 0).mean()) if x.size else float("nan")
    smean = float(stress["net_10bp"].mean()) if len(stress) else float("nan")
    agent_tot, jt_tot = float(x.sum()), float(jt["net_10bp"].sum())
    checks = {
        "1_mean_daily_net_pos_and_t_gt_3": {"mean_daily_net_usd": mean, "t": t, "pass": bool(x.size and mean > 0 and t > 3)},
        "2_three_symbols_positive": {"positive_symbols": int((per_sym > 0).sum()), "per_symbol": per_sym.round(4).to_dict(),
                                     "pass": bool((per_sym > 0).sum() >= 3)},
        "3_share_positive_ge_60pct": {"share_positive": share, "pass": bool(x.size and share >= 0.6)},
        "4_stress_queue_mean_pos": {"mean_daily_net_usd_q2": smean, "pass": bool(len(stress) and smean > 0)},
        "5_agent_beats_join_touch": {"agent_total": agent_tot, "join_touch_total": jt_tot,
                                     "pass": bool(x.size and agent_tot >= jt_tot)},
    }
    texts = ["mean daily net P&L > 0 and t > 3 across coin-days", "at least 3 coins with positive total net P&L",
             "at least 60% of coin-days positive", "mean daily net P&L > 0 at queue_mult 2.0",
             "agent total net P&L >= Join touch total"]
    values = [mean, int((per_sym > 0).sum()), share, smean, agent_tot - jt_tot]
    conditions = [{"id": f"A{i + 1}", "text": t, "value": (v if v == v else None), "pass": c["pass"]}
                  for i, (t, v, c) in enumerate(zip(texts, values, checks.values()))]
    return {"coin_days": int(x.size), "min_fills": MIN_FILLS, "checks": checks, "conditions": conditions,
            "pass": bool(x.size and all(v["pass"] for v in checks.values()))}


class _Fills:
    def __init__(self, fills):
        self.fills, self.markouts = fills, None


def write_dashboard_bundle(qname: str, qmult: float, kept: list, agents: dict, gate: dict | None,
                           screen_csv: str = "results/screen.csv", out_dir: str = "dashboard/runs"):
    """Dashboard Guide D12: run id wf-<UTC date>-q<queue_mult>, counted days only."""
    if not kept:
        print(f"no dashboard bundle for queue {qname}: no counted days yet")
        return None
    cfg = replace(QSConfig(), queue_mult=qmult)
    days, groups = [], {}
    for sym, day, var, res, arm in kept:
        extra = {"live_arm": arm} if var == "agent" else None
        days.append(report.day_row(res, sym, day, var, extra))
        groups.setdefault((sym, var), []).append(res)
    curves, hourly, markouts, wait, calib = {}, {}, [], {}, []
    for (sym, var), results in groups.items():
        curves[f"{sym}|{var}"] = report.curve(results)
        hourly[f"{sym}|{var}"] = report.hourly(results)
        nonempty = [r.fills for r in results if len(r.fills)]
        if not nonempty:
            continue
        fills = pd.concat(nonempty, ignore_index=True)
        markouts += report.markout_rows(_Fills(fills), sym, var)
        if var == "agent":
            wait[sym] = report.wait_hist_of(fills)
            calib += report.calib_rows(fills, sym)
    edge = [r for sym, a in agents.items() for r in report.edge_rows(a.table, sym)]
    agent_hist = [r for sym, a in agents.items() for r in report.agent_rows(a.history, sym)]
    screen = report.screen_rows(pd.read_csv(screen_csv)) if Path(screen_csv).exists() else None
    gates = {"A": {"conditions": gate["conditions"], "pass": gate["pass"]}} if gate else None
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    b = report.build_bundle(f"wf-{date}-q{qmult:g}", "walkforward", f"Agent walk-forward, queue {qmult:g}x ({qname})",
                            {"maker_fee_bps": cfg.maker_fee_bps, "latency_ms": cfg.latency_ms, "queue_mult": cfg.queue_mult,
                             "lot_usd": cfg.lot_usd, "q_max": cfg.q_max, "decision_ms": cfg.decision_ms},
                            days, curves=curves, hourly=hourly, markouts=markouts, wait_hist=wait or None,
                            calib=calib or None, edge=edge or None, agent=agent_hist or None, screen=screen, gates=gates)
    path = report.write_bundle(b, out_dir)
    print(f"dashboard bundle -> {path}")
    return path


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m scripts.run_agent_walkforward")
    ap.add_argument("--data", default="data")
    ap.add_argument("--symbols", default=None)
    ap.add_argument("--warmup-days", type=int, default=7)
    ap.add_argument("--export-state", action="store_true", help="save each coin's final headline table for the paper trader")
    ap.add_argument("--state", default="data/paper/state")
    ap.add_argument("--out", default="results/agent_walkforward.csv")
    args = ap.parse_args(argv)
    syms = args.symbols.split(",") if args.symbols else v2_universe()
    print(f"v2 universe: {', '.join(syms)}; warm-up days: {args.warmup_days}")

    rows, history, finals, kept, agents_by_q = [], {}, {}, {}, {}
    for qname, qm in QUEUES:
        for sym in syms:
            r, agent = run_symbol(sym, qname, qm, args.warmup_days, args.data, keep=kept.setdefault(qname, []))
            rows += r
            if agent is not None:
                history.setdefault(sym, {})[qname] = agent.history
                agents_by_q.setdefault(qname, {})[sym] = agent
                if qname == "headline":
                    finals[sym] = agent
    df = pd.DataFrame(rows)
    if df.empty:
        print("no usable days")
        return
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)
    Path("results/agent_history.json").write_text(json.dumps(history))
    g = gate_a(df)
    g["warmup_days"] = args.warmup_days
    n_counted = int((df["counted"] & (df["variant"] == "agent") & (df["queue"] == "headline")).sum())
    if n_counted == 0:
        g["status"] = "not evaluated: no counted days (each coin needs more than the warm-up days)"
    elif g["coin_days"] == 0:
        g["status"] = f"fail: the agent declined to trade (< {MIN_FILLS} fills on every counted day): no edge found"
    else:
        g["status"] = "pass" if g["pass"] else "fail"
    Path("results/gate_a.json").write_text(json.dumps(g, indent=2))

    for qname, qm in QUEUES:
        write_dashboard_bundle(qname, qm, kept.get(qname, []), agents_by_q.get(qname, {}),
                               g if qname == "headline" and n_counted else None)

    counted = df[df["counted"]]
    with pd.option_context("display.width", 160, "display.float_format", "{:,.2f}".format):
        if counted.empty:
            print(f"\nNo counted days: every coin has <= {args.warmup_days} usable days. Download more history "
                  f"(run_download_history.bat) and re-run.")
        else:
            tab = counted.groupby(["queue", "variant", "symbol"]).agg(
                days=("day", "count"), fills_per_day=("fills", "mean"), net_usd_per_day=("net_10bp", "mean"),
                net_bp_per_usd=("pnl_bps_of_volume", "mean"), positive_days=("net_10bp", lambda s: (s > 0).mean()),
                t=("net_10bp", t_stat))
            print(tab.to_string())
            hot = counted[(counted["fills"] >= MIN_FILLS) & (counted["pnl_bps_of_volume"] > 30)]
            if len(hot):
                print("\nSTOP AND REPORT: coin-day net edge above +30 bp per dollar traded (possible look-ahead):")
                print(hot[["symbol", "day", "variant", "queue", "pnl_bps_of_volume"]].to_string(index=False))
    print("\nGate A")
    for name, v in g["checks"].items():
        nums = ", ".join(f"{k}={val:.3f}" if isinstance(val, float) else f"{k}={val}" for k, val in v.items()
                         if k not in ("pass", "per_symbol"))
        print(f"  {'PASS' if v['pass'] else 'FAIL'}  {name}: {nums}")
    print(f"  coin-days counted: {g['coin_days']}   GATE A: {g['status'].upper()}")
    if n_counted == 0:
        print(fee_note())
        return
    c1 = g["checks"]["1_mean_daily_net_pos_and_t_gt_3"]
    print("\nSummary:\n"
          f"  1. {g['coin_days']} counted coin-days with >= {MIN_FILLS} fills after a {args.warmup_days}-day warm-up.\n"
          f"  2. The agent made {c1['mean_daily_net_usd']:.2f} USD per coin-day on average (t = {c1['t']:.2f}).\n"
          f"  3. {g['checks']['3_share_positive_ge_60pct']['share_positive']:.0%} of coin-days were positive.\n"
          f"  4. Against Join touch on the same days: {g['checks']['5_agent_beats_join_touch']['agent_total']:.2f} vs "
          f"{g['checks']['5_agent_beats_join_touch']['join_touch_total']:.2f} USD.\n"
          f"  5. Gate A {'passes' if g['pass'] else 'fails'}"
          + ("." if g["pass"] else ": per the guide, stop here; do not adjust the menu, buckets or thresholds."))
    print(fee_note())

    if args.export_state:
        st = Path(args.state)
        st.mkdir(parents=True, exist_ok=True)
        for sym, agent in finals.items():
            (st / f"{sym}_table.json").write_text(json.dumps(agent.table.to_dict()))
            (st / f"{sym}_agent.json").write_text(json.dumps({"live_arm": agent.live_arm, "tick": agent.tick}))
        print(f"exported {len(finals)} tables -> {st}")
    print(f"saved -> {args.out}, results/agent_history.json, results/gate_a.json")


if __name__ == "__main__":
    main()
