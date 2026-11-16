"""Хранилище знаний проекта: ловушки и решения, которые автоматически попадают в правила проекта и в каждый новый промпт."""
from __future__ import annotations

import re
import time

from .engine import find_secrets

MAX_TEXT = 400
MAX_LESSONS = 60


def _norm(text):
    return re.sub(r"\s+", " ", text.strip().lower())


def add(lessons, text, source="manual", tags=None, now=None):
    """Возвращает (новый список, добавленная запись или None если дубликат). Секреты не принимаются."""
    text = re.sub(r"\s+", " ", (text or "").strip())
    if len(text) < 8:
        raise ValueError("too_short")
    if len(text) > MAX_TEXT:
        raise ValueError("too_long")
    if find_secrets("+" + text):
        raise ValueError("looks_like_secret")
    for item in lessons:
        if _norm(item["text"]) == _norm(text):
            return lessons, None
    entry = {"id": "L%d" % (max([int(x["id"][1:]) for x in lessons] or [0]) + 1), "text": text, "source": source,
             "tags": sorted(set(tags or []))[:5], "created": now if now is not None else time.time(), "uses": 0}
    out = (lessons + [entry])[-MAX_LESSONS:]
    return out, entry


def remove(lessons, lesson_id):
    return [x for x in lessons if x["id"] != lesson_id]


def render(lessons, max_chars=2500, tags=None):
    """Блок для вставки в промпты. Сначала недавние и подходящие по тегам. Пустой список даёт пустую строку."""
    if not lessons:
        return ""
    wanted = set(tags or [])
    ranked = sorted(lessons, key=lambda x: (0 if wanted & set(x.get("tags", [])) else 1, -x["created"]))
    lines, size = [], 0
    for item in ranked:
        row = "- " + item["text"]
        if size + len(row) > max_chars:
            break
        lines.append(row)
        size += len(row) + 1
    return "ЛОВУШКИ И РЕШЕНИЯ ПРОЕКТА (учитывай, это уже случалось):\n" + "\n".join(lines) if lines else ""


def suggest_from_returns(returns, threshold=2):
    """returns: список reason_id из возвратов. Если одна и та же причина повторяется threshold раз, предлагаем записать правило."""
    counts = {}
    for r in returns:
        counts[r] = counts.get(r, 0) + 1
    from .returns import TEMPLATES
    return [{"reason": r, "text": "Частая причина возврата «%s»: %s" % (TEMPLATES[r][0], TEMPLATES[r][1])[:MAX_TEXT], "count": c}
            for r, c in sorted(counts.items(), key=lambda kv: -kv[1]) if c >= threshold and r in TEMPLATES]
