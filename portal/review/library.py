"""Библиотека удачных промптов: задания, принятые с первого раза, запоминаются как образцы для похожих новых заданий."""
from __future__ import annotations

import re

MAX_EXAMPLES = 40
STOP = set("и в на с по для из к от до что как это при или не а но же за то все всё также его их ее её".split())


def keywords(text):
    return {w for w in re.findall(r"[a-zа-я0-9_]{4,}", (text or "").lower()) if w not in STOP}


def record(library, task_id, title, goal, prompt, returns, lane):
    """Добавляет образец только если задача принята без возвратов. Возвращает новый список."""
    if returns != 0:
        return library
    item = {"id": task_id, "title": title, "lane": lane, "goal": goal[:600], "prompt": prompt[:6000]}
    return ([x for x in library if x["id"] != task_id] + [item])[-MAX_EXAMPLES:]


def similar(library, title, goal, lane=None, limit=2):
    want = keywords(title + " " + goal)
    scored = []
    for item in library:
        if lane and item["lane"] != lane:
            continue
        got = keywords(item["title"] + " " + item["goal"])
        if not want or not got:
            continue
        score = len(want & got) / len(want | got)
        if score > 0.05:
            scored.append((score, item))
    scored.sort(key=lambda t: -t[0])
    return [i for _, i in scored[:limit]]


def render_examples(items, max_chars=2400):
    """Фрагмент «образец удачного задания» для добавления в конец нового промпта."""
    if not items:
        return ""
    out = ["ОБРАЗЕЦ УДАЧНОГО ЗАДАНИЯ (принято с первого раза, ориентируйся на структуру отчёта и уровень детализации):"]
    size = 0
    for item in items:
        head = "%s: %s" % (item["id"], item["title"])
        body = item["goal"]
        if size + len(head) + len(body) > max_chars:
            break
        out.append("- %s. Цель была: %s" % (head, body))
        size += len(head) + len(body)
    return "\n".join(out) if len(out) > 1 else ""
