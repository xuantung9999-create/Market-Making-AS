/* desk_pending.js: placeholders for views not built yet (Dashboard Guide D9-D11, Redesign R5-R8).
   Each later task creates js/views/<name>.js, registers its view, and removes it from this list. */
["signals", "market", "simlive", "health"].forEach(v => {
  if (!draw[v]) register(v, () => deskBundle(v));
});
["live", "book"].forEach(v => { if (!draw[v]) register(v, () => {}, false); });   // these read no run
