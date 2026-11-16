"""Поиск по памяти проекта: документы, решения, отчёты, возвраты, знания, идеи. Лёгкий BM25 без внешних библиотек."""
from __future__ import annotations

import math
import re

WORD = re.compile(r"[a-zа-яё0-9_]{3,}", re.I)
STEM = 6


def tokens(text):
    return [w.lower().replace("ё", "е")[:STEM] for w in WORD.findall(text or "")]


def build(docs):
    """docs: список {id, kind, title, text, url}. Индекс хранит частоты слов и длины документов."""
    index = {"docs": [], "df": {}, "avg": 0.0}
    total = 0
    for d in docs:
        toks = tokens(d.get("title", "") + " " + d.get("title", "") + " " + d.get("text", ""))
        tf = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        for t in tf:
            index["df"][t] = index["df"].get(t, 0) + 1
        index["docs"].append({"doc": d, "tf": tf, "len": len(toks)})
        total += len(toks)
    index["avg"] = total / len(docs) if docs else 0.0
    return index


def snippet(text, query_tokens, width=160):
    low = (text or "")
    for m in WORD.finditer(low):
        if m.group(0).lower().replace("ё", "е")[:STEM] in query_tokens:
            start = max(0, m.start() - width // 3)
            return ("…" if start else "") + low[start:start + width].replace("\n", " ").strip()
    return (low[:width]).replace("\n", " ").strip()


def search(index, query, limit=8, kinds=None, k1=1.4, b=0.75):
    q = [t for t in dict.fromkeys(tokens(query))]
    if not q or not index["docs"]:
        return []
    n = len(index["docs"])
    scored = []
    for item in index["docs"]:
        d = item["doc"]
        if kinds and d.get("kind") not in kinds:
            continue
        score = 0.0
        for t in q:
            f = item["tf"].get(t, 0)
            if not f:
                continue
            idf = math.log(1 + (n - index["df"][t] + 0.5) / (index["df"][t] + 0.5))
            score += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * item["len"] / (index["avg"] or 1)))
        if score > 0:
            scored.append((score, d))
    scored.sort(key=lambda t: -t[0])
    qs = set(q)
    return [{"id": d["id"], "kind": d.get("kind", ""), "title": d.get("title", ""), "url": d.get("url", ""),
             "snippet": snippet(d.get("text", ""), qs), "score": round(s, 3)} for s, d in scored[:limit]]
