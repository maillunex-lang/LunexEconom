"use strict";
const REPO="maillunex-lang/LunexEconom",API="https://api.github.com/repos/"+REPO,RAW="https://raw.githubusercontent.com/"+REPO+"/main/";
const fallback=[
["0.1","Foundation","В работе","Godot Android, API, авторизация, PostgreSQL, финансовый журнал, CI"],
["0.2","Isometric World","Запланировано","Один регион, процедурная карта, участки, чанки и жесты"],
["0.3","Economy Core","Запланировано","Первая агроцепочка, склады, труд, спрос и магазины"],
["0.4","Online Alpha","Запланировано","Сделки, контракты, общий мир, закрытая альфа"],
["0.5","Living Economy","Запланировано","NPC-конкуренты, отрасли, холдинги, логистика и НИИ"],
["0.6","Financial Systems","Запланировано","Банки, кредиты, налоги и банкротства"],
["0.7","Regions & Government","Запланировано","20 регионов, межрегиональная логистика и политика"],
["0.8","Social MMO","Запланировано","Альянсы, совместные проекты, биржа, сообщения"],
["0.9","Open Beta","Запланировано","Подписка, оптимизация, нагрузочные тесты, обновления"],
["1.0","Release","Запланировано","Стабилизация, релиз, документация и поддержка"]
];
const taskFallback=[
["BE-001","Изолированный репозиторий и рабочая область","На проверке"],
["BE-002","Серверные контракты","В работе"],
["BE-003","Транзакционный финансовый реестр","Запланировано"],
["BE-004","PostgreSQL и миграции","Запланировано"],
["BE-005","Игровые часы","В работе"],
["BE-006","Android-клиент Godot","В работе"],
["BE-007","MMO-синхронизация","Запланировано"],
["BE-008","CI и APK","Запланировано"],
["BE-009","Тесты целостности","В работе"],
["BE-010","Изометрическая дизайн-система","Запланировано"]
];
function parseRoadmap(md){
 const stages=[],tasks=[];for(const line of md.split("\n")){
 const cols=line.trim().replace(/^\||\|$/g,"").split("|").map(s=>s.trim());
 if(cols.length===5&&/^\d\.\d$/.test(cols[0])){let status=cols[4].replace(/[🟡⬜🧪✅⛔]/gu,"").trim();stages.push([cols[0],cols[3].split(":")[0].trim(),status,cols[3].split(":").slice(1).join(":").trim()]);}
 if(cols.length===5&&/^BE-\d{3}$/.test(cols[0])){tasks.push([cols[0],cols[2],cols[3].replace(/[🟡⬜🧪✅⛔]/gu,"").trim()]);}
 }return{stages:stages.length===10?stages:fallback,tasks:tasks.length?tasks:taskFallback};
}
function el(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e;}
function renderRoadmap(stages,tasks){const root=document.getElementById("roadmap-list");root.replaceChildren();let done=0;
 stages.forEach((s,i)=>{if(/готово/i.test(s[2]))done++;const item=el("article","stage"+(i===0?" open":""));const head=el("button","stage-head");head.type="button";head.setAttribute("aria-expanded",String(i===0));head.append(el("span","stage-number",s[0]));const title=el("span","stage-title",s[1]);title.append(el("span","stage-sub",s[3]));head.append(title);head.append(el("span","pill"+(/работе/i.test(s[2])?" active":""),s[2]));head.append(el("span","chevron","⌄"));const body=el("div","stage-content");body.append(el("p","",i===0?"Задачи Foundation, обновляемые из ROADMAP.md:":"Критерии и зависимости описаны в дорожной карте проекта."));
 if(i===0){tasks.forEach(t=>{const row=el("div","task");row.append(el("span","mark",/готово/i.test(t[2])?"✓":/работе/i.test(t[2])?"◐":"○"));row.append(el("span","",t[0]+" · "+t[1]));row.append(el("small","",t[2]));body.append(row);});}
 const link=el("a","text-link","Читать критерии в GitHub ↗");link.href="https://github.com/"+REPO+"/blob/main/docs/ROADMAP.md";link.target="_blank";link.rel="noopener";body.append(link);head.addEventListener("click",()=>{item.classList.toggle("open");head.setAttribute("aria-expanded",String(item.classList.contains("open")));});item.append(head,body);root.append(item);});
 document.getElementById("done-count").textContent=done+"/10";
}
async function loadRoadmap(){renderRoadmap(fallback,taskFallback);try{const r=await fetch(RAW+"docs/ROADMAP.md?ts="+Date.now(),{cache:"no-store"});if(!r.ok)throw Error("GitHub "+r.status);const parsed=parseRoadmap(await r.text());renderRoadmap(parsed.stages,parsed.tasks);document.getElementById("source-status").textContent="Источник: ROADMAP.md · данные загружены из GitHub";}catch(e){document.getElementById("source-status").textContent="Показан сохранённый план · GitHub временно недоступен";}}
async function loadCommits(){const root=document.getElementById("commit-list");try{const r=await fetch(API+"/commits?sha=main&per_page=6",{headers:{Accept:"application/vnd.github+json"}});if(!r.ok)throw Error("GitHub "+r.status);const data=await r.json();root.replaceChildren();data.forEach(c=>{const a=el("a","commit");a.href=c.html_url;a.target="_blank";a.rel="noopener";a.append(el("span","hash",c.sha.slice(0,7)));a.append(el("span","message",c.commit.message.split("\n")[0]));const t=el("time","",new Date(c.commit.author.date).toLocaleDateString("ru-RU",{day:"numeric",month:"short",year:"numeric"}));a.append(t);root.append(a);});if(!data.length)root.append(el("div","empty","Коммитов пока нет."));}catch(e){root.replaceChildren(el("div","empty","История временно недоступна. Откройте GitHub по ссылке ниже."));}}
async function loadApk(){const root=document.getElementById("apk-state");root.textContent="APK пока не опубликована. Подписанного тестового релиза ещё нет.";try{const r=await fetch("./release.json?ts="+Date.now(),{cache:"no-store"});if(!r.ok)return;const data=await r.json();if(data.status!=="published"||!data.url||!data.version)return;const url=new URL(data.url,location.href);if(url.protocol!=="https:"||!(url.hostname==="rikagro.ru"||url.hostname==="github.com"||url.hostname==="objects.githubusercontent.com"))return;if(!/\.apk(?:\?|$)/i.test(url.pathname))return;root.replaceChildren();const link=el("a","", "Скачать APK · "+data.version+" ↓");link.href=url.href;link.rel="noopener";root.append(link);if(data.sha256)root.append(el("p","", "SHA-256: "+data.sha256));}catch(e){}}
loadRoadmap();loadCommits();loadApk();
