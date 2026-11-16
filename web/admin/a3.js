/* A3 sections: catalog drafts, announcements, versions and audit downloads.
   No external libraries; admin authentication stays in the existing app.js. */
(() => {
  'use strict';
  const byId = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
  const requestId = () => 'a3-' + (crypto.randomUUID ? crypto.randomUUID() :
      String(Date.now()) + Math.random().toString(36).slice(2));
  const canEdit = role => role === 'owner' || role === 'admin';
  const post = (api, path, payload) => api(path, {
    method: 'POST', body: JSON.stringify(payload)
  });
  const dateRu = iso => iso ? new Date(iso).toLocaleString('ru-RU') : '—';
  const table = (rows, keys) => '<div class="table-scroll"><table><thead><tr>' +
      keys.map(k => '<th>' + esc(k) + '</th>').join('') + '</tr></thead><tbody>' +
      rows.map(row => '<tr>' + keys.map(k => '<td>' + esc(row[k]) + '</td>').join('') + '</tr>').join('') +
      '</tbody></table></div>';
  const message = (id, text, error=false) => {
    const node=byId(id);
    if (node) { node.textContent=text; node.className=error ? 'error' : 'hint'; }
  };
  const errorText = error => error.message || 'Не удалось выполнить запрос.';

  async function catalog({ api, role }) {
    const data = await api('/catalog');
    const history = await api('/catalog/revisions');
    const editable=canEdit(role);
    let pending=[];
    let previewed=null;
    const names={products:'Товары',buildings:'Здания',recipes:'Рецепты'};
    const collections={products:data.items.products,buildings:data.items.buildings,recipes:data.items.recipes};
    const summary=kind => collections[kind].map(x => ({
      id:x.id,
      name:x.effective.name,
      draft:x.balance,
      status:x.overridden ? 'Переопределено' : 'Базовое',
      value:kind==='products' ? String(x.effective.reference_price) :
          kind==='buildings' ? String(x.effective.build_cost) :
          Object.entries(x.effective.outputs).map(([k,v])=>k+': '+v).join(', ')
    }));
    byId('content').innerHTML = '<section class="panel"><h2>Каталог и баланс · ревизия ' +
      esc(data.revision) + '</h2><p class="hint">SHA-256: <code>' + esc(data.sha) +
      '</code>. Базовый JSON остаётся неизменным. Все значения пока draft.</p>' +
      Object.keys(names).map(kind => '<details class="a3-details"' + (kind==='buildings'?' open':'') +
          '><summary>' + names[kind] + ' (' + collections[kind].length + ')</summary>' +
          table(summary(kind),['id','name','draft','status','value']) + '</details>').join('') +
      '</section>' +
      (editable ? '<section class="panel"><h2>Редактор безопасных полей</h2>' +
       '<p class="hint">Структура рецептов, ID, названия и размеры заблокированы. Сначала предпросмотр.</p>' +
       '<div class="a3-form-grid"><label>Категория<select id="a3-entity"><option value="buildings">Здание</option>' +
       '<option value="products">Товар</option><option value="recipes">Рецепт</option></select></label>' +
       '<label>Объект<select id="a3-identifier"></select></label><label>Поле<select id="a3-field"></select></label>' +
       '<label>Целое значение<input id="a3-number" type="number" min="0" step="1" inputmode="numeric"></label></div>' +
       '<p id="a3-existing" class="hint"></p><div class="toolbar"><button id="a3-stage" class="button secondary">' +
       'Добавить изменение</button><button id="a3-preview" class="button primary">Предпросмотр</button></div>' +
       '<div id="a3-staged" class="a3-wrap"></div><div id="a3-impact" class="a3-wrap"></div>' +
       '<label>Причина изменения<input id="a3-reason" maxlength="500" placeholder="Зачем корректируем баланс"></label>' +
       '<button id="a3-apply" class="button primary" disabled>Применить ревизию</button>' +
       '<p id="a3-catalog-message" role="status" class="hint"></p></section>' : '') +
      '<section class="panel"><h2>История ревизий</h2>' +
      table(history.items.map(r=>({revision:r.revision,actor:r.actor,
         reason:r.reason,overrides:r.overrides_count,at:dateRu(r.at)})),
         ['revision','actor','reason','overrides','at']) +
      (editable ? '<label>Ревизия для отката<select id="a3-rollback-target"><option value="0">0 · Базовый JSON</option>' +
        history.items.map(r=>'<option value="'+r.revision+'">'+r.revision+' · '+esc(r.reason)+'</option>').join('') +
        '</select></label><button id="a3-rollback" class="button secondary">Откатить выбранную ревизию</button>' : '') +
      '</section>';

    if (!editable) return;
    const entity=byId('a3-entity'), ident=byId('a3-identifier'), field=byId('a3-field');
    const number=byId('a3-number');
    const currentValue=(obj,path) => path.split('.').reduce((value,key)=>value[key],obj);
    const options=()=> {
      const item=collections[entity.value].find(x=>x.id===ident.value);
      if (!item)return;
      const fields = entity.value==='recipes' ?
        ['inputs','outputs'].flatMap(direction =>
           Object.keys(item.effective[direction]).map(product => direction+'.'+product)) :
        (data.editable[entity.value] || []).filter(key => key in item.effective);
      field.innerHTML=fields.map(name=>'<option value="'+esc(name)+'">'+esc(name)+'</option>').join('');
      showValue();
    };
    const showValue=()=>{
      const item=collections[entity.value].find(x=>x.id===ident.value);
      if (!item || !field.value)return;
      number.value=currentValue(item.effective,field.value);
      const base=currentValue(item.base,field.value);
      byId('a3-existing').textContent='Базовое: '+base+' · текущее: '+number.value;
    };
    const selectEntity=()=>{
      ident.innerHTML=collections[entity.value].map(x=>'<option value="'+esc(x.id)+'">'+
         esc(x.effective.name)+' · '+esc(x.id)+'</option>').join('');
      options();
    };
    entity.onchange=selectEntity; ident.onchange=options; field.onchange=showValue;
    selectEntity();

    const renderPending=()=>{
      byId('a3-staged').innerHTML=pending.length ?
        '<p>Запланировано изменений: '+pending.length+'</p>' +
        table(pending.map(x=>({entity:x.entity,id:x.id,field:x.field,value:x.value})),
          ['entity','id','field','value']) : '<p class="hint">Изменений пока нет.</p>';
      byId('a3-apply').disabled=true;
      previewed=null;
      byId('a3-impact').textContent='';
    };
    byId('a3-stage').onclick=()=>{
      const value=Number(number.value);
      if (number.value.trim()==='' || !Number.isSafeInteger(value) || value<0){
        message('a3-catalog-message','Введите неотрицательное целое число.',true);return;
      }
      const change={entity:entity.value,id:ident.value,field:field.value,value};
      pending=pending.filter(x=>!(x.entity===change.entity && x.id===change.id && x.field===change.field));
      pending.push(change);
      renderPending();
      message('a3-catalog-message','Изменение добавлено в предпросмотр.');
    };
    byId('a3-preview').onclick=async()=>{
      if (!pending.length){message('a3-catalog-message','Сначала добавьте изменение.',true);return;}
      try {
        const result=await post(api,'/catalog/preview',{changes:pending});
        previewed=JSON.stringify(pending);
        const impacts=result.impacts.map(x=>({
          building:x.building, 'стоимость до':x.before.build_cost, 'стоимость после':x.after.build_cost,
          'выручка до':x.before.daily_revenue,'выручка после':x.after.daily_revenue,
          'прибыль до':x.before.daily_profit,'прибыль после':x.after.daily_profit,
          'окупаемость до':x.before.payback_days ?? '∞',
          'окупаемость после':x.after.payback_days ?? '∞'
        }));
        byId('a3-impact').innerHTML='<h3>Предпросмотр до и после</h3>'+
          '<p class="hint">Хлебный сценарий M1: пройден. Зарплата и содержание оценочные, без округления денег.</p>'+
          table(impacts,['building','стоимость до','стоимость после','выручка до','выручка после',
              'прибыль до','прибыль после','окупаемость до','окупаемость после']);
        byId('a3-apply').disabled=false;
        message('a3-catalog-message','Предпросмотр прошёл. Можно применить с причиной.');
      } catch(error){previewed=null;byId('a3-apply').disabled=true;
          message('a3-catalog-message','Предпросмотр отклонён: '+errorText(error),true);}
    };
    byId('a3-apply').onclick=async()=>{
      const reason=byId('a3-reason').value.trim();
      if (reason.length<3 || previewed!==JSON.stringify(pending)){
        message('a3-catalog-message','Введите причину и повторите предпросмотр.',true);return;
      }
      if (!window.confirm('Применить '+pending.length+' изменений каталога?'))return;
      const button=byId('a3-apply');button.disabled=true;
      try { await post(api,'/catalog/apply',{changes:pending,reason,request_id:requestId()});
        await catalog({api,role});
      } catch(error){button.disabled=false;message('a3-catalog-message',errorText(error),true);}
    };
    byId('a3-rollback').onclick=async()=>{
      const revision=Number(byId('a3-rollback-target').value);
      const reason=window.prompt('Причина отката ревизии '+revision+':','Откат каталога');
      if (!reason || reason.trim().length<3 || !window.confirm('Вернуть каталог к ревизии '+revision+'?'))return;
      try {await post(api,'/catalog/rollback',{revision,reason:reason.trim(),request_id:requestId()});
        await catalog({api,role});
      } catch(error){message('a3-catalog-message',errorText(error),true);}
    };
    renderPending();
  }

  async function announcements({api,role}){
    const canWrite=canEdit(role);
    const [data,cities]=await Promise.all([api('/announcements'),api('/cities?limit=100')]);
    byId('content').innerHTML='<section class="panel"><h2>Объявления игрокам</h2>' +
      (canWrite ? '<form id="a3-ann-form" class="form"><label>Заголовок (до 80 знаков)' +
       '<input name="title" maxlength="80" required></label><label>Текст (до 500 знаков, без HTML)' +
       '<textarea name="body" maxlength="500" required></textarea></label>' +
       '<div class="a3-form-grid"><label>Тип<select name="level"><option value="info">Информация</option>' +
       '<option value="warn">Предупреждение</option></select></label><label>Город' +
       '<select name="city_id"><option value="">Все города</option>' +
       (cities.items||[]).map(c=>'<option value="'+esc(c.id)+'">'+esc(c.name)+'</option>').join('') +
       '</select></label><label>Начало<input name="starts_at" type="datetime-local" required></label>' +
       '<label>Конец<input name="ends_at" type="datetime-local" required></label></div>' +
       '<button class="button primary" type="submit">Опубликовать объявление</button></form>' : '') +
       '<p id="a3-ann-message" role="status" class="hint"></p></section>' +
       '<section class="panel"><h2>История объявлений</h2><div class="a3-items">' +
       (data.items||[]).map(x=>'<article class="row"><div class="row-main"><b>'+esc(x.title)+
         '</b><p>'+esc(x.body)+'</p><p class="hint">'+esc(x.level)+' · '+esc(x.city_id||'Все города')+
         ' · '+esc(dateRu(x.starts_at))+' → '+esc(dateRu(x.ends_at))+
         ' · '+(x.active?'Активно':'Выключено')+'</p></div>'+
         (canWrite && x.active?'<button class="button secondary" data-ann-id="'+x.id+'">Деактивировать</button>':'')+
         '</article>').join('') + '</div></section>';
    if (!canWrite)return;
    const form=byId('a3-ann-form'),start=form.elements.starts_at,end=form.elements.ends_at;
    const localValue=date=>{
      const shifted=new Date(date.getTime()-date.getTimezoneOffset()*60000);
      return shifted.toISOString().slice(0,16);
    };
    start.value=localValue(new Date());
    end.value=localValue(new Date(Date.now()+24*3600*1000));
    form.onsubmit=async event=>{
      event.preventDefault();
      const record=new FormData(form);
      const payload={title:record.get('title'),body:record.get('body'),level:record.get('level'),
          city_id:record.get('city_id')||null,starts_at:new Date(record.get('starts_at')).toISOString(),
          ends_at:new Date(record.get('ends_at')).toISOString(),request_id:requestId()};
      try {await post(api,'/announcements',payload);await announcements({api,role});}
      catch(error){message('a3-ann-message',errorText(error),true);}
    };
    document.querySelectorAll('[data-ann-id]').forEach(button=>{
      button.onclick=async()=>{
        if (!window.confirm('Деактивировать объявление?'))return;
        try {await post(api,'/announcements/'+button.dataset.annId+'/deactivate',
          {request_id:requestId()});await announcements({api,role});}
        catch(error){message('a3-ann-message',errorText(error),true);}
      };
    });
  }

  async function releases({api}){
    const data=await api('/releases');
    const current=Object.entries(data.flags||{}).filter(([_,flag])=>flag.overridden).map(([key,flag])=>
      ({flag:key,default:JSON.stringify(flag.default),current:JSON.stringify(flag.current)}));
    byId('content').innerHTML='<div class="grid">'+
      [['Сервер',data.version],['SHA',data.sha],['Миграции',data.migrations.count],
        ['SHA каталога',data.catalog.sha],['Ревизия баланса',data.catalog.revision],
        ['Миграции целы',data.migrations.sha256_ok?'Да':'Нет']].map(([key,value])=>
          '<article class="metric"><span class="muted">'+esc(key)+'</span><strong>'+esc(value)+'</strong></article>').join('')+
      '</div><section class="panel"><h2>Флаги, отличающиеся от заводских</h2>'+
      (current.length?table(current,['flag','default','current']):'<p class="hint">Все флаги имеют значения по умолчанию.</p>')+
      '</section><section class="panel"><h2>Текущий APK / релиз</h2>'+
      (data.release ? table(Object.entries(data.release).map(([key,value])=>({field:key,value})),
        ['field','value']) : '<p class="hint">'+esc(data.release_note||'Метаданные не доступны.')+'</p>')+
      '</section>';
  }

  async function exportAudit({role}){
    if (!canEdit(role))return;
    const config=window.ADMIN_CONFIG||{};
    const apiBase=String(config.apiBase||'/lunexeconom/v2/admin-api/').replace(/\/$/,'');
    const token=sessionStorage.getItem('lunex_admin_token');
    if (!token)throw new Error('Административная сессия не найдена.');
    const fmt=window.prompt('Формат экспорта: csv или json','csv');
    if (!fmt || !['csv','json'].includes(fmt))return;
    const action=byId('audit-action')?.value.trim()||'';
    const query=new URLSearchParams({format:fmt});
    if (action)query.set('action',action);
    const response=await fetch(apiBase+'/audit/export?'+query.toString(),{
      method:'GET',headers:{Authorization:'Bearer '+token}
    });
    if (!response.ok){
      const error=await response.json().catch(()=>({}));
      throw new Error(error.message||error.error||'Ошибка экспорта аудита');
    }
    const blob=await response.blob();
    const url=URL.createObjectURL(blob);
    const link=document.createElement('a');
    link.href=url;link.download='lunex-audit.'+fmt;
    document.body.appendChild(link);link.click();link.remove();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  }

  window.ADMIN_A3={catalog,announcements,releases,exportAudit};
})();
