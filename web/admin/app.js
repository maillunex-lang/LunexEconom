/* Мобильная панель A1. Токен живёт только в sessionStorage текущей вкладки. */
(() => {
  const config = window.ADMIN_CONFIG || {};
  const apiBase = String(config.apiBase || '/lunexeconom/v2/admin-api/').replace(/\/$/, '');
  let token = sessionStorage.getItem('lunex_admin_token') || '';
  let currentRole = sessionStorage.getItem('lunex_admin_role') || '';
  let passwordChangeRequired = sessionStorage.getItem('lunex_admin_password_change_required') === 'true';

  const numberRu = (value) => Number(value || 0).toLocaleString('ru-RU');
  const dateRu = (value) => value ? new Date(value).toLocaleString('ru-RU') : '—';
  const $ = (selector) => document.querySelector(selector);
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[char]));

  async function api(path, options = {}) {
    const headers = { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) };
    const response = await fetch(`${apiBase}${path}`, { ...options, headers });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      if (data.error === 'password_change_required') {
        passwordChangeRequired = true;
        sessionStorage.setItem('lunex_admin_password_change_required', 'true');
        showPasswordChange();
      }
      throw new Error(data.message || data.error || 'Ошибка запроса');
    }
    return data;
  }

  function showLoggedIn() {
    $('#login').classList.add('hidden');
    $('#app').classList.remove('hidden');
    $('#logout').classList.remove('hidden');
    $('#open-password-change').classList.remove('hidden');
    if (passwordChangeRequired) showPasswordChange();
    else loadTab('overview');
  }

  function showPasswordChange() {
    $('#password-change').classList.remove('hidden');
    $('#content').classList.add('hidden');
    $('#admin-tabs').classList.toggle('hidden', passwordChangeRequired);
    $('#password-change-title').textContent = passwordChangeRequired ? 'Необходимо сменить пароль' : 'Сменить пароль';
    $('#password-change-hint').textContent = passwordChangeRequired
      ? 'Для доступа к панели установите пароль длиной не менее 14 символов. Он также станет паролем для игры.'
      : 'Новый пароль будет использоваться и для входа в игру.';
    $('#password-change-error').textContent = '';
    $('#password-change-cancel').classList.toggle('hidden', passwordChangeRequired);
  }

  function closePasswordChange() {
    $('#password-change').classList.add('hidden');
    $('#content').classList.remove('hidden');
    $('#admin-tabs').classList.remove('hidden');
    $('#password-change-form').reset();
  }

  $('#open-password-change').onclick = () => showPasswordChange();
  $('#password-change-cancel').onclick = () => { if (!passwordChangeRequired) closePasswordChange(); };
  $('#password-change-form').onsubmit = async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const password = form.elements.namedItem('password').value;
    const confirmation = form.elements.namedItem('confirmation').value;
    const message = $('#password-change-error');
    message.textContent = '';
    if (password.length < 14 || password.length > 256) { message.textContent = 'Пароль должен содержать от 14 до 256 символов.'; return; }
    if (password !== confirmation) { message.textContent = 'Пароли не совпадают.'; return; }
    const button = form.querySelector('[type=submit]');
    button.disabled = true;
    try {
      await api('/password', { method: 'POST', body: JSON.stringify({ password }) });
      passwordChangeRequired = false;
      sessionStorage.removeItem('lunex_admin_password_change_required');
      closePasswordChange();
      await loadTab('overview');
    } catch (error) { message.textContent = error.message; }
    finally { button.disabled = false; }
  };

  function metric(label, value) {
    return `<article class="metric"><span class="muted">${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></article>`;
  }

  function renderOverview(data) {
    const reconcileText = data.reconcile?.ok ? '0 расхождений' : 'Есть расхождения';
    $('#content').innerHTML = `<div class="grid">
      ${metric('Онлайн', data.online)}
      ${metric('Игроки', data.players)}
      ${metric('Регистрации за сутки', data.registrations_24h)}
      ${metric('Предприятия', data.enterprises)}
      ${metric('Участки игроков', data.owned_parcels)}
      ${metric('Системные счета', data.system_balance)}
      ${metric('Сверка журнала', reconcileText)}
      ${metric('Версия', data.version)}
    </div>`;
    refreshAlertsBadge();
  }

  function renderPlayers(data) {
    const items = data.items || [];
    $('#players-list').innerHTML = items.length ? items.map((player) => `
      <article class="row">
        <div class="row-main"><b>${escapeHtml(player.username)}</b>
          <div class="hint">Роль: ${escapeHtml(player.role)}</div>
        </div>
        <div class="actions">
          <span class="status ${player.blocked ? 'danger' : ''}">${player.blocked ? 'Заблокирован' : 'Активен'}</span>
          <button class="button ghost" data-player-id="${player.id}" type="button">Открыть</button>
        </div>
      </article>`).join('') : '<p class="muted">Игроки не найдены.</p>';
    document.querySelectorAll('[data-player-id]').forEach((button) => {
      button.addEventListener('click', () => loadPlayer(button.dataset.playerId));
    });
  }

  async function loadPlayers(query = '') {
    const data = await api(`/players?q=${encodeURIComponent(query)}`);
    renderPlayers(data);
  }

  async function loadPlayer(id) {
    const player = await api(`/players/${id}`);
    $('#content').innerHTML = `<div class="panel">
      <button id="back-players" class="button ghost" type="button">← К списку</button>
      <h2>${escapeHtml(player.username)}</h2>
      <p class="muted">Роль: ${escapeHtml(player.role)}</p>
      <div class="grid">
        ${metric('Кошелёк', player.wallet)}
        ${metric('Предприятия', (player.enterprises || []).length)}
        ${metric('Участки', (player.parcels || []).length)}
        ${metric('Состояние', player.blocked ? 'Заблокирован' : 'Активен')}
      </div>
      <div class="actions" style="margin-top:16px">
        <button id="toggle-block" class="button ${player.blocked ? 'secondary' : 'danger-button'}" type="button">${player.blocked ? 'Разблокировать' : 'Заблокировать'}</button>
        <button id="revoke-player" class="button ghost" type="button">Сбросить сессии</button>
      </div>
      <hr>
      <h3>Предприятия</h3>
      ${table(player.enterprises || [], ['name', 'city_id', 'stage', 'idle'])}
      <h3>Проводки кошелька</h3>
      ${table(player.wallet_entries || [], ['transfer_id', 'amount', 'at'])}
      <h3>Последние действия по игроку</h3>
      ${table(player.audit_actions || [], ['actor', 'action', 'at'])}
      <hr>
      <h3>Компенсация</h3>
      <form id="compensate-form" class="form">
        <label>Сумма (+ начисление, − возврат)<input name="amount" type="number" step="1" required></label>
        <label>Причина<textarea name="reason" required></textarea></label>
        <label>Ссылка на обращение<input name="ticket" required placeholder="SUP-123"></label>
        <label>Уникальный request_id<input name="request_id" required></label>
        <button class="button primary" type="submit">Показать последствия и применить</button>
        <p id="player-error" class="error"></p>
      </form>
    </div>`;
    $('#back-players').onclick = () => loadTab('players');
    $('#toggle-block').onclick = async () => {
      try {
        const reason = player.blocked ? '' : window.prompt('Причина блокировки:');
        if (!player.blocked && !reason) return;
        if (!window.confirm(player.blocked ? 'Разблокировать игрока?' : 'Заблокировать игрока и закрыть его сессии?')) return;
        await api(`/players/${id}/${player.blocked ? 'unblock' : 'block'}`, {
          method: 'POST', body: JSON.stringify(player.blocked ? {} : { reason }),
        });
        await loadPlayer(id);
      } catch (error) { $('#player-error').textContent = error.message; }
    };
    $('#revoke-player').onclick = async () => {
      if (!window.confirm('Сбросить все сессии игрока?')) return;
      try { await api('/sessions/revoke', { method: 'POST', body: JSON.stringify({ player_id: Number(id) }) }); await loadPlayer(id); }
      catch (error) { $('#player-error').textContent = error.message; }
    };
    $('#compensate-form').onsubmit = async (event) => {
      event.preventDefault();
      const form = new FormData(event.currentTarget);
      const payload = Object.fromEntries(form.entries());
      payload.amount = Number(payload.amount);
      if (!window.confirm(`Изменить баланс на ${payload.amount}? Проводка будет записана в аудит.`)) return;
      try { await api(`/players/${id}/compensate`, { method: 'POST', body: JSON.stringify(payload) }); await loadPlayer(id); }
      catch (error) { $('#player-error').textContent = error.message; }
    };
  }

  function renderSettings(data) {
    const entries = Object.entries(data.flags || {});
    $('#content').innerHTML = `<div class="panel"><p class="notice">Изменения применяются без перезапуска. Перед опасным изменением подтвердите последствия.</p>
      <div class="list">${entries.map(([key, value]) => {
        const bounds = data.metadata?.[key]?.bounds;
        return `<form class="row setting-form" data-setting="${escapeHtml(key)}">
          <div class="row-main"><b>${escapeHtml(key)}</b>${window.ADMIN_HELP?.setting(key,value,data.defaults?.[key],bounds) || ''}</div>
          <div class="actions"><input name="value" value="${escapeHtml(value)}" aria-label="Значение ${escapeHtml(key)}"><button class="button secondary" type="submit">Сохранить</button></div>
        </form>`;
      }).join('')}</div></div><div id="revisions" class="panel"><h3>Ревизии</h3><p class="muted">Загрузка…</p></div>`;
    document.querySelectorAll('.setting-form').forEach((form) => form.onsubmit = async (event) => {
      event.preventDefault();
      const valueText = new FormData(form).get('value');
      const value = valueText === 'true' ? true : valueText === 'false' ? false : Number.isNaN(Number(valueText)) ? valueText : Number(valueText);
      if (!window.confirm(`Применить значение ${valueText} для ${form.dataset.setting}?`)) return;
      try { await api('/settings', { method: 'POST', body: JSON.stringify({ key: form.dataset.setting, value, apply_at: 'now' }) }); await loadTab('settings'); }
      catch (error) { window.alert(error.message); }
    });
    api('/revisions').then((revisions) => {
      $('#revisions').innerHTML = `<h3>Ревизии</h3><div class="list">${(revisions.items || []).map((item) => `<div class="row"><div><b>#${item.revision} · ${escapeHtml(item.key)}</b><div class="hint">Новое значение: ${escapeHtml(item.value)} · ${escapeHtml(item.actor)}</div></div><button class="button ghost" data-rollback="${item.revision}" type="button">Откатить</button></div>`).join('')}</div>`;
      document.querySelectorAll('[data-rollback]').forEach((button) => button.onclick = async () => {
        if (!window.confirm(`Откатить ревизию #${button.dataset.rollback}?`)) return;
        await api('/revisions/rollback', { method: 'POST', body: JSON.stringify({ revision: Number(button.dataset.rollback) }) });
        await loadTab('settings');
      });
    });
  }

  function table(items, fields) {
    if (!items.length) return '<p class="muted">Данных пока нет.</p>';
    return `<div class="table-scroll"><table><thead><tr>${fields.map(k => `<th>${escapeHtml(k)}</th>`).join('')}</tr></thead><tbody>${items.map(item => `<tr>${fields.map(k => `<td>${escapeHtml(k === 'at' ? dateRu(item[k]) : item[k])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  }

  async function refreshAlertsBadge() {
    try { const data = await api('/alerts'); $('#alerts-count').textContent = data.count ? `(${numberRu(data.count)})` : ''; }
    catch { $('#alerts-count').textContent = ''; }
  }

  async function loadEconomy() {
    const data = await api('/economy');
    $('#content').innerHTML = `<div class="grid">
      ${metric('Деньги игроков', numberRu(data.player_money))}
      ${metric('Казна', numberRu(data.treasury))}
      ${metric('Итог ledger', numberRu(data.ledger_total))}
      ${metric('Сверка', data.reconcile.ok ? 'Сходится' : 'Расхождение')}
      ${metric('Игроки', numberRu(data.players))}
      ${metric('Активных 24 ч', numberRu(data.active_24h))}
      ${metric('Активных 7 дней', numberRu(data.active_7d))}
      ${metric('Розница за 7 игровых дней', numberRu(data.revenue_7d))}
      ${metric('НДС за 7 игровых дней', numberRu(data.tax_7d))}
    </div><section class="panel"><h2>Динамика экономики</h2><div id="economy-chart"></div></section>
    <section class="panel"><h2>Системные счета</h2>${table(data.system_accounts,['account','balance'])}</section>
    <section class="panel"><h2>Предприятия по типам</h2>${table(data.enterprises_by_building,['building','count'])}</section>
    <section class="panel"><h2>Предприятия по стадии</h2>${table(data.enterprises_by_stage,['stage','count'])}</section>
    <section class="panel"><h2>Продажи по товарам</h2>${table(data.sales_7d,['product','quantity','revenue'])}</section>
    <section class="panel"><h2>Выпуск продукции</h2><p class="hint">Фактический выпуск по игровым дням после подключения A2.</p>${table(data.production_7d,['product','quantity'])}</section>
    <section class="panel"><h2>Лидеры по деньгам</h2>${table(data.top_money,['name','money'])}</section>
    <section class="panel"><h2>Лидеры по предприятиям</h2>${table(data.top_enterprises,['name','count'])}</section>`;
    const history = await api('/economy/history?days=30');
    const rows = history.items || [];
    if (!rows.length) { $('#economy-chart').textContent='Снимков пока нет.'; return; }
    const max = Math.max(1,...rows.map(row => Number(row.player_money)));
    const points = rows.map((row,i) => `${20 + i*660/Math.max(1, rows.length-1)},${178 - 155*Number(row.player_money)/max}`).join(' ');
    $('#economy-chart').innerHTML = `<svg viewBox="0 0 700 200" role="img" aria-label="Деньги игроков по игровым дням" preserveAspectRatio="xMidYMid meet"><title>Динамика денег игроков</title><path d="M20 178 H680" stroke="currentColor" opacity=".4" fill="none"/><polyline points="${points}" fill="none" stroke="var(--mint)" stroke-width="3" stroke-linejoin="round"/></svg>`;
  }

  async function loadCities(query = '') {
    const data=await api('/cities?limit=100');
    const cities=(data.items || []).filter(c=>`${c.name} ${c.id}`.toLocaleLowerCase('ru').includes(query.toLocaleLowerCase('ru')));
    $('#content').innerHTML = `<div class="toolbar"><input id="city-filter" aria-label="Фильтр города" placeholder="Поиск города" value="${escapeHtml(query)}" /></div><div class="list">${cities.map(c=>`<article class="row"><div class="row-main"><b>${escapeHtml(c.name)}</b><p class="hint">Уровень ${c.level} · радиус ${numberRu(c.radius)} · застройка ${numberRu(c.occupancy_percent)}% · население ${numberRu(c.population)} · зданий ${numberRu(c.buildings)}</p></div><div class="actions"><span class="status ${c.growth_enabled ? '' : 'danger'}">Рост ${c.growth_enabled ? 'включён' : 'выключен'}</span>${['owner','admin'].includes(currentRole) ? `<button class="button secondary" data-city="${escapeHtml(c.id)}" data-enabled="${c.growth_enabled}" type="button">Переключить</button>` : ''}</div></article>`).join('') || '<p>Городов нет.</p>'}</div>`;
    $('#city-filter').oninput=(event)=>loadCities(event.target.value);
    document.querySelectorAll('[data-city]').forEach(button=>button.onclick=async()=>{
      const reason=window.prompt('Укажите причину изменения роста города:');
      if (!reason?.trim()) return;
      if (!window.confirm('Подтвердить изменение статуса роста?'))return;
      const id=button.dataset.city;
      const requestId = `growth-${Date.now()}-${Math.random().toString(36).slice(2)}`;
      try { await api(`/cities/${encodeURIComponent(id)}/growth`,{method:'POST',body:JSON.stringify({enabled:button.dataset.enabled !== 'true',reason,request_id:requestId})}); await loadCities(query); }
      catch(error){window.alert(error.message);}
    });
  }

  async function loadEvents(after=0) {
    const data=await api(`/world/events?limit=50&after=${after}`);
    $('#content').innerHTML=`<section class="panel"><h2>События мира</h2>${table(data.items,['id','kind','city_id','at'])}<button class="button ghost" id="events-next" type="button" ${data.next_after===null ? 'disabled' : ''}>Следующие события</button></section>`;
    $('#events-next').onclick=()=>loadEvents(data.next_after);
  }

  async function loadServer() {
    const [state,errors]=await Promise.all([api('/server'),api('/errors?limit=50')]);
    $('#content').innerHTML=`<div class="grid">${metric('Версия',state.version)}${metric('SHA',state.sha)}${metric('Время работы, с',numberRu(state.uptime_seconds))}${metric('Размер БД, байт',numberRu(state.database_size_bytes))}${metric('Активные админ-сессии',numberRu(state.admin_sessions_active))}${metric('Миграции',numberRu(state.migrations.count))}${metric('SHA-256 миграций',state.migrations.sha256_ok?'Совпадает':'Расхождение')}</div><section class="panel"><h2>Последние 50 тиков</h2>${table(state.ticks,['day','duration_ms','completed','error'])}</section><section class="panel"><h2>Ошибки</h2>${table(errors.items,['id','origin','day_index','error_code','at'])}</section>`;
  }

  async function loadAlerts() {
    const data=await api('/alerts');
    $('#content').innerHTML=`<section class="panel"><h2>Алерты (${numberRu(data.count)})</h2><div class="list">${(data.items||[]).map(a=>`<article class="row"><span class="status ${a.level==='crit'?'danger':''}">${escapeHtml(a.level)}</span><div class="row-main"><b>${escapeHtml(a.text)}</b><p class="hint">${escapeHtml(a.code)}</p></div><button class="button ghost" data-open-alert="${escapeHtml(a.link.slice(1))}" type="button">Открыть</button></article>`).join('') || '<p class="muted">Активных предупреждений нет.</p>'}</div></section>`;
    document.querySelectorAll('[data-open-alert]').forEach(b=>b.onclick=()=>loadTab(b.dataset.openAlert==='ticks'?'server':b.dataset.openAlert));
    await refreshAlertsBadge();
  }

  const a3Options = () => ({ api, role: currentRole });
  async function loadA3(name) {
    if (!window.ADMIN_A3) throw new Error('Модуль A3 не загружен');
    if (name === 'catalog') await window.ADMIN_A3.catalog(a3Options());
    if (name === 'announcements') await window.ADMIN_A3.announcements(a3Options());
    if (name === 'releases') await window.ADMIN_A3.releases(a3Options());
  }

  async function loadTab(name) {
    if (passwordChangeRequired) { showPasswordChange(); return; }
    document.querySelectorAll('.tab').forEach((tab) => tab.classList.toggle('active', tab.dataset.tab === name));
    try {
      if (['catalog','announcements','releases'].includes(name)) await loadA3(name);
      if (name === 'economy') await loadEconomy();
      if (name === 'cities') await loadCities();
      if (name === 'events') await loadEvents();
      if (name === 'server') await loadServer();
      if (name === 'alerts') await loadAlerts();
      if (name === 'overview') renderOverview(await api('/overview'));
      if (name === 'players') {
        $('#content').innerHTML = '<div class="toolbar"><input id="player-query" placeholder="Логин или почта"><button id="player-search" class="button primary" type="button">Найти</button></div><div id="players-list" class="list"></div>';
        $('#player-search').onclick = () => loadPlayers($('#player-query').value);
        await loadPlayers();
      }
      if (name === 'settings') renderSettings(await api('/settings'));
      if (name === 'audit') {
        const data = await api('/audit');
        $('#content').innerHTML = `<div class="toolbar"><input id="audit-action" placeholder="Фильтр по действию"><button id="audit-search" class="button primary" type="button">Применить</button></div><div id="audit-list" class="list"></div>`;
        const renderAudit = (items) => { $('#audit-list').innerHTML = (items || []).map((item) => `<div class="row"><div><b>${escapeHtml(item.action)}</b><div class="hint">${escapeHtml(item.actor)} · роль ${escapeHtml(item.role || '')} · ${escapeHtml(item.at)}</div></div><span class="hint">игрок: ${escapeHtml(item.player_id || '—')}</span></div>`).join('') || '<p class="muted">Записей нет.</p>'; };
        renderAudit(data.items);
        $('#audit-search').onclick = async () => renderAudit((await api(`/audit?action=${encodeURIComponent($('#audit-action').value)}`)).items);
        if (['owner','admin'].includes(currentRole)) {
          const download = document.createElement('button');
          download.id='audit-export';
          download.className='button secondary';
          download.textContent='Экспорт аудита (CSV/JSON)';
          $('#audit-search').parentElement.appendChild(download);
          download.onclick=async()=>{
            try { await window.ADMIN_A3.exportAudit(a3Options()); }
            catch(error) { window.alert('Ошибка экспорта: '+error.message); }
          };
        }
      }
    } catch (error) { $('#content').innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`; }
    const guide = window.ADMIN_HELP?.section(name);
    if (guide) $('#content').insertAdjacentHTML('afterbegin', guide);
  }

  $('#login-form').onsubmit = async (event) => {
    event.preventDefault();
    $('#login-error').textContent = '';
    const form = new FormData(event.currentTarget);
    try {
      const data = await api('/login', { method: 'POST', body: JSON.stringify({ username: form.get('username'), password: form.get('password') }) });
      token = data.token;
      currentRole = data.role;
      passwordChangeRequired = data.password_change_required === true;
      if (passwordChangeRequired) sessionStorage.setItem('lunex_admin_password_change_required', 'true');
      else sessionStorage.removeItem('lunex_admin_password_change_required');
      sessionStorage.setItem('lunex_admin_token', token);
      sessionStorage.setItem('lunex_admin_role', currentRole);
      showLoggedIn();
    } catch (error) { $('#login-error').textContent = error.message; }
  };
  document.querySelectorAll('.tab').forEach((tab) => tab.onclick = () => loadTab(tab.dataset.tab));
  $('#logout').onclick = async () => { try { await api('/logout', { method: 'POST' }); } finally { sessionStorage.removeItem('lunex_admin_token'); sessionStorage.removeItem('lunex_admin_role'); sessionStorage.removeItem('lunex_admin_password_change_required'); location.reload(); } };
  if (token) showLoggedIn();
})();
