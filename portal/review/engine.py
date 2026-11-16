"""Авто-ревью: проверки сданной работы по списку изменённых файлов и тексту диффа. Чистые функции, без сети и без изменения чего-либо."""
from __future__ import annotations

import re

GREEN, YELLOW, RED = "green", "yellow", "red"
ORDER = {GREEN: 0, YELLOW: 1, RED: 2}

# Размер PR: выше мягкого порога жёлтый, выше жёсткого красный (строк изменено без учёта снимков и документов).
SOFT_LINES = 3000
HARD_LINES = 12000
BINARY_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".zip", ".mp4", ".pdf", ".woff", ".woff2")

SECRET_PATTERNS = (
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{40,}\b")),
    ("aws_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("api_key", re.compile(r"\bsk-[A-Za-z0-9_-]{24,}\b")),
    ("telegram_bot_token", re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("assigned_secret", re.compile(r"""(?i)\b(?:password|passwd|secret|token|api[_-]?key)\b\s*[:=]\s*["'][^"'\s$<{]{12,}["']""")),
)
# Тестовые значения, которые не считаются утечкой.
SAFE_VALUES = re.compile(r"(?i)(correct-horse|example|placeholder|dummy|changeme|test-?token|fake|not-a-real|xxxx|\*{4,})")


def glob_to_regex(glob):
    out, i = "", 0
    while i < len(glob):
        if glob.startswith("**", i):
            out += ".*"
            i += 2
        elif glob[i] == "*":
            out += "[^/]*"
            i += 1
        elif glob[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(glob[i])
            i += 1
    return re.compile("^" + out + "$")


def in_zone(path, zone_globs):
    return any(glob_to_regex(g).match(path) for g in zone_globs)


def check_zone(files, zone, shared_files=()):
    outside = sorted(f for f in files if not in_zone(f, zone))
    shared = sorted(f for f in files if f in set(shared_files))
    if shared:
        return {"id": "zone", "status": RED, "title": "Тронуты общие файлы директора", "details": shared[:20]}
    if outside:
        return {"id": "zone", "status": RED, "title": "Файлы вне зоны задачи", "details": outside[:20]}
    return {"id": "zone", "status": GREEN, "title": "Зона файлов соблюдена", "details": []}


def find_secrets(diff_text):
    """Ищет секреты только в добавленных строках диффа; тестовые значения пропускает. Значения не возвращает, только тип и номер строки."""
    found = []
    n = 0
    for line in (diff_text or "").splitlines():
        n += 1
        if not line.startswith("+") or line.startswith("+++"):
            continue
        body = line[1:]
        if SAFE_VALUES.search(body):
            continue
        for name, rx in SECRET_PATTERNS:
            if rx.search(body):
                found.append({"type": name, "line": n})
                break
    return found


def check_secrets(diff_text):
    found = find_secrets(diff_text)
    if found:
        return {"id": "secrets", "status": RED, "title": "В диффе похоже на секрет", "details": ["%s, строка диффа %d" % (f["type"], f["line"]) for f in found[:20]]}
    return {"id": "secrets", "status": GREEN, "title": "Секретов в диффе не найдено", "details": []}


def check_size(stats):
    """stats: список {path, added, deleted}. Снимки и бинарные файлы в размер не входят."""
    lines = sum(int(s.get("added", 0)) + int(s.get("deleted", 0)) for s in stats if not str(s.get("path", "")).lower().endswith(BINARY_EXT))
    if lines > HARD_LINES:
        return {"id": "size", "status": RED, "title": "PR слишком большой", "details": ["%d строк" % lines]}
    if lines > SOFT_LINES:
        return {"id": "size", "status": YELLOW, "title": "PR крупный, смотрите внимательнее", "details": ["%d строк" % lines]}
    return {"id": "size", "status": GREEN, "title": "Размер PR в норме", "details": ["%d строк" % lines]}


def check_ci(ci_state):
    if ci_state == "success":
        return {"id": "ci", "status": GREEN, "title": "CI зелёный", "details": []}
    if ci_state == "failure":
        return {"id": "ci", "status": RED, "title": "CI красный", "details": []}
    return {"id": "ci", "status": YELLOW, "title": "CI ещё идёт или нет данных", "details": []}


def check_checklist(items):
    items = items or []
    if not items:
        return {"id": "checklist", "status": YELLOW, "title": "Чек-лист не заполнен", "details": []}
    open_ = [i.get("text", "") for i in items if not i.get("done")]
    if open_:
        return {"id": "checklist", "status": YELLOW, "title": "Не закрыто пунктов: %d" % len(open_), "details": open_[:10]}
    return {"id": "checklist", "status": GREEN, "title": "Чек-лист закрыт", "details": []}


def check_report(report_text):
    if not (report_text or "").strip():
        return {"id": "report", "status": YELLOW, "title": "Нет отчёта исполнителя", "details": []}
    return {"id": "report", "status": GREEN, "title": "Отчёт исполнителя есть", "details": []}


def check_tests_added(files):
    """Если менялся код, а тестовые файлы не тронуты, это предупреждение (не ошибка)."""
    code = [f for f in files if f.endswith((".py", ".gd", ".js")) and "/tests/" not in f and "/ui_tests/" not in f and not f.startswith("tests/")]
    tests = [f for f in files if "/tests/" in f or "/ui_tests/" in f or f.startswith("tests/") or f.split("/")[-1].startswith("test_")]
    if code and not tests:
        return {"id": "tests_added", "status": YELLOW, "title": "Код изменён, тестов не добавлено", "details": code[:10]}
    return {"id": "tests_added", "status": GREEN, "title": "Тесты на месте", "details": []}


def verdict(checks):
    worst = max((ORDER[c["status"]] for c in checks), default=0)
    status = [k for k, v in ORDER.items() if v == worst][0]
    reds = [c["title"] for c in checks if c["status"] == RED]
    yellows = [c["title"] for c in checks if c["status"] == YELLOW]
    return {"status": status, "red": reds, "yellow": yellows, "checks": checks}


def review(plan_pkg_zone, shared_files, files, diff_text, stats, ci_state, checklist, report):
    """Полный светофор. Красный: нельзя принимать без разбора. Жёлтый: можно, но посмотрите. Зелёный: безопасно принять."""
    checks = [
        check_zone(files, plan_pkg_zone, shared_files),
        check_secrets(diff_text),
        check_ci(ci_state),
        check_size(stats),
        check_tests_added(files),
        check_checklist(checklist),
        check_report(report),
    ]
    return verdict(checks)


def auto_merge_allowed(v, require_checklist=True):
    """Авто-слияние допустимо только при полностью зелёном светофоре (жёлтые пункты тоже блокируют)."""
    if v["status"] != GREEN:
        return False
    if require_checklist and any(c["id"] == "checklist" and c["status"] != GREEN for c in v["checks"]):
        return False
    return True
