"""Предупреждения о конфликтах: пересечение зон и реальных файлов у задач, которые выданы одновременно."""
from __future__ import annotations

from .engine import glob_to_regex


def _prefix(glob):
    out = []
    for part in glob.split("/"):
        if any(c in part for c in "*?"):
            break
        out.append(part)
    return "/".join(out)


def zones_overlap(a, b):
    for x in a:
        for y in b:
            px, py = _prefix(x), _prefix(y)
            if px == py or px.startswith(py.rstrip("/") + "/") or py.startswith(px.rstrip("/") + "/") or px == "" or py == "":
                if not px or not py:
                    return True
                # одинаковый путь или один внутри другого, а glob-ы с шаблонами пересекаются
                if glob_to_regex(x).match(py) or glob_to_regex(y).match(px) or px == py or px.startswith(py + "/") or py.startswith(px + "/"):
                    return True
    return False


def shared_files(files_a, files_b):
    return sorted(set(files_a) & set(files_b))


def warnings(tasks):
    """tasks: список {id, zone[], files[]} выданных или готовых к выдаче. Возвращает предупреждения по парам."""
    out = []
    for i, a in enumerate(tasks):
        for b in tasks[i + 1:]:
            same = shared_files(a.get("files", []), b.get("files", []))
            if same:
                out.append({"a": a["id"], "b": b["id"], "level": "red", "files": same[:20],
                            "text": "%s и %s уже правят одни и те же файлы: %s. Сначала примите одну, потом выдавайте другую." % (a["id"], b["id"], ", ".join(same[:3]))})
            elif zones_overlap(a.get("zone", []), b.get("zone", [])):
                out.append({"a": a["id"], "b": b["id"], "level": "yellow", "files": [],
                            "text": "Зоны %s и %s пересекаются, возможны конфликты слияния. Лучше не выдавать вместе." % (a["id"], b["id"])})
    return out
