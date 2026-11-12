/* desk_pending.js: placeholders for Desk views not built yet (Dashboard Guide Tasks D5-D11).
   Each later task creates js/views/<name>.js, registers its view, and removes it from this list. */
["signals", "market", "simlive", "health"].forEach(v => {
  if (!draw[v]) register(v, () => deskBundle(v));
});
