/* pnl.js: Desk > P&L (Dashboard Guide Task D5). Reads only: days, summary, hourly. */

function drawPnlWaterfall(b) {
  const ds = filteredDays(b);
  if (!ds.length) return emptyPanel("pnl-wf");
  const sum = k => ds.reduce((a, d) => a + (isNum(d[k]) ? d[k] : 0), 0);
  const sc = sum("spread_capture"), inv = sum("inventory_pnl"), fees = sum("fees"), net = sum("pnl");
  deskPlot("pnl-wf", [{
    type: "waterfall", orientation: "v", measure: ["relative", "relative", "relative", "total"],
    x: ["Spread capture", "Inventory P&L", "Fees", "Net"], y: [sc, inv, -fees, net],
    text: [sc, inv, -fees, net].map(v => sign(v)), textposition: "outside",
    increasing: { marker: { color: PROFIT } }, decreasing: { marker: { color: LOSS } },
    totals: { marker: { color: pnlColor(net) } }, connector: { line: { color: C.line } },
    hovertemplate: "%{x}: %{y:,.2f} USD<extra></extra>",
  }], { yaxis: axis("USD", { zeroline: true, zerolinecolor: C.muted }), showlegend: false });
}

function drawPnlDaily(b) {
  const f = Source.filter, ds = filteredDays(b);
  if (!ds.length) return emptyPanel("pnl-daily");
  const dates = [...new Set(ds.map(d => d.date))].sort();
  const syms = f.symbol === "ALL" ? Source.symbolsOf(b) : [f.symbol];
  const tr = syms.map((s, i) => {
    const by = Object.fromEntries(ds.filter(d => d.symbol === s).map(d => [d.date, d.pnl]));
    return { type: "bar", name: s, x: dates, y: dates.map(t => by[t] ?? null), marker: { color: SERIES[i % SERIES.length] },
             hovertemplate: `${s} %{x}: %{y:,.2f} USD<extra></extra>` };
  });
  const tot = dates.map(t => ds.filter(d => d.date === t).reduce((a, d) => a + (d.pnl || 0), 0));
  const ma = tot.map((_, i) => { const w = tot.slice(Math.max(0, i - 6), i + 1); return w.reduce((a, x) => a + x, 0) / w.length; });
  tr.push({ type: "scatter", mode: "lines", name: "7-day mean (total)", x: dates, y: ma, line: { color: C.text, width: 2 } });
  deskPlot("pnl-daily", tr, { barmode: "relative", xaxis: axis("UTC date", { type: "date" }), yaxis: axis("USD per day", { zeroline: true, zerolinecolor: C.muted }) });
}

function drawPnlHeat(b) {
  const f = Source.filter, h = section(b, "hourly");
  if (!h) { emptyPanel("pnl-heat"); emptyPanel("pnl-heat-edge"); return; }
  const syms = (f.symbol === "ALL" ? Source.symbolsOf(b) : [f.symbol]).filter(s => h[`${s}|${f.variant}`]);
  if (!syms.length) { emptyPanel("pnl-heat"); emptyPanel("pnl-heat-edge"); return; }
  const days = s => Math.max(1, (section(b, "days") || []).filter(d => d.symbol === s && d.variant === f.variant).length);
  const hrs = [...Array(24).keys()];
  const z = syms.map(s => h[`${s}|${f.variant}`].pnl.map(v => v / days(s)));
  const scale = [[0, LOSS], [0.5, C.panel], [1, PROFIT]];
  const lim = Math.max(1e-9, ...z.flat().map(Math.abs));
  deskPlot("pnl-heat", [{ type: "heatmap", x: hrs, y: syms, z, zmin: -lim, zmax: lim, colorscale: scale,
    colorbar: { title: { text: "USD/day" } }, hovertemplate: "%{y} %{x}:00 UTC: %{z:,.2f} USD/day<extra></extra>" }],
    { xaxis: axis("UTC hour", { dtick: 2 }), yaxis: axis("") });
  const ze = syms.map(s => h[`${s}|${f.variant}`].net_edge_bp || null);
  if (ze.some(r => !r)) return emptyPanel("pnl-heat-edge");
  const le = Math.max(1e-9, ...ze.flat().map(Math.abs));
  deskPlot("pnl-heat-edge", [{ type: "heatmap", x: hrs, y: syms, z: ze, zmin: -le, zmax: le, colorscale: scale,
    colorbar: { title: { text: "bp" } }, hovertemplate: "%{y} %{x}:00 UTC: %{z:,.2f} bp<extra></extra>" }],
    { xaxis: axis("UTC hour", { dtick: 2 }), yaxis: axis("") });
}

function drawPnlStats(b) {
  const f = Source.filter, rows = (section(b, "summary") || []).filter(r => r.variant === f.variant);
  if (!rows.length) return emptyPanel("pnl-stats");
  rows.sort((a, c) => (a.symbol === "ALL" ? -1 : c.symbol === "ALL" ? 1 : a.symbol < c.symbol ? -1 : 1));
  const tf = x => isNum(x) ? fmt(x, 2) : "too few days";
  const body = rows.map(r => `<tr><td>${esc(r.symbol === "ALL" ? "All coins" : r.symbol)}</td><td>${fmt(r.days, 0)}</td>
    <td class="${pnlCls(r.pnl_total)}">${sign(r.pnl_total)}</td><td class="${pnlCls(r.pnl_mean_day)}">${sign(r.pnl_mean_day)}</td>
    <td>${isNum(r.pnl_std_day) ? fmt(r.pnl_std_day) : "–"}</td><td>${tf(r.t_stat)}</td>
    <td>${isNum(r.sharpe_ann) ? fmt(r.sharpe_ann) + " ± " + fmt(r.sharpe_se) : "too few days"}</td>
    <td>${pct(r.hit_rate)}</td><td>${isNum(r.profit_factor) ? fmt(r.profit_factor) : "–"}</td>
    <td class="${pnlCls(r.max_dd)}">${isNum(r.max_dd) ? sign(r.max_dd) : "–"}</td>
    <td class="${pnlCls(r.net_bp_per_usd)}">${isNum(r.net_bp_per_usd) ? sign(r.net_bp_per_usd) : "–"}</td>
    <td>${isNum(r.turnover_day) ? fmt(r.turnover_day, 1) : "–"}</td>
    <td>${isNum(r.var95_day) ? sign(r.var95_day) : "needs 20 days"}</td><td>${isNum(r.es95_day) ? sign(r.es95_day) : "–"}</td></tr>`).join("");
  fillHtml("pnl-stats", `<table><thead><tr><th>Coin</th><th>Counted days</th><th>Total (USD)</th><th>Mean/day (USD)</th><th>Std/day (USD)</th>
    <th>t-stat</th><th>Sharpe (ann.)</th><th>Hit rate</th><th>Profit factor</th><th>Max DD (USD)</th><th>Net bp per $</th>
    <th>Turnover/day (× cap)</th><th>VaR 95%/day</th><th>ES 95%/day</th></tr></thead><tbody>${body}</tbody></table>`);
}

function drawPnlHist(b) {
  const ds = filteredDays(b).filter(d => (d.fills || 0) >= 20);
  if (!ds.length) return emptyPanel("pnl-hist", "No day with 20 or more fills in this selection");
  const x = ds.map(d => d.pnl), mean = x.reduce((a, v) => a + v, 0) / x.length;
  deskPlot("pnl-hist", [{ type: "histogram", x, nbinsx: 30, marker: { color: rgba(SERIES[0], 0.7) }, hovertemplate: "%{x} USD: %{y} days<extra></extra>" }],
    { xaxis: axis("Daily net P&L (USD)"), yaxis: axis("Days"), showlegend: false,
      shapes: [{ type: "line", x0: 0, x1: 0, yref: "paper", y0: 0, y1: 1, line: { color: C.muted, dash: "dot" } },
               { type: "line", x0: mean, x1: mean, yref: "paper", y0: 0, y1: 1, line: { color: pnlColor(mean), width: 2 } }],
      annotations: [{ x: mean, yref: "paper", y: 0.97, text: `mean ${sign(mean)} USD`, showarrow: false, xanchor: "right", yanchor: "top", font: { color: pnlColor(mean) } }] });
}

function drawPnl() {
  const b = deskBundle("pnl");
  if (!b) return;
  drawPnlWaterfall(b); drawPnlDaily(b); drawPnlHeat(b); drawPnlStats(b); drawPnlHist(b);
}
register("pnl", drawPnl);
