"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const statuses = {done: "Сделано", wip: "В работе", planned: "В планах"};
  const channelLabel = {alpha: "альфа", test: "тест"};
  const base = (() => { try { const u = new URL(window.LUNEX_PUBLIC_BASE); return u.protocol === "https:" && !u.username && !u.password && !u.search && !u.hash ? u : null; } catch { return null; } })();
  const fallback = window.LUNEX_FALLBACK_RELEASE || "https://github.com/maillunex-lang/LunexEconom/releases/latest";
  const download = $("apk-link");
  const testDownload = $("test-apk-link");
  const hex64 = /^[a-f0-9]{64}$/i;
  const semver = /^[0-9]+\.[0-9]+\.[0-9]+$/;
  const releasedUtc = /^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$/;
  download.href = fallback;
  download.textContent = "Последний релиз на GitHub";
  const show = (node, on) => { if (on) node.removeAttribute("hidden"); else node.setAttribute("hidden", ""); };
  const allowApk = (value) => {
    if (!base || typeof value !== "string") return null;
    try {
      const u = new URL(value);
      const prefix = base.pathname.replace(/\/+$/, "") + "/";
      if (u.protocol !== "https:" || u.origin !== base.origin || !u.pathname.startsWith(prefix) || !u.pathname.toLowerCase().endsWith(".apk") || u.username || u.password || u.search || u.hash || /%(?:2e|2f|5c|00)/i.test(u.pathname) || u.pathname.includes("..") || u.pathname.includes("\\") || u.pathname.includes("//")) return null;
      return u.href;
    } catch { return null; }
  };
  const txt = (node, value) => { node.textContent = String(value); };
  const releaseEntries = (m) => {
    const items = Array.isArray(m.releases) ? m.releases : Array.isArray(m.history) ? m.history : [];
    if (items.length) return items.slice(0, 5).map(r => ({ version: r.version_name || r.version || "Версия", date: r.released || r.date || "", notes: r.notes || "" }));
    return [{version: m.version_name || "Версия", date: m.released || "", notes: m.notes || "Подробности обновления не указаны."}];
  };
  const fmt = value => Number.isInteger(value) && value > 0 ? `${(value / 1048576).toFixed(1).replace(".", ",")} МиБ` : "Не указан";
  const parseDate = value => {
    if (typeof value !== "string" || !releasedUtc.test(value)) return "Не указана";
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? "Не указана" : new Intl.DateTimeFormat("ru-RU", { day:"numeric", month:"long", year:"numeric", timeZone:"UTC" }).format(d);
  };
  const paintReleases = (entries) => {
    const journal = $("journal-list"); journal.replaceChildren();
    if (!entries.length) { const p = document.createElement("p"); p.textContent = "Записей журнала пока нет."; journal.append(p); return; }
    entries.forEach(e => {
      const article = document.createElement("article"); article.className = "journal-card";
      const h = document.createElement("h3"); h.textContent = e.version;
      const p = document.createElement("p"); p.textContent = String(e.notes || "Нет заметок об изменениях.");
      const small = document.createElement("small"); small.textContent = e.date ? parseDate(e.date) : "";
      article.append(h, small, p); journal.append(article);
    });
  };
  const paintHash = (value) => {
    const ok = typeof value === "string" && hex64.test(value);
    txt($("apk-hash"), ok ? value.toLowerCase() : "Не указан");
    show($("copy-sha"), ok);
    $("copy-sha").textContent = "Скопировать SHA-256";
  };
  const paintPrevious = (prev) => {
    if (!prev) { show($("previous-release"), false); return; }
    show($("previous-release"), true);
    const link = $("previous-link");
    link.href = prev.apk_url;
    link.textContent = prev.channel === "test" ? `${prev.version_name} · тест` : prev.version_name;
    txt($("previous-hash"), prev.sha256);
  };
  const hideTestChrome = () => {
    show($("channel-banner"), false);
    show(testDownload, false);
    testDownload.href = fallback;
    download.classList.add("primary");
    download.classList.remove("subtle");
  };
  const record = (raw) => {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
    if (raw.channel !== "alpha" && raw.channel !== "test") return null;
    if (typeof raw.version_name !== "string" || !semver.test(raw.version_name)) return null;
    if (!Number.isInteger(raw.version_code) || raw.version_code < 1 || raw.version_code > 2100000000) return null;
    if (typeof raw.released !== "string" || !releasedUtc.test(raw.released)) return null;
    const releasedAt = new Date(raw.released);
    if (Number.isNaN(releasedAt.getTime()) || releasedAt.toISOString().slice(0, 19) + "Z" !== raw.released) return null;
    const url = allowApk(raw.apk_url);
    if (!url) return null;
    if (!Number.isInteger(raw.size) || raw.size < 1 || raw.size > 512 * 1024 * 1024) return null;
    if (typeof raw.sha256 !== "string" || !hex64.test(raw.sha256)) return null;
    if (typeof raw.notes !== "string" || !raw.notes.trim() || raw.notes.length > 4000 || /[\u0000-\u0008\u000B\u000C\u000E-\u001F]/.test(raw.notes) || !/[А-Яа-яЁё]/.test(raw.notes)) return null;
    return { channel: raw.channel, version_name: raw.version_name, version_code: raw.version_code, released: raw.released, apk_url: url, size: raw.size, sha256: raw.sha256.toLowerCase(), notes: raw.notes };
  };
  const parseLatest = (raw) => {
    if (!raw || typeof raw !== "object" || Array.isArray(raw) || raw.schema !== 1 || !Object.prototype.hasOwnProperty.call(raw, "previous")) return null;
    const current = record(raw);
    if (!current) return null;
    if (raw.previous === null) return Object.assign(current, { previous: null });
    const previous = record(raw.previous);
    if (!previous) return null;
    return Object.assign(current, { previous });
  };
  const paintLatest = (build) => {
    const test = build.channel === "test";
    show($("channel-banner"), test);
    show(testDownload, test);
    if (test) {
      download.href = fallback;
      download.textContent = "Последний релиз на GitHub";
      download.classList.remove("primary");
      download.classList.add("subtle");
      testDownload.href = build.apk_url;
      testDownload.textContent = "Скачать тестовую сборку";
      $("release-status").textContent = "Показана тестовая сборка из latest.json. Для обычной игры она не предназначена.";
    } else {
      hideTestChrome();
      download.href = build.apk_url;
      download.textContent = "Скачать для Android";
      $("release-status").textContent = "Последняя проверенная сборка · данные из latest.json";
    }
    txt($("apk-version"), build.version_name);
    txt($("apk-code"), String(build.version_code));
    txt($("apk-channel"), channelLabel[build.channel]);
    txt($("apk-size"), fmt(build.size));
    txt($("apk-date"), parseDate(build.released));
    paintHash(build.sha256);
    txt($("whats-new"), build.notes);
    paintPrevious(build.previous);
    const entries = [{ version: build.version_name, date: build.released, notes: build.notes }];
    if (build.previous) entries.push({ version: build.previous.channel === "test" ? `${build.previous.version_name} · тест` : build.previous.version_name, date: build.previous.released, notes: build.previous.notes });
    paintReleases(entries);
  };
  const clearBuild = (status) => {
    hideTestChrome();
    show($("previous-release"), false);
    paintHash("");
    txt($("apk-version"), "Нет данных");
    txt($("apk-code"), "Не указан");
    txt($("apk-channel"), "Не указан");
    txt($("apk-size"), "Не указан");
    txt($("apk-date"), "Не указана");
    $("release-status").textContent = status;
  };
  async function loadLatest() {
    const response = await fetch("./latest.json", {cache:"no-store"});
    if (!response.ok) return false;
    const build = parseLatest(await response.json());
    if (!build) return false;
    paintLatest(build);
    return true;
  }
  async function loadManifest() {
    const response = await fetch("./update.json", {cache:"no-store"});
    if (!response.ok) throw Error("no manifest");
    const m = await response.json();
    const url = allowApk(m.apk_url);
    if (!url) throw Error("unsafe APK URL");
    hideTestChrome();
    show($("previous-release"), false);
    download.href = url; download.textContent = "Скачать для Android";
    $("release-status").textContent = "Доступен APK · данные из манифеста";
    txt($("apk-version"), m.version_name || "Не указана");
    txt($("apk-code"), Number.isInteger(m.version_code) ? String(m.version_code) : "Не указан");
    txt($("apk-channel"), "Не указан");
    txt($("apk-size"), fmt(m.size));
    txt($("apk-date"), parseDate(m.released));
    paintHash(m.sha256);
    txt($("whats-new"), m.notes || "Заметки не опубликованы.");
    paintReleases(releaseEntries(m));
  }
  async function loadRelease() {
    try {
      if (await loadLatest()) return;
    } catch { /* latest.json отсутствует или повреждён: запасной путь ниже. */ }
    try {
      await loadManifest();
    } catch {
      clearBuild("Манифест недоступен или ссылка отклонена. Откройте страницу последнего релиза на GitHub.");
      download.href = fallback;
      download.textContent = "Последний релиз на GitHub";
      $("whats-new").textContent = "Сведения об обновлениях появятся после публикации проверенной сборки.";
      paintReleases([]);
    }
  }
  $("copy-sha").addEventListener("click", async () => {
    const value = $("apk-hash").textContent.trim();
    if (!hex64.test(value)) return;
    let copied = false;
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(value);
        copied = true;
      }
    } catch { copied = false; }
    if (!copied) {
      const area = document.createElement("textarea");
      area.value = value;
      area.setAttribute("readonly", "");
      document.body.append(area);
      area.select();
      try { copied = document.execCommand("copy"); } catch { copied = false; }
      area.remove();
    }
    $("copy-sha").textContent = copied ? "Скопировано" : "Не удалось скопировать";
  });
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
  void loadRelease(); void loadRoadmap();
})();
