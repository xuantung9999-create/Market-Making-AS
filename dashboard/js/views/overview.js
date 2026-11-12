/* overview.js: Desk > Overview (Dashboard Guide Task D4).
   Reads only: days, summary, curves, gates. Every statistic comes precomputed from mm/report.py. */

function sparkline(vals, w = 120, h = 26) {
  if (!vals || vals.length < 2) return "–";
  const step = Math.max(1, Math.floor(vals.length / 120));
  const v = vals.filter((_, i) => i % step === 0 || i === vals.length - 1);
  let lo = Math.min(0, ...v), hi = Math.max(0, ...v);
  if (hi === lo) hi = lo + 1;
  const X = i => (i / (v.length - 1)) * (w - 2) + 1, Y = y => h - 2 - ((y - lo) / (hi - lo)) * (h - 4);
  const pts = v.map((y, i) => `${X(i).toFixed(1)},${Y(y).toFixed(1)}`).join(" ");
  const col = pnlColor(v[v.length - 1]);
  return `<svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true">
    <line x1="0" x2="${w}" y1="${Y(0).toFixed(1)}" y2="${Y(0).toFixed(1)}" stroke="${C.line}" stroke-width="1"/>
    <polyline points="${pts}" fill="none" stroke="${col}" stroke-width="1.5"/></svg>`;
}

function drawOverviewTiles(b) {
  const f = Source.filter, r = summaryRow(b, f.symbol, f.variant);
  if (!r) return emptyPanel("ov-tiles");
  const tooFew = "too few days";
  const tiles = [
    ["Total net P&L (USD)", sign(r.pnl_total), pnlCls(r.pnl_total), "after maker fees"],
    ["Net bp per $ traded", isNum(r.net_bp_per_usd) ? sign(r.net_bp_per_usd, 2) : "–", pnlCls(r.net_bp_per_usd), "P&L ÷ notional × 10⁴"],
    ["t-statistic", isNum(r.t_stat) ? fmt(r.t_stat, 2) : tooFew, "", isNum(r.t_stat) ? "|t| > 2: unlikely to be luck" : "needs 5 counted days"],
    ["Hit rate", pct(r.hit_rate), "", "share of days with P&L > 0"],
    ["Max drawdown (USD)", isNum(r.max_dd) ? sign(r.max_dd) : "–", isNum(r.max_dd) && r.max_dd < 0 ? "neg" : "", "on daily P&L"],
    ["Counted days", isNum(r.days) ? fmt(r.days, 0) : "–", "", "days with ≥ 20 fills"],
  ];
  fillHtml("ov-tiles", tiles.map(t => `<div class="tile"><div class="k">${t[0]}</div><div class="v ${t[2]}">${t[1]}</div><div class="s">${t[3]}</div></div>`).join(""));
}

function drawOverviewBlotter(b) {
  const f = Source.filter, v = f.variant;
  const days = section(b, "days");
  if (!days) return emptyPanel("ov-blotter");
  const curves = section(b, "curves") || {};
  const syms = f.symbol === "ALL" ? Source.symbolsOf(b) : [f.symbol];
  const rows = syms.map(sym => {
    const ds = days.filter(d => d.symbol === sym && d.variant === v).sort((a, c) => a.date < c.date ? -1 : 1);
    if (!ds.length) return "";
    const last = ds[ds.length - 1], s = summaryRow(b, sym, v) || {}, cv = curves[`${sym}|${v}`];
    const inv = cv && cv.q && cv.q.length ? fmt(cv.q[cv.q.length - 1], 0) : "–";
    const stop = last.loss_stop === undefined ? "–" : last.loss_stop ? "STOP" : "no";
    return `<tr>
      <td>${esc(sym)}</td><td>${esc(last.date)}</td>
      <td>${inv}</td>
      <td class="${pnlCls(last.pnl)}">${sign(last.pnl)}</td>
      <td class="${pnlCls(s.pnl_total)}">${sign(s.pnl_total)}</td>
      <td>${isNum(s.fills_day) ? fmt(s.fills_day, 0) : "–"}</td>
      <td class="${pnlCls(s.net_edge_bp)}">${isNum(s.net_edge_bp) ? sign(s.net_edge_bp, 2) : "–"}</td>
      <td>${isNum(s.mk_60) ? sign(s.mk_60, 2) : "–"}</td>
      <td>${isNum(last.live_arm) ? last.live_arm : "–"}</td>
      <td class="${last.loss_stop ? "flag-on" : ""}">${stop}</td>
      <td>${cv ? sparkline(cv.pnl) : "–"}</td></tr>`;
  }).join("");
  fillHtml("ov-blotter", `<table><thead><tr>
    <th>Symbol</th><th>Last day (UTC)</th><th>Inventory (lots)</th><th>P&amp;L last day (USD)</th><th>P&amp;L total (USD)</th>
    <th>Fills / day</th><th>Net edge (bp)</th><th>60 s markout (bp)</th><th>Live arm</th><th>Loss stop</th><th>Cumulative P&amp;L</th>
    </tr></thead><tbody>${rows}</tbody></table>`);
}

function drawOverviewCurve(b) {
  const f = Source.filter, v = f.variant, curves = section(b, "curves");
  if (!curves) return emptyPanel("ov-cum");
  const syms = f.symbol === "ALL" ? Source.symbolsOf(b) : [f.symbol];
  const tr = [];
  syms.forEach((sym, i) => {
    const c = curves[`${sym}|${v}`];
    if (c) tr.push({ x: c.t, y: c.pnl, name: sym, mode: "lines", line: { width: 1.5, color: SERIES[i % SERIES.length] },
                     hovertemplate: `${sym} %{y:,.2f} USD<extra></extra>` });
  });
  const all = curves[`ALL|${v}`];
  if (f.symbol === "ALL" && all) tr.push({ x: all.t, y: all.pnl, name: "Total", mode: "lines", line: { width: 2.5, color: C.text },
                                           hovertemplate: "Total %{y:,.2f} USD<extra></extra>" });
  if (!tr.length) return emptyPanel("ov-cum");
  deskPlot("ov-cum", tr, { xaxis: axis("UTC", { type: "date" }), yaxis: axis("USD", { zeroline: true, zerolinecolor: C.muted }) });
}

function drawOverviewGates(b) {
  const g = section(b, "gates");
  if (!g) return emptyPanel("ov-gates", "Not evaluated yet");
  const mark = p => p === true ? '<span class="mark pass">PASS</span>' : p === false ? '<span class="mark fail">FAIL</span>' : '<span class="mark na">n/a</span>';
  let html = "";
  for (const name of ["A", "B"]) {
    const gate = g[name];
    html += `<tr><th>Gate ${name}</th><th>${gate ? "" : "not evaluated yet"}</th><th></th><th>${gate ? mark(gate.pass) : ""}</th></tr>`;
    if (!gate) continue;
    for (const c of gate.conditions || [])
      html += `<tr><td>${esc(c.id)}</td><td>${esc(c.text)}</td><td>${isNum(c.value) ? fmtP(c.value) : "–"}</td><td>${mark(c.pass)}</td></tr>`;
  }
  fillHtml("ov-gates", `<table class="gates"><tbody>${html}</tbody></table>`);
}

function drawOverview() {
  const b = deskBundle("overview");
  if (!b) return;
  drawOverviewTiles(b);
  drawOverviewBlotter(b);
  drawOverviewCurve(b);
  drawOverviewGates(b);
}
register("overview", drawOverview);
