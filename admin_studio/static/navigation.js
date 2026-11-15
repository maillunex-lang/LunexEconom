"use strict";
/* World Studio 2.0: responsive, accessible navigation; no credentials stored. */
(() => {
  const nav = document.getElementById("studio-nav");
  const panels = [...document.querySelectorAll("#studio-main > section[data-panel]")];
  const allowed = new Set(["overview", "dashboard", "online", "flags", "parameters", "revisions", "maintenance", "players", "cities", "world", "assets", "goods", "deposits", "patch", "audit"]);
  function show(view, updateHistory = true) {
    if (!allowed.has(view)) view = "overview";
    panels.forEach(panel => { panel.hidden = panel.dataset.panel !== view; });
    nav.querySelectorAll("button[data-view]").forEach(button => {
      const selected = button.dataset.view === view;
      button.setAttribute("aria-pressed", String(selected));
      button.classList.toggle("selected", selected);
    });
    if (updateHistory) history.replaceState(null, "", "#" + view);
    const selected = nav.querySelector('button[data-view="' + view + '"]');
    if (selected) selected.scrollIntoView({block:"nearest", inline:"nearest", behavior:"auto"});
  }
  nav.addEventListener("click", event => {
    const button = event.target.closest("button[data-view]");
    if (button && nav.contains(button)) show(button.dataset.view);
  });
  window.addEventListener("hashchange", () => show(location.hash.slice(1), false));
  show(location.hash.slice(1), false);
})();