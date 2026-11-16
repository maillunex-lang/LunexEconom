"""Три концепта доски портала (HTML), данные берутся из docs/work_plan.json. Запуск: python tools/mockups/portal_concepts.py"""
import json
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "portal" / "mockups" / "concepts"
plan = json.loads((ROOT / "docs" / "work_plan.json").read_text(encoding="utf-8"))
P = {p["id"]: p for p in plan["packages"]}
# демонстрационные статусы (пример, не реальное состояние)
ST = {"A1": "accepted", "B1": "accepted", "A2": "issued", "B2": "submitted", "A3": "ready", "B3": "queue"}
def st(i): return ST.get(i, "queue")
NAME = {"accepted": "Принято", "submitted": "Ждёт приёмки", "issued": "У исполнителя", "ready": "Можно выдавать", "queue": "В очереди"}
ICON = {"accepted": "✓", "submitted": "◔", "issued": "●", "ready": "→", "queue": "·"}
WAVE = {1: "Волна 1–3", 2: "Волна 1–3", 3: "Волна 2", 4: "Волна 2", 5: "Волна 3", 6: "Волна 3–5", 7: "Волна 2–4", 8: "Волна 4", 9: "Волна 4", 10: "Волна 4", 11: "Волна 5"}
CSS = """
:root{--bg:#EDF1EA;--bg2:#E3EAE0;--s:#fff;--s2:#F4F7F2;--ink:#13201A;--mut:#566860;--line:#D2DBD3;--acc:#2B7A52;--acc2:#1E5C3D;--okb:#DAF0E3;--ok:#1E6B45;--wb:#FBEED2;--w:#9A6200;--ib:#DFEBF9;--i:#1F5FA6;--lock:#8A978F;--A:#2B7A52;--B:#1F5FA6}
*{box-sizing:border-box}body{margin:0;font:14px/1.5 Inter,system-ui,sans-serif;color:var(--ink);background:radial-gradient(1200px 500px at 85% -10%,var(--bg2),transparent),var(--bg);width:1440px;padding:0 0 40px}
h1,h2,h3{font-family:"Space Grotesk",system-ui,sans-serif;margin:0}
.top{height:60px;background:#fff9;border-bottom:1px solid var(--line);display:flex;align-items:center;padding:0 40px;gap:14px;font-weight:700;font-size:17px}
.top span{font-weight:500;color:var(--mut);font-size:14px}
.wrap{padding:22px 40px;display:flex;flex-direction:column;gap:18px}
.card{background:var(--s);border:1px solid var(--line);border-radius:18px;padding:18px;box-shadow:0 1px 2px #13201a0f,0 8px 24px #13201a10}
.row{display:flex;gap:12px;align-items:center}.sp{justify-content:space-between}
.pill{font-size:12px;font-weight:600;padding:3px 10px;border-radius:999px;display:inline-flex;gap:6px;align-items:center}
.pill:before{content:"";width:7px;height:7px;border-radius:50%;background:currentColor}
.accepted,.ready{background:var(--okb);color:var(--ok)}.issued{background:var(--wb);color:var(--w)}.submitted{background:var(--ib);color:var(--i)}.queue{background:var(--s2);color:var(--lock);border:1px solid var(--line)}
.btn{font-weight:600;padding:10px 16px;border-radius:12px;border:1px solid var(--line);background:#fff;font-size:14px}.btn.p{background:var(--acc);color:#fff;border-color:var(--acc)}
.mut{color:var(--mut)}.sm{font-size:13px}.pid{font-family:"Space Grotesk";font-weight:700;color:var(--acc);margin-right:6px}
.tiles{display:flex;gap:12px}.tile{flex:1;background:#fff;border:1px solid var(--line);border-radius:14px;padding:12px 16px}.tile b{font:700 24px "Space Grotesk"}
"""

def top(crumb):
    return f'<div class="top"><svg width="26" height="26" viewBox="0 0 32 32"><rect x="2" y="2" width="28" height="28" rx="8" fill="#2B7A52" opacity=".15"/><path d="M9 21l5-10 4 7 2-4 3 7" stroke="#2B7A52" stroke-width="2.4" fill="none" stroke-linecap="round"/></svg>CreatePortal <span>/ {escape(crumb)}</span></div>'

def page(name, body, extra=""):
    html = f'<!doctype html><meta charset="utf-8"><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Space+Grotesk:wght@500;600;700&display=swap"><style>{CSS}{extra}</style>{body}'
    (OUT / f"{name}.html").write_text(html, encoding="utf-8")

def summary():
    n = len(P); acc = sum(1 for k in P if st(k) == "accepted")
    tiles = "".join(f'<div class="tile"><b>{v}</b><div class="mut sm">{t}</div></div>' for v, t in [(acc, "Принято"), (1, "Ждёт приёмки"), (1, "У исполнителя"), (1, "Можно выдавать")])
    return f'<div class="row"><div class="tile" style="max-width:220px"><b>{acc} из {n}</b><div class="mut sm">задач принято</div><div style="height:8px;border-radius:5px;background:#D2DBD3;margin-top:8px"><div style="height:8px;border-radius:5px;background:#2B7A52;width:{100*acc//n}%"></div></div></div>{tiles}</div>'

def now_cards():
    out = ""
    for lane, cur, act, hint in [("A", "A2", "Исполнитель сдал", "Когда исполнитель пришлёт отчёт, нажмите «Исполнитель сдал»"), ("B", "B2", "Принято, в архив", "Директор проверил? Нажмите, чтобы принять и перейти к B3")]:
        L = plan["lanes"][lane]; p = P[cur]
        out += f'''<div class="card" style="flex:1;border-top:4px solid var(--{lane})"><div class="row sp"><div class="mut sm">Линия {lane} · {L["name"]} · {L["who"]}</div><span class="pill {st(cur)}">{NAME[st(cur)]}</span></div>
        <h2 style="font-size:21px;margin:6px 0 4px"><span class="pid">{cur}</span>{escape(p["title"])}</h2><div class="mut sm" style="min-height:40px">{escape(p["goal"][:150])}…</div>
        <div class="row" style="margin-top:12px"><span class="btn p">{act}</span><span class="btn">Скопировать промпт</span></div><div class="mut sm" style="margin-top:8px">{hint}</div></div>'''
    return out

# ---------- Концепт 1: «Дорожки» ----------
def c1():
    steps = sorted({p["step"] for p in P.values()})
    css = ".grid{display:grid;grid-template-columns:90px repeat(11,1fr);gap:8px;align-items:stretch}.lh{font-weight:700;display:flex;align-items:center;gap:8px}.lh i{width:10px;height:36px;border-radius:5px}.sh{text-align:center;font-weight:600;font-size:12px;color:var(--mut)}.sh small{display:block;font-weight:400}.node{border-radius:14px;padding:8px 8px 10px;border:1.5px solid var(--line);background:#fff;min-height:96px;display:flex;flex-direction:column;gap:4px;position:relative}.node b{font:700 15px 'Space Grotesk'}.node .t{font-size:11.5px;line-height:1.3;color:var(--ink)}.node.accepted{background:var(--okb);border-color:#b9dfc8}.node.issued{background:var(--wb);border-color:#EACD8D}.node.submitted{background:var(--ib);border-color:#B9D2F0}.node.ready{border:2px solid var(--acc);box-shadow:0 0 0 4px #2B7A5222}.node.queue{background:transparent;border-style:dashed}.ic{position:absolute;right:8px;top:6px;font-weight:700}.line{height:3px;background:var(--line);align-self:center;border-radius:2px}"
    cells = '<div></div>' + "".join(f'<div class="sh">Шаг {s}<small>{WAVE[s]}</small></div>' for s in steps)
    for lane in ("A", "B"):
        L = plan["lanes"][lane]
        cells += f'<div class="lh"><i style="background:var(--{lane})"></i><div>Линия {lane}<div class="mut sm" style="font-weight:400">{L["name"]}</div></div></div>'
        for s in steps:
            pk = [p for p in P.values() if p["step"] == s and p["lane"] == lane]
            if pk:
                p = pk[0]; k = st(p["id"])
                cells += f'<div class="node {k}"><span class="ic">{ICON[k]}</span><b>{p["id"]}</b><div class="t">{escape(p["title"][:44])}</div></div>'
            else:
                cells += '<div></div>'
    body = f'''{top("Башкирия: Мёд и Нефть")}<div class="wrap"><div class="row sp"><div><h1 style="font-size:28px">Башкирия: Мёд и Нефть</h1><div class="mut">maillunex-lang/LunexEconom · пример данных</div></div><div class="row"><span class="btn">Синхронизировать</span><span class="btn">Протокол для ИИ</span></div></div>
    {summary()}<div class="row" style="align-items:stretch">{now_cards()}</div>
    <div class="card"><div class="row sp" style="margin-bottom:12px"><h2 style="font-size:18px">Дорожки: две линии идут одновременно</h2><div class="row sm mut"><span class="pill accepted">Принято</span><span class="pill submitted">Ждёт приёмки</span><span class="pill issued">У исполнителя</span><span class="pill ready">Можно выдавать</span><span class="pill queue">В очереди</span></div></div><div class="grid">{cells}</div></div></div>'''
    page("concept1_swimlanes", body, css)

# ---------- Концепт 2: «Путь» ----------
def c2():
    steps = sorted({p["step"] for p in P.values()})
    css = ".path{position:relative;padding:10px 0}.spine{position:absolute;left:50%;top:0;bottom:0;width:4px;background:var(--line);transform:translateX(-50%);border-radius:2px}.spine i{display:block;width:4px;background:var(--acc);height:33%;border-radius:2px}.st{display:grid;grid-template-columns:1fr 70px 1fr;align-items:center;margin:14px 0}.dot{width:44px;height:44px;border-radius:50%;margin:auto;display:flex;align-items:center;justify-content:center;font:700 16px 'Space Grotesk';background:#fff;border:3px solid var(--line);position:relative;z-index:1}.dot.done{background:var(--acc);border-color:var(--acc);color:#fff}.dot.cur{border-color:var(--w);color:var(--w);box-shadow:0 0 0 6px #9A620022}.pc{padding:12px 14px;border-radius:14px;border:1px solid var(--line);background:#fff;display:flex;flex-direction:column;gap:3px}.pc.accepted{background:var(--okb);border-color:#b9dfc8}.pc.issued{background:var(--wb)}.pc.submitted{background:var(--ib)}.pc.queue{background:transparent;border-style:dashed}.pc.ready{border:2px solid var(--acc)}"
    rows = ""
    for s in steps[:6]:
        pa = [p for p in P.values() if p["step"] == s and p["lane"] == "A"][0]; pb = [p for p in P.values() if p["step"] == s and p["lane"] == "B"][0]
        both = {st(pa["id"]), st(pb["id"])}
        dot = "done" if both == {"accepted"} else ("cur" if both & {"issued", "submitted", "ready"} else "")
        def card(p):
            k = st(p["id"]); return f'<div class="pc {k}"><div class="row sp"><span><span class="pid">{p["id"]}</span><b>{escape(p["title"][:40])}</b></span><span class="pill {k}">{NAME[k]}</span></div><div class="mut sm">Линия {p["lane"]} · {escape(p["goal"][:70])}…</div></div>'
        rows += f'<div class="st"><div>{card(pa)}</div><div class="dot {dot}">{"✓" if dot=="done" else s}</div><div>{card(pb)}</div></div>'
    body = f'''{top("Башкирия: Мёд и Нефть")}<div class="wrap"><div class="row sp"><div><h1 style="font-size:28px">Башкирия: Мёд и Нефть</h1><div class="mut">Путь проекта: шаги сверху вниз, слева сервер, справа клиент</div></div><div class="row"><span class="btn">Схема</span><span class="btn">Протокол для ИИ</span></div></div>
    {summary()}<div class="card"><div class="row sp"><div class="mut sm" style="font-weight:600">СЕРВЕР (линия A)</div><div class="mut sm" style="font-weight:600">КЛИЕНТ (линия B)</div></div><div class="path"><div class="spine"><i></i></div>{rows}<div class="mut sm" style="text-align:center">…ещё 5 шагов</div></div></div></div>'''
    page("concept2_path", body, css)

# ---------- Концепт 3: «Центр управления» (список + подробности) ----------
def c3():
    css = ".ms{display:grid;grid-template-columns:420px 1fr;gap:16px;align-items:start}.lane{display:flex;flex-direction:column;gap:6px}.li{display:flex;gap:10px;align-items:center;padding:8px 10px;border-radius:12px;border:1px solid transparent}.li .ck{width:22px;height:22px;border-radius:50%;border:2px solid var(--line);display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;flex:none}.li.accepted .ck{background:var(--acc);border-color:var(--acc);color:#fff}.li.issued .ck{border-color:var(--w);color:var(--w)}.li.submitted .ck{border-color:var(--i);color:var(--i)}.li.ready .ck{border-color:var(--acc);color:var(--acc)}.li.sel{background:var(--okb);border-color:#b9dfc8}.li .t{flex:1;min-width:0;font-weight:500}.li.queue{opacity:.6}.det h2{font-size:22px}.bx{background:var(--s2);border:1px solid var(--line);border-radius:12px;padding:12px;font:12.5px/1.5 ui-monospace,monospace;color:var(--mut);height:130px;overflow:hidden}.chip{font-size:12px;border:1px solid var(--line);padding:2px 8px;border-radius:6px;background:var(--s2);color:var(--mut);font-weight:600}.seg{display:flex;gap:6px;margin-bottom:8px}.seg b{font-size:12px;padding:5px 12px;border-radius:999px;background:var(--s2);border:1px solid var(--line)}.seg b.on{background:var(--acc);color:#fff;border-color:var(--acc)}"
    def lane(l):
        L = plan["lanes"][l]; items = ""
        for p in [p for p in P.values() if p["lane"] == l][:7]:
            k = st(p["id"]); sel = " sel" if p["id"] == "B2" else ""
            items += f'<div class="li {k}{sel}"><span class="ck">{ICON[k] if k!="queue" else ""}</span><span class="t"><span class="pid">{p["id"]}</span>{escape(p["title"][:34])}</span><span class="chip">шаг {p["step"]}</span></div>'
        return f'<div class="card"><div class="row sp"><b style="font:700 16px Space Grotesk;color:var(--{l})">Линия {l} · {L["name"]}</b><span class="mut sm">{L["who"]}</span></div><div class="lane" style="margin-top:8px">{items}<div class="mut sm" style="padding:4px 10px">…ещё 4 задачи</div></div></div>'
    p = P["B2"]
    detail = f'''<div class="card det" style="position:sticky;top:10px"><div class="row sp"><div class="mut sm">Линия B · Клиент · шаг {p["step"]}</div><span class="pill submitted">Ждёт приёмки</span></div><h2><span class="pid">B2</span>{escape(p["title"])}</h2><p class="mut">{escape(p["goal"])}</p>
    <div class="row" style="flex-wrap:wrap"><span class="chip">CI: успех</span><span class="chip">PR #112</span><span class="chip">сдано 14:05</span><span class="chip">зависит от B1</span></div>
    <div class="seg" style="margin-top:12px"><b class="on">Приёмка</b><b>Промпт</b><b>Критерии</b><b>Журнал</b></div>
    <div class="bx">✓ Пробное слияние с main без конфликтов<br>✓ Файлы только в зоне линии B<br>✓ Все клиентские проверки прошли<br>○ Слито в main</div>
    <div class="row" style="margin-top:14px"><span class="btn p">Принято, в архив</span><span class="btn">Вернуть исполнителю</span><span class="btn">Скопировать промпт</span></div></div>'''
    body = f'''{top("Башкирия: Мёд и Нефть")}<div class="wrap"><div class="row sp"><div><h1 style="font-size:28px">Башкирия: Мёд и Нефть</h1><div class="mut">Слева порядок задач по линиям, справа выбранная задача</div></div><div class="row"><span class="btn">Протокол для ИИ</span></div></div>{summary()}
    <div class="ms"><div class="lane" style="gap:14px">{lane("A")}{lane("B")}</div>{detail}</div></div>'''
    page("concept3_master_detail", body, css)

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    c1(); c2(); c3()
