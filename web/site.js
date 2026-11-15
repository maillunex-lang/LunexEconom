"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const statuses = {done: "Сделано", wip: "В работе", planned: "В планах"};
  const base = (() => { try { const u = new URL(window.LUNEX_PUBLIC_BASE); return u.protocol === "https:" && !u.username && !u.password && !u.search && !u.hash ? u : null; } catch { return null; } })();
  const fallback = window.LUNEX_FALLBACK_RELEASE || "https://github.com/maillunex-lang/LunexEconom/releases/latest";
  const download = $("apk-link");
  download.href = fallback;
  download.textContent = "Последний релиз на GitHub";
  const allowApk = (value) => {
    if (!base || typeof value !== "string") return null;
    try {
      const u = new URL(value);
      const prefix = base.pathname.replace(/\/+$/, "") + "/";
      if (u.protocol !== "https:" || u.origin !== base.origin || !u.pathname.startsWith(prefix) || !u.pathname.toLowerCase().endsWith(".apk") || u.username || u.password || u.search || u.hash || /%(?:2e|2f|5c|00)/i.test(u.pathname) || u.pathname.includes("..") || u.pathname.includes("\\")) return null;
      return u.href;
    } catch { return null; }
  };
  const txt = (node, value) => { node.textContent = String(value); };
  const releaseEntries = (m) => {
    const items = Array.isArray(m.releases) ? m.releases : Array.isArray(m.history) ? m.history : [];
    if (items.length) return items.slice(0, 5).map(r => ({ version: r.version_name || r.version || "Версия", date: r.released || r.date || "", notes: r.notes || "" }));
    return [{version: m.version_name || "Версия", date: m.released || "", notes: m.notes || "Подробности обновления не указаны."}];
  };
  const fmt = value => Number.isFinite(value) && value > 0 ? `${(value / 1048576).toFixed(1).replace(".", ",")} МиБ` : "Не указан";
  const parseDate = value => {
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? "Не указана" : new Intl.DateTimeFormat("ru-RU", { day:"numeric", month:"long", year:"numeric", timeZone:"UTC" }).format(d);
  };
  const paintReleases = (entries) => {
    const journal = $("journal-list"); journal.replaceChildren();
    entries.forEach(e => {
      const article = document.createElement("article"); article.className = "journal-card";
      const h = document.createElement("h3"); h.textContent = e.version;
      const p = document.createElement("p"); p.textContent = String(e.notes || "Нет заметок об изменениях.");
      const small = document.createElement("small"); small.textContent = e.date ? parseDate(e.date) : "";
      article.append(h, small, p); journal.append(article);
    });
  };
  async function loadManifest() {
    try {
      const response = await fetch("./update.json", {cache:"no-store"});
      if (!response.ok) throw Error("no manifest");
      const m = await response.json();
      const url = allowApk(m.apk_url);
      if (!url) throw Error("unsafe APK URL");
      download.href = url; download.textContent = "Скачать для Android";
      $("release-status").textContent = "Доступен APK · данные из манифеста";
      txt($("apk-version"), m.version_name || "Не указана");
      txt($("apk-size"), fmt(m.size));
      txt($("apk-date"), parseDate(m.released));
      txt($("apk-hash"), /^[a-f0-9]{64}$/i.test(m.sha256 || "") ? m.sha256 : "Не указан");
      txt($("whats-new"), m.notes || "Заметки не опубликованы.");
      paintReleases(releaseEntries(m));
    } catch {
      $("release-status").textContent = "Манифест недоступен или ссылка отклонена. Откройте страницу последнего релиза на GitHub.";
      $("whats-new").textContent = "Сведения об обновлениях появятся после публикации манифеста.";
      paintReleases([]);
    }
  }
  const statusTag = status => {
    const span = document.createElement("span"); span.className = `status status-${status}`; span.textContent = statuses[status]; return span;
  };
  const createMilestone = (m) => {
    const li = document.createElement("li"); li.className = `milestone milestone-${m.status}`;
    const mark = document.createElement("span"); mark.className = "milestone-mark"; mark.setAttribute("aria-hidden", "true"); mark.textContent = m.status === "done" ? "✓" : m.status === "wip" ? "◉" : "○";
    const title = document.createElement("strong"); title.textContent = m.title;
    li.append(mark, title, statusTag(m.status)); return li;
  };
  const createPhase = phase => {
    const details = document.createElement("details"); details.className = "phase-card";
    const summary = document.createElement("summary");
    const ring = document.createElement("span"); ring.className = "progress-ring"; ring.style.setProperty("--progress", String(phase.progress));
    ring.textContent = `${phase.progress}%`; ring.setAttribute("aria-label", `Готовность ${phase.progress} процентов`);
    const name = document.createElement("span"); name.className = "phase-heading";
    const title = document.createElement("strong"); title.textContent = phase.title;
    const sub = document.createElement("small"); sub.textContent = `${phase.items.length} пунктов`;
    name.append(title, sub); summary.append(ring, name, statusTag(phase.status));
    const ul = document.createElement("ul"); ul.className = "phase-items";
    phase.items.forEach(item => { const li = document.createElement("li"); li.textContent = item.title; li.append(statusTag(item.status)); ul.append(li); });
    details.append(summary, ul); return details;
  };
  async function loadRoadmap() {
    try {
      const response = await fetch("./roadmap.json", {cache:"no-store"});
      if (!response.ok) throw Error("no roadmap");
      const data = await response.json();
      if (!Array.isArray(data.phases) || !data.phases.length || !Array.isArray(data.milestones) || data.phases.some(p => !Number.isInteger(p.progress) || p.progress < 0 || p.progress > 100 || !Array.isArray(p.items) || !statuses[p.status]) || data.milestones.some(m => !statuses[m.status])) throw Error("invalid roadmap");
      $("roadmap-milestones").replaceChildren(...data.milestones.map(createMilestone));
      $("roadmap-phases").replaceChildren(...data.phases.map(createPhase));
      const percent = Math.round(data.phases.reduce((acc, p) => acc + p.progress, 0) / data.phases.length);
      txt($("roadmap-progress"), `${percent}%`);
      txt($("roadmap-updated"), data.updated || "Дата не указана");
      $("roadmap-source").textContent = "Данные дорожной карты загружены из roadmap.json";
    } catch {
      $("roadmap-source").textContent = "Не удалось загрузить roadmap.json. Ниже показана информация о доступности дорожной карты.";
      $("roadmap-phases").textContent = "Дорожная карта временно недоступна. Попробуйте открыть страницу позже.";
    }
  }
  const themeToggle = $("theme-toggle");
  const updateTheme = theme => { document.documentElement.dataset.theme = theme; themeToggle.setAttribute("aria-pressed", String(theme === "light")); themeToggle.textContent = theme === "light" ? "Тёмная тема" : "Светлая тема"; };
  updateTheme(window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
  themeToggle.addEventListener("click", () => updateTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"));
  void loadManifest(); void loadRoadmap();
})();
