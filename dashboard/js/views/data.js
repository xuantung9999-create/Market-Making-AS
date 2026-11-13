/* data.js: Data > Recorder health (Dashboard Redesign R8). Reads the book bundle's coverage, the run index and SITE. */

function drawDataTiles() {
  const b = Source.book, cov = (b && b.coverage) || [];
  const clean = cov.reduce((a, r) => a + r.hours, 0), gapMin = cov.reduce((a, r) => a + r.gap_minutes, 0);
  const days = new Set(cov.map(r => r.date)).size;
  const tiles = [
    ["Coins recorded", b ? fmt(b.symbols.length, 0) : "–", "", b ? "in the newest book bundle" : "no book bundle yet"],
    ["Days recorded", b ? fmt(days, 0) : "–", "", "UTC dates with any data"],
    ["Clean hours", b ? fmt(clean, 0) : "–", "", "all coins together"],
    ["Gap time", b ? fmt(gapMin / 60, 1) + " h" : "–", "", "book gaps over 120 s"],
    ["Tests passing", isNum(SITE.testsPassed) ? fmt(SITE.testsPassed, 0) : "–", "", "set in js/core.js at build time"],
  ];
  fillHtml("dh-tiles", tiles.map(t => `<div class="tile"><div class="k">${t[0]}</div><div class="v ${t[2]}">${t[1]}</div><div class="s">${t[3]}</div></div>`).join(""));
}

function drawDataCoverage() {
  const cov = Source.book && Source.book.coverage;
  if (!cov || !cov.length) return emptyPanel("dh-cov", Source.bookError || "No recorded book yet. Run the recorder, then run_build_book.bat.");
  const syms = [...new Set(cov.map(r => r.symbol))].sort(), dates = [...new Set(cov.map(r => r.date))].sort();
  const z = syms.map(s => dates.map(d => { const r = cov.find(x => x.symbol === s && x.date === d); return r ? r.hours : null; }));
  const text = syms.map(s => dates.map(d => { const r = cov.find(x => x.symbol === s && x.date === d); return r ? `${r.hours} clean hours, ${fmt(r.gap_minutes, 1)} min of gaps` : "no data"; }));
  deskPlot("dh-cov", [{ type: "heatmap", x: dates, y: syms, z, text, hoverinfo: "text", zmin: 0, zmax: 24, xgap: 2, ygap: 2,
    colorscale: [[0, "#1a2433"], [0.5, "#2b6cb0"], [0.83, "#38bdf8"], [1, "#e0f2fe"]], colorbar: { title: { text: "clean hours", side: "right" }, thickness: 10, tickvals: [0, 12, 20, 24] } }],
    { height: Math.max(180, 44 * syms.length + 100), margin: { l: 90, r: 16, t: 10, b: 60 }, hovermode: "closest",
      xaxis: axis("UTC date", { type: "category" }), yaxis: Object.assign(axis(""), { autorange: "reversed" }) });
}

function drawDataBundles() {
  const rows = Source.list().slice().sort((a, c) => a.built_utc < c.built_utc ? 1 : -1);
  if (!rows.length) return emptyPanel("dh-bundles");
  fillHtml("dh-bundles", `<table><thead><tr><th>Bundle</th><th>Kind</th><th>Built (UTC)</th><th>Age</th><th>Days</th><th>Coins</th></tr></thead><tbody>${rows.map(r =>
    `<tr><td>${esc(r.run_id)}</td><td>${badge(r.kind)}</td><td>${esc(r.built_utc)}</td><td>${esc(ago(r.built_utc).replace("built ", ""))}</td><td>${isNum(r.n_days) ? fmt(r.n_days, 0) : "–"}</td><td>${(r.symbols || []).length}</td></tr>`).join("")}</tbody></table>`);
}

function drawData() {
  const body = $("desk-body-health"), msg = $("desk-msg-health");
  msg.hidden = true; body.hidden = false;
  drawDataTiles(); drawDataCoverage(); drawDataBundles();
}
register("health", drawData);
