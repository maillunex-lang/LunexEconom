"""Журнал решений владельца: разбор из DECISIONS.md и хранение новых записей."""
from __future__ import annotations

import re
import time

from .redact import redact

DATE = re.compile(r"(20\d\d-\d\d-\d\d)")
MAX_TEXT = 700


def parse_markdown(text):
    """Берёт маркированные пункты под заголовками с «Принято» или «Решени»; пункты таблиц вопросов не включаются."""
    out, active = [], False
    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if line.startswith("#"):
            low = line.lower()
            active = "принято" in low or "решени" in low and "вопрос" not in low
            continue
        if active and line.startswith("- "):
            body = line[2:].strip()
            m = DATE.search(body)
            title = re.split(r"\.(?:\s|$)", re.sub(r"\*\*|`", "", body))[0][:90]
            out.append({"id": "D%d" % (len(out) + 1), "date": m.group(1) if m else "", "title": title, "text": redact(re.sub(r"\*\*", "", body))[:MAX_TEXT], "source": "DECISIONS.md"})
    return out


def add(decisions, title, text, source="owner", date=None, now=None):
    title = re.sub(r"\s+", " ", (title or "").strip())
    text = redact((text or "").strip())
    if len(title) < 4:
        raise ValueError("title_too_short")
    if len(text) > MAX_TEXT:
        raise ValueError("text_too_long")
    for d in decisions:
        if d["title"].lower() == title.lower() and d["text"] == text:
            return decisions, None
    nums = [int(d["id"][1:]) for d in decisions if re.fullmatch(r"D\d+", d["id"])]
    entry = {"id": "D%d" % (max(nums or [0]) + 1), "date": date or time.strftime("%Y-%m-%d", time.gmtime(now if now is not None else time.time())),
             "title": title[:90], "text": text, "source": source}
    return decisions + [entry], entry
