"use strict";
/* Russian-only, token-gated World Studio runtime panels. No HTML injection. */
(() => {
  const byId = id => document.getElementById(id);
  const el = (tag, value, css) => {
    const node = document.createElement(tag);
    if (value !== undefined) node.textContent = String(value);
    if (css) node.className = css;
    return node;
  };
  const time = seconds => new Date(seconds * 1000).toLocaleString("ru-RU");
  const show = (id, msg, bad=false) => {
    const node = byId(id);
    node.textContent = msg;
    node.classList.toggle("bad", bad);
  };
  const read = path => api("/api/game/" + path);
  const write = (path, payload) => api("/api/game/" + path,
    {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload)});
  const errors = {
    unknown_parameter:"Параметр не входит в разрешённый реестр",
    invalid_type:"Неверный тип значения", out_of_range:"Значение за пределами диапазона",
    confirmation_required:"Требуется подтверждение опасного изменения",
    revision_conflict:"Настройки изменены другим администратором. Обновите страницу",
    game_server_unavailable:"Игровой сервер не отвечает", unauthorized:"Недействительный токен",
    revision_not_found:"Ревизия не найдена", invalid_request:"Некорректный запрос"
  };
  const describeError = e => errors[e.message] || String(e.message);
  let config = null;
  async function refreshConfig() {
    config = await read("config");
    renderSettings();
    const client=config.client||{};
    byId("client-minversion").value=String(client.min_version??0);
    byId("client-recversion").value=String(client.recommended_version??0);
    byId("client-hqtitle").value=String(client.texts?.hq_title??"");
    show("client-patchurl","Манифест: "+String(client.patch_url||"не настроен"));
    const current = config.parameters.find(p => p.key === "MAINTENANCE_MODE");
    show("maintenancestatus", current && current.value ? "Обслуживание включено" : "Игра работает");
  }
  function sendChange(name, value, label) {
    (async () => {
      const item = config.parameters.find(p=>p.key===name);
      if (!item) throw Error("unknown_parameter");
      const dangerous = item.danger === "high";
      if (dangerous && !confirm("Изменить «" + label + "» на «" + String(value) + "»? Изменение будет записано в журнал. " +
          (item.apply_at === "next_month" ? "Вступит в силу со следующего игрового месяца." : "Применится сразу."))) return;
      const result = await write("config/set", {
        changes:{[name]:value}, comment:"World Studio: " + label,
        confirm:dangerous, expected_revision:config.revision
      });
      const nextMonth = item.apply_at === "next_month" ? " · с начала следующего игрового месяца" : "";
      show(item.type==="bool" ? "flagsmessage" : "paramsmessage",
        "Ревизия " + result.revision + nextMonth);
      await refreshConfig();
    })().catch(e => show(config?.parameters?.find(p=>p.key===name)?.type==="bool" ? "flagsmessage" : "paramsmessage", "Ошибка: "+describeError(e), true));
  }
  function settingRow(item) {
    const row = el("article", undefined, "runtime-row");
    const title = el("strong",item.key);
    const desc = el("p", item.description + " · по умолчанию: " + item.default +
      (item.minimum != null ? " · диапазон: " + item.minimum + "…"+item.maximum : "") +
      (item.apply_at==="next_month" ? " · со следующего месяца" : "") +
      (!item.effective ? " · ожидает применения" : ""));
    const input = document.createElement("input");
    input.setAttribute("aria-label", item.key);
    if (item.type === "bool") {
      input.type = "checkbox";
      input.checked = !!item.value;
      input.onchange=()=>sendChange(item.key,input.checked,item.key);
    } else {
      input.type="number";
      input.step=item.type==="int" ? "1":"any";
      input.min=String(item.minimum);
      input.max=String(item.maximum);
      input.value=String(item.value);
      const save=el("button","Сохранить");
      save.type="button";
      save.onclick=()=>{
        const value=Number(input.value);
        if (!Number.isFinite(value) || (item.type==="int" && !Number.isInteger(value)) ||
            value<item.minimum || value>item.maximum) {
          show("paramsmessage","Укажите число в разрешённом диапазоне",true);return;
        }
        sendChange(item.key,value,item.key);
      };
      row.append(title,desc,input,save);
    }
    if (item.type==="bool") row.append(title,desc,input);
    if (item.value !== item.default) {
      const reset=el("button","Сбросить");
      reset.type="button";
      reset.onclick=()=>sendChange(item.key,item.default,item.key+" (сброс)");
      row.append(reset);
    }
    return row;
  }
  function renderSettings() {
    if (!config) return;
    const flags=byId("flagslist"), parameters=byId("paramslist");
    flags.replaceChildren();
    parameters.replaceChildren();
    config.parameters.forEach(p => (p.type === "bool" ? flags : parameters).append(settingRow(p)));
  }
  function canvasChart(rows) {
    const canvas=byId("onlinechart"), ctx=canvas.getContext("2d");
    const width=canvas.width,height=canvas.height;
    ctx.clearRect(0,0,width,height);
    ctx.strokeStyle="#668876";
    ctx.beginPath();ctx.moveTo(0,height-22);ctx.lineTo(width,height-22);ctx.stroke();
    if (!rows.length) {
      ctx.font="18px sans-serif";ctx.fillStyle="#bed6c5";
      ctx.fillText("История появится после первых подключений",16,40);return;
    }
    const min=rows[0].at,max=rows[rows.length-1].at,peak=Math.max(1,...rows.map(x=>x.online));
    ctx.strokeStyle="#79c99a";ctx.lineWidth=3;ctx.beginPath();
    rows.forEach((r,i)=>{
      const x=(r.at-min)/Math.max(1,max-min)*(width-20)+10;
      const y=(height-36)-(r.online/peak)*(height-54);
      if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);
    });
    ctx.stroke();ctx.fillStyle="#e4f3e9";ctx.font="14px sans-serif";
    ctx.fillText("Пик: "+peak,12,17);
  }
  async function refreshDashboard() {
    try {
      const [status,online]=await Promise.all([read("status"),read("online")]);
      const cards=byId("dashboardcards");
      cards.replaceChildren();
      const elements=[
        ["Версия / SHA", (status.version||"не определена")+" / "+(status.commit||"—")],
        ["Игровой месяц",status.month],
        ["Онлайн сейчас",online.online],
        ["Пик за 24 часа",online.peak_24h],
        ["Ревизия настроек",status.revision],
        ["Аккаунтов",status.accounts?.accounts??"—"],
        ["Статус базы",status.database?.status??"неизвестен"],
        ["Время работы, с",status.uptime_seconds]
      ];
      elements.forEach(([label,value])=>{
        const box=el("article",undefined,"card");
        box.append(el("small",label),el("strong",value));cards.append(box);
      });
      canvasChart(online.history||[]);
      show("dashboarderrors","Ошибки за сутки: "+(status.errors_24h??"нет метрики")+
        "\nРезервная копия: "+(status.backup_age_seconds==null?"нет метрики":status.backup_age_seconds+" с")+
        "\nВерсии клиентов: "+JSON.stringify(online.versions||[]));
      show("dashboardmessage","Обновлено: "+new Date().toLocaleTimeString("ru-RU"));
    }catch(e){show("dashboardmessage","Ошибка: "+describeError(e),true);}
  }
  async function refreshOnline() {
    try {
      const data=await read("online/players");
      const root=byId("onlineplayers");root.replaceChildren();
      data.players.forEach(p=>{
        const card=el("article",undefined,"runtime-row");
        card.append(el("strong",p.username),el("p","Версия: "+(p.version||"—")+" · Город: "+(p.city||"—")+
          " · Активность: "+time(p.last_seen)));
        const button=el("button","Показать");
        button.onclick=()=>{window.location.hash="players";byId("playerq").value=p.username;byId("playersearch").click();};
        card.append(button);root.append(card);
      });
      if (!data.players.length) root.append(el("p","Сейчас нет активных игроков"));
      show("onlinemessage","Онлайн: "+data.players.length);
    }catch(e){show("onlinemessage","Ошибка: "+describeError(e),true);}
  }
  async function refreshRevisions() {
    try {
      const data=await read("revisions");
      const root=byId("revisionslist");root.replaceChildren();
      data.revisions.forEach(item=>{
        const card=el("article",undefined,"runtime-row");
        card.append(el("strong","Ревизия "+item.revision),el("p",time(item.at)+
          " · "+item.actor+" · "+item.comment));
        const compare=el("button","Сравнить");
        compare.onclick=()=>{
          const previous=data.revisions.find(p=>p.revision===item.revision-1);
          const current=item.snapshot.values;
          const before=previous?.snapshot?.values||{};
          const changed=Object.keys({...before,...current}).filter(k=>JSON.stringify(before[k])!==JSON.stringify(current[k]));
          show("revisionsmessage","Изменения ревизии "+item.revision+": "+(changed.length ? changed.map(k=>k+
            ": "+JSON.stringify(before[k]??"по умолчанию")+" → "+JSON.stringify(current[k]??"по умолчанию")).join("; "):"нет изменений параметров"));
        };
        const undo=el("button","Откатить");
        undo.onclick=async()=>{
          if(!confirm("Создать новую ревизию из версии "+item.revision+"? Это изменит настройки игроков."))return;
          try {
            const res=await write("config/rollback",{revision:item.revision,confirm:true,
              expected_revision:config?.revision});
            show("revisionsmessage","Создана ревизия "+res.revision+" из "+item.revision);
            await refreshConfig();await refreshRevisions();
          }catch(e){show("revisionsmessage","Ошибка: "+describeError(e),true);}
        };
        card.append(compare,undo);root.append(card);
      });
      if(!data.revisions.length)root.append(el("p","Ревизий пока нет"));
    }catch(e){show("revisionsmessage","Ошибка: "+describeError(e),true);}
  }
  byId("flagsrefresh").onclick=()=>refreshConfig().catch(e=>show("flagsmessage","Ошибка: "+describeError(e),true));
  byId("paramsrefresh").onclick=()=>refreshConfig().catch(e=>show("paramsmessage","Ошибка: "+describeError(e),true));
  byId("dashboardrefresh").onclick=refreshDashboard;
  byId("onlinerefresh").onclick=refreshOnline;
  byId("revisionsrefresh").onclick=refreshRevisions;
  byId("maintenancebutton").onclick=async()=>{
    try {
      await refreshConfig();
      const item=config.parameters.find(p=>p.key==="MAINTENANCE_MODE");
      if(!item)return;
      if(!confirm("Изменить режим обслуживания? Игроки увидят изменение сразу."))return;
      await write("config/set",{changes:{MAINTENANCE_MODE:!item.value},
        confirm:true,comment:"Режим обслуживания",expected_revision:config.revision});
      await refreshConfig();show("maintenancemessage","Режим изменён");
    }catch(e){show("maintenancemessage","Ошибка: "+describeError(e),true);}
  };
  byId("maintenancepublish").onclick=async()=>{
    try {
      await write("announce",{text:byId("maintenanceannouncement").value.trim()});
      show("maintenancemessage","Объявление сохранено");
    }catch(e){show("maintenancemessage","Ошибка: "+describeError(e),true);}
  };
  byId("client-save").onclick=async()=>{
    try {
      if (!config) await refreshConfig();
      const min=Number(byId("client-minversion").value);
      const recommended=Number(byId("client-recversion").value);
      const title=byId("client-hqtitle").value.trim();
      if (!Number.isSafeInteger(min) || !Number.isSafeInteger(recommended) ||
          min<0 || recommended<min || recommended>1000000000 || title.length>200) {
        show("client-message","Неверные версии или длина названия",true);return;
      }
      if (!confirm("Сохранить новую ревизию клиентской конфигурации? Без отдельной подписи игроки не увидят изменения.")) return;
      const texts={...(config.client?.texts||{})};
      if(title) texts.hq_title=title; else delete texts.hq_title;
      const result=await write("config/client",{
        changes:{texts,min_version:min,recommended_version:recommended},
        expected_revision:config.revision,confirm:true
      });
      show("client-message","Черновик ревизии "+result.revision+" сохранён, требуется подпись");
      await refreshConfig();await refreshRevisions();
    }catch(e){show("client-message","Ошибка: "+describeError(e),true);}
  };
  byId("configcandidate").onclick=async()=>{
    try {
      const candidate=await read("config/candidate");
      const bytes=Uint8Array.from(atob(candidate.payload_b64),c=>c.charCodeAt(0));
      const hash=Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",bytes)))
        .map(x=>x.toString(16).padStart(2,"0")).join("");
      show("candidatesummary","Ревизия "+candidate.revision+"\nSHA-256: "+hash+
        "\nДлина: "+bytes.length+" байт\nПодписать можно только локальным инструментом администратора.");
    }catch(e){show("candidatesummary","Ошибка: "+describeError(e),true);}
  };
  // The host's normal connect action owns the token; reading the panels only
  // after successful auth avoids asking for credentials twice.
  // The legacy connection request finishes asynchronously. Refresh when the
  // connection state actually changes, not after an arbitrary 700 ms delay.
  const observer = new MutationObserver(() => {
    if (byId("status").textContent.trim() !== "Подключено") return;
    refreshConfig().catch(e=>show("flagsmessage","Ошибка: "+describeError(e),true));
    refreshDashboard();refreshOnline();refreshRevisions();
  });
  observer.observe(byId("status"), {childList:true,characterData:true,subtree:true});
})();
