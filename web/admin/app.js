/* Мобильная панель A1. Токен живёт только в sessionStorage текущей вкладки. */
(() => {
  const config = window.ADMIN_CONFIG || {};
  const apiBase = String(config.apiBase || '/lunexeconom/v2/admin-api/').replace(/\/$/, '');
  let token = sessionStorage.getItem('lunex_admin_token') || '';
  let currentRole = '';

  const $ = (selector) => document.querySelector(selector);
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[char]));

  async function api(path, options = {}) {
    const headers = { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) };
    const response = await fetch(`${apiBase}${path}`, { ...options, headers });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.message || data.error || 'Ошибка запроса');
    return data;
  }

  function showLoggedIn() {
    $('#login').classList.add('hidden');
    $('#app').classList.remove('hidden');
    $('#logout').classList.remove('hidden');
    loadTab('overview');
  }

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
  }

  function renderPlayers(data) {
    const items = data.items || [];
    $('#players-list').innerHTML = items.length ? items.map((player) => `
      <article class="row">
        <div class="row-main"><b>${escapeHtml(player.username)}</b>
          <div class="hint">${escapeHtml(player.email || 'почта не указана')} · роль ${escapeHtml(player.role)}</div>
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
      <p class="muted">${escapeHtml(player.email || 'почта не указана')} · ${escapeHtml(player.role)}</p>
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
          <div class="row-main"><b>${escapeHtml(key)}</b><div class="hint">${escapeHtml(data.metadata?.[key]?.description || '')} ${bounds ? `Границы: ${escapeHtml(bounds.join('…'))}` : ''}</div></div>
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

  async function loadTab(name) {
    document.querySelectorAll('.tab').forEach((tab) => tab.classList.toggle('active', tab.dataset.tab === name));
    try {
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
      }
    } catch (error) { $('#content').innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`; }
  }

  $('#login-form').onsubmit = async (event) => {
    event.preventDefault();
    $('#login-error').textContent = '';
    const form = new FormData(event.currentTarget);
    try {
      const data = await api('/login', { method: 'POST', body: JSON.stringify({ username: form.get('username'), password: form.get('password') }) });
      token = data.token;
      currentRole = data.role;
      sessionStorage.setItem('lunex_admin_token', token);
      showLoggedIn();
    } catch (error) { $('#login-error').textContent = error.message; }
  };
  document.querySelectorAll('.tab').forEach((tab) => tab.onclick = () => loadTab(tab.dataset.tab));
  $('#logout').onclick = async () => { try { await api('/logout', { method: 'POST' }); } finally { sessionStorage.removeItem('lunex_admin_token'); location.reload(); } };
  if (token) showLoggedIn();
})();
