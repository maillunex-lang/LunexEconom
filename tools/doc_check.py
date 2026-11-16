"""Проверка свежести документов: находит в текстах упоминания, которых нет в коде.
Проверяет: пути файлов, маршруты API (/api/...), переменные окружения PORTAL_*.
Запуск: python tools/doc_check.py [--strict] [файлы или папки ...]  (по умолчанию docs/portal, portal/DEPLOY.md, README.md).
Код выхода 1 при находках только с --strict (для CI)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ["docs/portal", "portal/DEPLOY.md", "README.md"]
CODE_DIRS = ["portal", "tools", "server", "client"]
IGNORE_PATH = re.compile(r"[<>*{}$|]|^https?:|^~|^/(?:var|etc|opt|usr|tmp|home)/|\.\.\.|^\.?\.?/?$")
BACKTICK = re.compile(r"`([^`\n]{2,160})`")
ROUTE = re.compile(r"(/api/[A-Za-z0-9_\-/{}.]+|/hook/[A-Za-z0-9_\-/]+|/share\b|/health\b)")
ENV = re.compile(r"\bPORTAL_[A-Z][A-Z0-9_]+\b")
PATH_LIKE = re.compile(r"^[A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-]+)+/?$")
EXT = re.compile(r"\.[A-Za-z0-9]{1,6}$")
DOMAIN = re.compile(r"^[a-z0-9\-]+\.(?:ru|com|org|net|io)\b")
# Строки про будущие версии и про состав скелета нового проекта проверять нечем: они описывают то, чего нет в этом репозитории.
SKIP_LINE = re.compile(r"\[v[2-9]\]|скелет|планируется", re.I)
# Конкретные пути, которые документы упоминают как создаваемые на сервере или при работе.
KNOWN_RUNTIME = ("portal/qa/server/", "portal/qa/ui/", "docs/gdd/", "portal/ui_tests/shots/")


def source_blob():
    parts = []
    for d in CODE_DIRS:
        base = ROOT / d
        if base.is_dir():
            for p in base.rglob("*"):
                if p.suffix in (".py", ".sh", ".service", ".conf", ".html", ".js", ".md", ".path") and "tests" not in p.parts and p.is_file():
                    try:
                        parts.append(p.read_text(encoding="utf-8", errors="ignore"))
                    except OSError:
                        pass
    return "\n".join(parts)


def route_known(route, blob):
    route = route.rstrip("/.")
    segs = [s for s in route.split("/") if s and not (s.startswith("{") or s.startswith("<"))]
    if not segs:
        return True
    return all(("/" + s in blob) or ('"%s"' % s in blob) or ("'%s'" % s in blob) for s in segs[-2:])


def check_file(path, blob):
    findings = []
    text = path.read_text(encoding="utf-8", errors="ignore")
    rel = str(path.relative_to(ROOT))
    for n, line in enumerate(text.splitlines(), 1):
        if SKIP_LINE.search(line):
            continue
        for m in BACKTICK.finditer(line):
            token = m.group(1).strip()
            if IGNORE_PATH.search(token):
                continue
            if PATH_LIKE.match(token) and (EXT.search(token) or token.endswith("/")):
                t = token.split("#")[0]
                if DOMAIN.match(t):
                    continue
                if not (ROOT / t).exists() and not (path.parent / t).exists() and not any(t.startswith(k) for k in KNOWN_RUNTIME):
                    findings.append((rel, n, "path", token))
        for r in ROUTE.findall(line):
            if not route_known(r, blob):
                findings.append((rel, n, "route", r))
        for e in ENV.findall(line):
            if e not in blob:
                findings.append((rel, n, "env", e))
    return findings


def collect(args):
    files = []
    for a in args or DEFAULT:
        p = (ROOT / a) if not Path(a).is_absolute() else Path(a)
        if p.is_dir():
            files += sorted(p.rglob("*.md"))
        elif p.is_file():
            files.append(p)
    return files


def main(argv):
    strict = "--strict" in argv
    args = [a for a in argv[1:] if a != "--strict"]
    blob = source_blob()
    findings = []
    for f in collect(args):
        findings += check_file(f, blob)
    seen = set()
    for rel, n, kind, tok in findings:
        key = (rel, kind, tok)
        if key in seen:
            continue
        seen.add(key)
        print(f"{rel}:{n}: {kind}: {tok}")
    print(f"Найдено расхождений: {len(seen)}")
    return 1 if (strict and seen) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
