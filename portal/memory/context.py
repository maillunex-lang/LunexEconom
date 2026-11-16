"""Контекст для ИИ: короткая сводка проекта на одну страницу. Секреты вырезаются, размер ограничен бюджетом."""
from __future__ import annotations

from . import repomap
from .redact import redact

STATUS_RU = {"planned": "в плане", "issued": "у исполнителя", "submitted": "сдано, ждёт приёмки", "accepted": "принято"}
ROLES = {"director": "ИИ-директор", "executor": "исполнитель", "reviewer": "проверяющий"}


def _clip(text, n):
    text = redact(text or "")
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _plan_section(plan, states):
    pk = plan.get("packages", [])
    done = [p for p in pk if states.get(p["id"], {}).get("status", p.get("status")) in ("accepted", "done")]
    lines = ["Всего пакетов: %d, принято: %d." % (len(pk), len(done))]
    for p in pk:
        st = states.get(p["id"], {}).get("status") or ("accepted" if p.get("status") == "done" else "planned")
        if st == "accepted":
            continue
        deps = ", ".join(p.get("depends_on", [])) or "нет"
        lines.append("- %s «%s» (линия %s): %s; зависит от: %s." % (p["id"], p.get("short") or p["title"], p["lane"], STATUS_RU.get(st, st), deps))
    return "\n".join(lines)


def _next_actions(plan, states):
    pk = {p["id"]: p for p in plan.get("packages", [])}
    st = lambda i: states.get(i, {}).get("status") or ("accepted" if pk[i].get("status") == "done" else "planned")
    acts = []
    for i, p in pk.items():
        s = st(i)
        if s == "submitted":
            acts.append("Принять или вернуть %s (сдано исполнителем)." % i)
        elif s == "planned" and all(d in pk and st(d) == "accepted" for d in p.get("depends_on", [])):
            acts.append("Можно выдавать %s «%s» (линия %s)." % (i, p.get("short") or p["title"], p["lane"]))
    return acts or ["Все выданные задачи в работе; ждать отчётов."]


def build(project, plan, states, decisions=None, lessons=None, events=None, open_prs=None, items=None, role="director", max_chars=6000):
    """Возвращает markdown. Разделы в порядке важности; при нехватке бюджета нижние сокращаются или отбрасываются."""
    plan = plan or {"packages": []}
    states = states or {}
    head = ["# Контекст проекта «%s»" % project.get("name", ""), "Для: %s. Репозиторий: %s. Основная ветка: %s." % (ROLES.get(role, role), project.get("repo") or "не указан", project.get("branch") or "main")]
    if project.get("description"):
        head.append("О проекте: " + _clip(project["description"], 400))
    sections = [("Что делать сейчас", "\n".join("- " + a for a in _next_actions(plan, states))),
                ("План и статусы", _plan_section(plan, states))]
    if lessons:
        sections.append(("Ловушки и правила проекта", "\n".join("- " + _clip(l["text"], 300) for l in lessons[-12:])))
    if decisions:
        sections.append(("Решения владельца (последние)", "\n".join("- %s%s" % (d.get("date", "") + " " if d.get("date") else "", _clip(d["text"] if d["text"].startswith(d["title"][:30]) else d["title"] + ": " + d["text"], 240)) for d in decisions[-10:])))
    if open_prs:
        sections.append(("Открытые PR", "\n".join("- #%s %s (%s)" % (p.get("number"), _clip(p.get("title", ""), 90), p.get("ci", "CI неизвестен")) for p in open_prs[:10])))
    if events:
        sections.append(("Последние события", "\n".join("- %s" % _clip(e if isinstance(e, str) else e.get("text", ""), 140) for e in events[-8:])))
    if items:
        sections.append(("Карта репозитория", repomap.render(items, max_chars=1800)))
    out, used = ["\n".join(head)], len(head[0])
    for title, body in sections:
        if not body.strip():
            continue
        block = "## %s\n%s" % (title, body)
        room = max_chars - used
        if room < 120:
            break
        if len(block) > room:
            block = block[: room - 1].rstrip() + "…"
        out.append(block)
        used += len(block) + 2
    text = "\n\n".join(out)
    return redact(text)[:max_chars]
