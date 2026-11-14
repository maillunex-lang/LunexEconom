"use strict";
/* Game administration: monitoring, players, moderation, announcement, release signing. Text only (textContent), no innerHTML. */
(function () {
  const root = document.getElementById("game");
  const $g = id => document.getElementById(id);
  const node = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
  const money = v => (v === null || v === undefined) ? "—" : new Intl.NumberFormat("ru-RU").format(v) + " ₽";
  const when = t => new Date(t * 1000).toLocaleString("ru-RU");
  const say = (id, text, bad) => { const n = $g(id); n.textContent = text; n.className = bad ? "bad" : ""; };
  const reason = e => ({ unauthorized: "нет доступа", rate_limited: "слишком много попыток, подождите", game_admin_not_configured: "не задан LUNEX_GAME_ADMIN_TOKEN в студии",
    game_server_unavailable: "игровой сервер недоступен", user_not_found: "игрок не найден", not_banned: "игрок не заблокирован", invalid_reason: "укажите причину (до 200 символов)",
    invalid_days: "срок: 0–3650 дней", invalid_text: "текст до 200 символов без < > и переводов строк", report_not_found: "жалоба не найдена", invalid_request: "некорректный запрос" }[e.message] || e.message);

  function card(title, value, bad) { const c = node("article", undefined, bad ? "card bad" : "card"); c.append(node("small", title), node("strong", value)); return c; }

  async function loadOverview() {
    const d = await api("/api/game/overview");
    const box = $g("gameoverview"); box.replaceChildren();
    const ledgerBad = d.ledger.unbalanced_transactions !== 0 || d.ledger.wallet_sum !== 0;
    box.append(
      card("Игровой месяц", d.month_index === null ? "—" : String(d.month_index)),
      card("Игроков (аккаунты)", String(d.accounts.accounts)), card("Активные сессии", String(d.accounts.active_sessions)), card("Блокировки", String(d.accounts.active_bans), d.accounts.active_bans > 0),
      card("Здания", String(d.world.buildings)), card("Компании", String(d.world.companies)),
      card("Население", d.city ? String(d.city.population) : "—"), card("Безработица: места/зарплата", d.city ? d.city.jobs + " / " + money(d.city.wage) : "—"),
      card("Журнал: несбалансир.", String(d.ledger.unbalanced_transactions), d.ledger.unbalanced_transactions !== 0), card("Сумма кошельков", money(d.ledger.wallet_sum), d.ledger.wallet_sum !== 0),
      card("Кредиты в обороте", money(d.finance.loans_outstanding)), card("Банкротств всего", String(d.finance.bankruptcies)),
      card("Бюджет города", money(d.system_accounts["player:city"])), card("Казна", money(d.system_accounts["system:treasury"])),
      card("Рынок (система)", money(d.system_accounts["system:market"])), card("Жалоб без ответа", String(d.moderation.open_reports), d.moderation.open_reports > 0));
    const prices = Object.entries(d.prices.products).map(([k, v]) => k + " " + money(v)).join(" · ");
    say("gameprices", prices ? "Цены месяца " + d.prices.month_index + ": " + prices : "Цен пока нет");
    say("gamewarnings", d.warnings.length ? "⚠ " + d.warnings.join("; ") : "Журнал в порядке: проводки сбалансированы, сумма кошельков 0.", d.warnings.length > 0 || ledgerBad);
  }

  async function loadPlayers() {
    const d = await api("/api/game/players?q=" + encodeURIComponent($g("playerq").value.trim()));
    const list = $g("playerlist"); list.replaceChildren();
    d.players.forEach(p => {
      const row = node("article");
      row.append(node("strong", p.username + (p.banned ? " · ЗАБЛОКИРОВАН" : "")), node("span", " · баланс " + money(p.balance) + " · зданий " + p.buildings + " · с " + when(p.created)));
      const open = node("button", "Карточка"); open.type = "button"; open.onclick = () => showPlayer(p.username);
      const ban = node("button", p.banned ? "Разблокировать" : "Заблокировать"); ban.type = "button";
      ban.onclick = async () => {
        try {
          if (p.banned) { await api("/api/game/unban", { method: "POST", body: JSON.stringify({ username: p.username }) }); say("gamemessage", "Разблокирован: " + p.username); }
          else { $g("banuser").value = p.username; $g("banreason").focus(); say("gamemessage", "Укажите причину в форме ниже и нажмите «Заблокировать»"); return; }
          await loadPlayers(); await loadOverview();
        } catch (e) { say("gamemessage", "Ошибка: " + reason(e), true); }
      };
      row.append(open, ban); list.append(row);
    });
    if (!d.players.length) list.append(node("p", "Игроков не найдено"));
  }

  async function showPlayer(name) {
    try {
      const d = await api("/api/game/player?name=" + encodeURIComponent(name));
      const lines = ["Игрок " + d.username, "Баланс: " + money(d.balance), "Кредит: " + money(d.loan),
        "Здания: " + (Object.entries(d.buildings).map(([k, v]) => k + "×" + v).join(", ") || "нет"),
        d.company ? "Долги: " + money(d.company.arrears) + " · пропущено месяцев: " + d.company.missed + " · банкротств: " + d.company.bankruptcies : "Компании нет",
        "Жалоб на игрока: " + d.reports_against, d.ban ? "БЛОКИРОВКА: " + d.ban.reason + (d.ban.until ? " до " + when(d.ban.until) : " (бессрочно)") : "Не заблокирован", "",
        "Последние операции:"].concat(d.recent_transactions.map(t => when(t.at) + " · " + money(t.amount) + " · " + t.memo));
      $g("playercard").textContent = lines.join("\n");
    } catch (e) { say("gamemessage", "Ошибка: " + reason(e), true); }
  }

  async function loadReports() {
    const d = await api("/api/game/reports");
    const list = $g("reportlist"); list.replaceChildren();
    d.reports.forEach(r => {
      const row = node("article");
      row.append(node("strong", r.reporter + " → " + r.target), node("p", r.reason + " · " + when(r.created)));
      const note = node("input"); note.placeholder = "Комментарий модератора"; note.maxLength = 300;
      const mk = (label, status) => { const b = node("button", label); b.type = "button"; b.onclick = async () => {
        try { await api("/api/game/report/resolve", { method: "POST", body: JSON.stringify({ id: r.id, status, note: note.value }) }); await loadReports(); await loadOverview(); }
        catch (e) { say("gamemessage", "Ошибка: " + reason(e), true); } }; return b; };
      row.append(note, mk("Отклонить", "dismissed"), mk("Приняты меры", "actioned")); list.append(row);
    });
    if (!d.reports.length) list.append(node("p", "Новых жалоб нет"));
  }

  async function loadAudit() {
    const d = await api("/api/game/audit");
    const list = $g("gameaudit"); list.replaceChildren();
    d.audit.forEach(a => list.append(node("article", when(a.at) + " · " + a.actor + " · " + a.action + " · " + a.target + " · " + a.detail + " · " + a.ip)));
  }

  async function loadCities() {
    const d = await api("/api/game/cities");
    const list = $g("citylist"); list.replaceChildren();
    d.cities.forEach(c => {
      const row = node("article");
      row.append(node("strong", c.name), node("span", " · домов " + c.houses + " из " + c.target + " · мест по плану " + c.plan_size + (c.seeded ? " · сгенерирован" : " · не генерировался")));
      const go = node("button", "Сгенерировать"); go.type = "button";
      go.onclick = () => seedOne(c.city_id, c.name);
      row.append(go); list.append(row);
    });
  }

  async function seedCities(which, label, dry) {
    try {
      const real = dry === false;
      if (real && !window.confirm("Создать дома в «" + label + "»? Это изменит игровой мир (деньги и экономика не затрагиваются).")) return;
      const r = await api("/api/game/cities/seed", { method: "POST", body: JSON.stringify({ city_id: which, dry_run: !real }) });
      const placed = r.cities.reduce((a, c) => a + c.placed, 0);
      say("citiesmessage", (real ? "Создано домов: " : "План (ничего не записано): будет создано домов: ") + placed + " в городах: " + r.cities.filter(c => c.placed > 0).length);
      if (real) { await loadCities(); await loadOverview(); await loadAudit(); }
    } catch (e) { say("citiesmessage", "Ошибка: " + reason(e), true); }
  }
  $g("citiesplan").onclick = () => seedCities("all", "все города", true);
  $g("citiesseed").onclick = () => seedCities("all", "все города", false);
  // single-city buttons always apply for real (after confirmation); the plan button above never writes
  async function seedOne(id, name) { await seedCities(id, name, false); }

  async function refreshGame() {
    try { await Promise.all([loadOverview(), loadPlayers(), loadReports(), loadAudit(), loadCities()]); say("gamemessage", "Обновлено " + new Date().toLocaleTimeString("ru-RU")); }
    catch (e) { say("gamemessage", "Игровой сервер: " + reason(e), true); }
  }

  $g("gamerefresh").onclick = refreshGame;
  $g("playersearch").onclick = () => loadPlayers().catch(e => say("gamemessage", "Ошибка: " + reason(e), true));
  $g("banform").onsubmit = async e => {
    e.preventDefault();
    try {
      const days = parseInt($g("bandays").value, 10) || 0;
      await api("/api/game/ban", { method: "POST", body: JSON.stringify({ username: $g("banuser").value.trim(), reason: $g("banreason").value.trim(), days }) });
      say("gamemessage", "Заблокирован: " + $g("banuser").value.trim()); $g("banreason").value = ""; await loadPlayers(); await loadOverview(); await loadAudit();
    } catch (err) { say("gamemessage", "Ошибка: " + reason(err), true); }
  };
  $g("announceform").onsubmit = async e => {
    e.preventDefault();
    try { await api("/api/game/announce", { method: "POST", body: JSON.stringify({ text: $g("announcetext").value.trim() }) }); say("gamemessage", $g("announcetext").value.trim() ? "Объявление опубликовано" : "Объявление снято"); await loadAudit(); }
    catch (err) { say("gamemessage", "Ошибка: " + reason(err), true); }
  };
  $g("announceclear").onclick = () => { $g("announcetext").value = ""; $g("announceform").requestSubmit(); };

  // Release signing helper: shows the digest of the exact manifest and the command to run on the administrator's own machine.
  $g("signinfo").onclick = async () => {
    const rev = parseInt($g("signrev").value, 10);
    if (!rev) { say("signresult", "Укажите номер ревизии", true); return; }
    try {
      const r = await fetch("/api/releases/" + rev + "/manifest", { headers: { Authorization: "Bearer " + token } });
      if (!r.ok) throw Error("revision_not_found");
      const bytes = new Uint8Array(await r.arrayBuffer());
      const digest = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))).map(b => b.toString(16).padStart(2, "0")).join("");
      say("signresult", "Манифест ревизии " + rev + ": " + bytes.length + " байт, SHA-256 " + digest + "\nПодпишите на своём компьютере (приватный ключ не покидает его):\n" +
        "LUNEX_ADMIN_TOKEN=… python3 sign_release.py --studio <адрес студии> --key private.pem --revision " + rev);
    } catch (e) { say("signresult", "Ошибка: " + reason(e), true); }
  };
  fetch("/health").then(r => r.json()).then(h => {
    say("signstate", h.signing ? "Подпись выпусков включена: клиентам отдаются только подписанные ревизии." : "⚠ Подпись выключена (не задан LUNEX_STUDIO_PUBLIC_KEY): выпуски отдаются без подписи, клиенты их не примут.", !h.signing);
    if (!h.game_admin) say("gamemessage", "Не задан LUNEX_GAME_ADMIN_TOKEN: раздел «Игра» работать не будет", true);
  }).catch(() => {});
  $g("connect").addEventListener("click", () => setTimeout(refreshGame, 700));
})();
