"""Пять вариантов мобильной доски портала (HTML, стекло). Данные из docs/work_plan.json. Запуск: python tools/mockups/portal_phone_concepts.py"""
import json
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "portal" / "mockups" / "phone"
plan = json.loads((ROOT / "docs" / "work_plan.json").read_text(encoding="utf-8"))
P = {p["id"]: p for p in plan["packages"]}
ST = {"A1": "accepted", "B1": "accepted", "A2": "issued", "B2": "submitted", "A3": "ready"}
def st(i): return ST.get(i, "queue")
NAME = {"accepted": "Принято", "submitted": "Ждёт приёмки", "issued": "У исполнителя", "ready": "Можно выдавать", "queue": "В очереди"}
def S(i): return P[i].get("short", P[i]["title"][:26])
CSS = """
:root{--ink:#0F1C16;--mut:#4A5E54;--edge:rgba(255,255,255,.78);--g:rgba(255,255,255,.55);--g2:rgba(255,255,255,.34);--gs:rgba(255,255,255,.78);--acc:#1F7A4D;--okb:rgba(70,200,130,.34);--ok:#17613D;--wb:rgba(255,200,80,.42);--w:#8A5A00;--ib:rgba(90,150,235,.32);--i:#1B55A0;--hair:rgba(15,28,22,.12);--A:#1F7A4D;--B:#1B55A0;--sh:0 10px 30px rgba(20,50,35,.16),0 2px 6px rgba(20,50,35,.08)}
*{box-sizing:border-box}body{margin:0;width:390px;height:844px;overflow:hidden;font:14px/1.45 Inter,system-ui,sans-serif;color:var(--ink);position:relative;background:#DDE8DF}
.bg{position:absolute;inset:0;z-index:0;overflow:hidden}.wrap,.top{position:relative;z-index:1}.tabs{z-index:3}.bg i{position:absolute;border-radius:50%;filter:blur(60px)}.bg i:nth-child(1){width:360px;height:360px;left:-110px;top:-80px;background:#7BE0A6}.bg i:nth-child(2){width:380px;height:380px;right:-140px;top:200px;background:#7FB6FF;opacity:.65}.bg i:nth-child(3){width:320px;height:320px;left:20%;bottom:-140px;background:#FFD58A;opacity:.6}
h1,h2,h3{font-family:"Space Grotesk",system-ui,sans-serif;margin:0}
.glass{background:var(--g);backdrop-filter:blur(22px) saturate(1.7);border:1px solid var(--edge);box-shadow:inset 0 1px 0 rgba(255,255,255,.6),var(--sh);position:relative}
.top{margin:12px 12px 0;border-radius:22px;padding:8px 12px;display:flex;align-items:center;gap:8px;font:700 15px "Space Grotesk"}
.top small{font:500 13px Inter;color:var(--mut)}.top .sp{flex:1}
.logo{width:26px;height:26px;border-radius:8px;background:linear-gradient(135deg,#7BE0A6,#1F7A4D);display:inline-block}
.tabs{position:absolute;left:12px;right:12px;bottom:14px;border-radius:26px;display:flex;padding:6px;gap:2px;background:var(--gs)}
.tabs div{flex:1;text-align:center;font-size:11px;color:var(--mut);padding:7px 0;border-radius:20px}.tabs div.on{background:rgba(31,122,77,.18);color:#15603C;font-weight:600}.tabs b{display:block;font-size:17px;line-height:1.1}
.wrap{padding:12px 14px;display:flex;flex-direction:column;gap:12px}
.pill{font-size:11.5px;font-weight:600;padding:2px 9px;border-radius:999px;display:inline-flex;gap:5px;align-items:center;border:1px solid var(--edge)}.pill:before{content:"";width:6px;height:6px;border-radius:50%;background:currentColor}
.accepted,.ready{background:var(--okb);color:var(--ok)}.issued{background:var(--wb);color:var(--w)}.submitted{background:var(--ib);color:var(--i)}.queue{background:var(--g2);color:#6B7C73}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;font-weight:600;font-size:14px;min-height:46px;padding:0 18px;border-radius:999px;background:var(--g2);border:1px solid var(--edge)}.btn.p{background:linear-gradient(180deg,#3E9A6A,#1F7A4D);color:#fff;box-shadow:0 6px 16px rgba(31,122,77,.4)}
.pid{font:700 14px "Space Grotesk";margin-right:5px}.mut{color:var(--mut)}.sm{font-size:12.5px}
.card{border-radius:24px;padding:14px}
.dot{width:10px;height:10px;border-radius:50%;display:inline-block}.dA{background:var(--A)}.dB{background:var(--B)}
"""
def doc(name, title, body, extra="", active=0):
    tabs = "".join(f'<div class="{"on" if i==active else ""}"><b>{ic}</b>{t}</div>' for i, (ic, t) in enumerate([("▤", "Проекты"), ("◎", "Доска"), ("✎", "Идеи"), ("?", "Справка")]))
    html = f'''<!doctype html><meta charset="utf-8"><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Space+Grotesk:wght@500;600;700&display=swap"><style>{CSS}{extra}</style>
<div class="bg"><i></i><i></i><i></i></div><div class="top glass"><span class="logo"></span>{escape(title)}<span class="sp"></span><small>⚙</small></div>{body}<div class="tabs glass">{tabs}</div>'''
    (OUT / f"{name}.html").write_text(html, encoding="utf-8")

def ring(pct, size=64, w=8, col="#1F7A4D"):
    import math
    r = (size - w) / 2; L = 2 * math.pi * r
    return f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" style="transform:rotate(-90deg)"><circle cx="{size/2}" cy="{size/2}" r="{r}" fill="none" stroke="rgba(15,28,22,.12)" stroke-width="{w}"/><circle cx="{size/2}" cy="{size/2}" r="{r}" fill="none" stroke="{col}" stroke-width="{w}" stroke-linecap="round" stroke-dasharray="{L}" stroke-dashoffset="{L*(1-pct/100)}"/></svg>'

# 1. Фокус
def c1():
    def big(i, act, hint):
        p = P[i]; k = st(i); L = plan["lanes"][p["lane"]]
        return f'''<div class="glass card" style="flex:0 0 306px;border-left:5px solid var(--{p["lane"]})"><div class="mut sm">Линия {p["lane"]} · {L["name"]}</div><div style="margin:6px 0"><span class="pill {k}">{NAME[k]}</span></div><h2 style="font-size:21px;margin:2px 0 6px"><span class="pid" style="color:var(--{p["lane"]})">{i}</span>{escape(S(i))}</h2><div class="mut sm" style="min-height:54px">{hint}</div><div class="btn p" style="width:100%;margin-top:6px">{act}</div></div>'''
    rows = "".join(f'<div class="glass" style="border-radius:18px;padding:10px 12px;display:flex;align-items:center;gap:10px"><span class="dot d{P[i]["lane"]}"></span><div style="flex:1"><b class="pid">{i}</b>{escape(S(i))}</div><span class="pill {st(i)}">{NAME[st(i)] if st(i)!="queue" else "после "+",".join(P[i]["depends_on"])}</span></div>' for i in ["A3", "B3", "A4", "B4", "A5"])
    body = f'''<div class="wrap"><div class="row" style="display:flex;align-items:center;gap:12px">{ring(9,58,7)}<div><h1 style="font-size:22px">Башкирия</h1><div class="mut sm">Принято 2 из 22 · 9%</div></div></div>
<div style="font:600 13px Inter;color:var(--mut);text-transform:uppercase;letter-spacing:.06em">Сейчас · листайте →</div>
<div style="display:flex;gap:10px;margin:0 -14px;padding:0 14px;overflow:hidden">{big("A2","Исполнитель сдал","Исполнитель работает. Когда пришлёт отчёт, нажмите «Исполнитель сдал».")}{big("B2","Принять, в архив","Сдано. Директор проверил и слил? Нажмите «Принять».")}</div>
<div style="text-align:center;font-size:20px;letter-spacing:6px;color:#1F7A4D;line-height:1">●<span style="opacity:.3"> ●</span></div>
<div style="font:600 13px Inter;color:var(--mut);text-transform:uppercase;letter-spacing:.06em">Дальше</div>{rows}</div>'''
    doc("v1_focus", "Башкирия", body, active=1)

# 2. Две линии сверху вниз
def c2():
    steps = list(range(1, 8))
    css = ".r{display:grid;grid-template-columns:22px 1fr 1fr;gap:8px;align-items:stretch;position:relative}.n{font:700 12px 'Space Grotesk';color:var(--mut);text-align:center;padding-top:14px}.t{border-radius:16px;padding:8px 10px;min-height:56px;position:relative}.t b{font:700 13px 'Space Grotesk'}.t div{font-size:12px;line-height:1.25}.trk:before{content:'';position:absolute;left:50%;top:-12px;bottom:-12px;width:3px;background:rgba(15,28,22,.1);transform:translateX(-50%);z-index:0}.t.accepted{background:var(--okb)}.t.issued{background:var(--wb)}.t.submitted{background:var(--ib)}.t.ready{border:2px solid var(--acc);box-shadow:0 0 0 4px rgba(31,122,77,.2)}"
    def cell(i):
        k = st(i); cls = {"queue": "queue"}.get(k, k)
        mark = {"accepted": "✓", "issued": "●", "submitted": "◔", "ready": "→", "queue": ""}[k]
        return f'<div class="t glass {cls}"><b style="color:var(--{P[i]["lane"]})">{i}</b> <span style="float:right;font-weight:700">{mark}</span><div>{escape(S(i))}</div></div>'
    rows = "".join(f'<div class="r"><div class="n">{s}</div>{cell("A"+str(s))}{cell("B"+str(s))}</div>' for s in steps)
    body = f'''<div class="wrap"><div style="display:flex;align-items:center;justify-content:space-between"><h1 style="font-size:22px">Башкирия</h1><span class="pill accepted">9% · 2 из 22</span></div>
<div class="glass card" style="padding:10px 12px;display:flex;gap:8px"><div style="flex:1"><span class="dot dA"></span> <b>Сервер</b><div class="mut sm">A2 у исполнителя</div></div><div style="flex:1"><span class="dot dB"></span> <b>Клиент</b><div class="mut sm">B2 ждёт приёмки</div></div></div>
<div style="display:grid;grid-template-columns:22px 1fr 1fr;gap:8px;font:600 11px Inter;color:var(--mut)"><span>шаг</span><span>СЕРВЕР</span><span>КЛИЕНТ</span></div>{rows}</div>'''
    doc("v2_two_lines", "Башкирия", body, css, 1)

# 3. По действиям
def c3():
    def card(i, label, act, kind):
        k = st(i)
        return f'<div class="glass card" style="padding:12px 14px"><div style="display:flex;align-items:center;gap:8px"><span class="dot d{P[i]["lane"]}"></span><b class="pid" style="margin:0">{i}</b><b style="flex:1">{escape(S(i))}</b><span class="pill {k}">{label}</span></div><div class="btn p" style="width:100%;margin-top:10px;min-height:44px">{act}</div></div>'
    def sec(t, n, col):
        return f'<div style="display:flex;align-items:center;gap:8px;margin-top:4px"><b style="font:700 15px \'Space Grotesk\'">{t}</b><span style="background:{col};border-radius:999px;padding:0 9px;font-weight:700">{n}</span></div>'
    body = f'''<div class="wrap"><div><h1 style="font-size:22px">Башкирия</h1><div class="mut sm">Начните сверху: это ждёт вас</div></div>
<div style="display:flex;gap:6px"><span class="pill ready" style="padding:6px 14px;font-size:13px">Все</span><span class="pill queue" style="padding:6px 14px;font-size:13px">Сервер</span><span class="pill queue" style="padding:6px 14px;font-size:13px">Клиент</span></div>
{sec("Ждёт вашей приёмки",1,"rgba(90,150,235,.4)")}{card("B2","Сдано","Принять, в архив","")}
{sec("Можно выдавать",1,"rgba(70,200,130,.4)")}{card("A3","Готово к выдаче","Взять промпт","")}
{sec("У исполнителей",1,"rgba(255,200,80,.5)")}<div class="glass card" style="padding:12px 14px;display:flex;align-items:center;gap:8px"><span class="dot dA"></span><b class="pid" style="margin:0">A2</b><b style="flex:1">{S("A2")}</b><span class="pill issued">3 дня</span></div>
<div class="glass card" style="padding:12px 14px;display:flex;justify-content:space-between"><b>Позже</b><span class="mut">17 задач ▸</span></div>
<div class="glass card" style="padding:12px 14px;display:flex;justify-content:space-between"><b>Готово</b><span class="mut">2 задачи ▸</span></div></div>'''
    doc("v3_actions", "Башкирия", body, active=1)

# 4. Переключатель линий
def c4():
    css = ".seg{display:flex;padding:4px;border-radius:999px;gap:2px}.seg div{flex:1;text-align:center;padding:9px 0;border-radius:999px;font-weight:600}.seg div.on{background:linear-gradient(180deg,#3E9A6A,#1F7A4D);color:#fff}.st{display:grid;grid-template-columns:30px 1fr;gap:10px}.rail{position:relative}.rail:before{content:'';position:absolute;left:14px;top:0;bottom:-10px;width:3px;background:rgba(15,28,22,.12)}.rail i{position:relative;z-index:1;width:30px;height:30px;border-radius:50%;display:flex;align-items:center;justify-content:center;font:700 13px 'Space Grotesk';background:#fff;border:3px solid rgba(15,28,22,.15)}.rail i.ok{background:#1F7A4D;color:#fff;border-color:#1F7A4D}.rail i.cur{border-color:#8A5A00;color:#8A5A00;box-shadow:0 0 0 5px rgba(138,90,0,.18)}.rail i.rd{border-color:#1F7A4D;color:#1F7A4D;box-shadow:0 0 0 5px rgba(31,122,77,.18)}"
    items = ""
    for i in ["A1", "A2", "A3", "A4", "A5", "A6"]:
        k = st(i); mark = {"accepted": ('ok', "✓"), "issued": ('cur', "●"), "ready": ('rd', "→")}.get(k, ('', P[i]["step"]))
        if i == "A2":
            inner = f'<div class="glass card" style="padding:12px 14px"><div style="display:flex;justify-content:space-between"><b><span class="pid" style="color:var(--A)">A2</span>{S(i)}</b><span class="pill issued">У исполнителя</span></div><div class="mut sm" style="margin:6px 0">Исполнитель работает. Когда пришлёт отчёт, нажмите «Сдал».</div><div style="display:flex;gap:8px"><div class="btn p" style="flex:1">Исполнитель сдал</div><div class="btn">Промпт</div></div></div>'
        else:
            inner = f'<div style="padding:5px 0;opacity:{1 if k!="queue" else .6}"><b class="pid" style="color:var(--A)">{i}</b>{escape(S(i))} <span class="mut sm">{NAME[k] if k!="queue" else ""}</span></div>'
        items += f'<div class="st"><div class="rail"><i class="{mark[0]}">{mark[1]}</i></div><div>{inner}</div></div>'
    body = f'''<div class="wrap"><div class="seg glass"><div class="on">Сервер · A</div><div>Клиент · B</div><div>Обе</div></div>
<div class="glass card" style="padding:10px 14px;display:flex;align-items:center;gap:10px"><span class="dot dB"></span><div style="flex:1" class="sm"><b>Параллельно:</b> B2 ждёт приёмки</div><b style="color:#1B55A0">Открыть ›</b></div>
<div class="mut sm">ChatGPT №1 · шаги 1–6 из 11</div>{items}</div>'''
    doc("v4_switch", "Башкирия", body, css, 1)

# 5. Кольца
def c5():
    css = ".rings{position:relative;width:230px;height:230px;margin:2px auto}.rings svg{position:absolute;left:0;top:0}.mid{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center}.mid b{font:700 34px 'Space Grotesk'}.chip{flex:0 0 150px;border-radius:20px;padding:10px 12px}"
    r1, r2 = ring(18, 230, 16, "#1F7A4D"), ring(9, 186, 16, "#1B55A0")
    def now(i, t):
        k = st(i)
        return f'<div class="glass card" style="padding:12px 14px;display:flex;align-items:center;gap:10px"><span class="dot d{P[i]["lane"]}" style="width:12px;height:12px"></span><div style="flex:1"><b class="pid" style="margin:0">{i}</b> <b>{S(i)}</b><div class="mut sm">{t}</div></div><span class="pill {k}">{NAME[k]}</span></div>'
    nxt = "".join(f'<div class="glass chip"><div class="mut sm">шаг {P[i]["step"]} · линия {P[i]["lane"]}</div><b class="pid" style="margin:0">{i}</b><div class="sm">{escape(S(i))}</div></div>' for i in ["A3", "B3", "A4", "B4"])
    body = f'''<div class="wrap"><div style="text-align:center"><h1 style="font-size:22px">Башкирия</h1></div>
<div class="rings"><div style="position:absolute;left:0;top:0">{r1}</div><div style="position:absolute;left:22px;top:22px">{r2}</div><div class="mid"><b>9%</b><div class="mut sm">2 из 22 задач</div></div></div>
<div style="display:flex;justify-content:center;gap:16px" class="sm"><span><span class="dot dA"></span> Сервер 2/11</span><span><span class="dot dB"></span> Клиент 1/11</span></div>
{now("A2","Ждём отчёт исполнителя")}{now("B2","Проверьте и примите")}
<div style="font:600 13px Inter;color:var(--mut);text-transform:uppercase;letter-spacing:.06em">Дальше</div><div style="display:flex;gap:8px;margin:0 -14px;padding:0 14px;overflow:hidden">{nxt}</div></div>'''
    doc("v5_rings", "Башкирия", body, css, 1)

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for f in (c1, c2, c3, c4, c5):
        f()
