"""Карта репозитория: что где лежит. По списку файлов и их первой строке собирается краткий навигатор для ИИ."""
from __future__ import annotations

import re
from pathlib import Path

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "shots", ".pytest_cache"}
SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".zip", ".mp4", ".sqlite", ".pyc", ".woff", ".woff2", ".pdf"}
MAX_FILE_BYTES = 200_000


def describe(path, text):
    """Одна строка назначения файла: докстринг модуля, первый заголовок документа или первый комментарий."""
    name = path.rsplit("/", 1)[-1]
    for raw in text.splitlines()[:12]:
        line = raw.strip()
        if not line:
            continue
        if name.endswith(".md"):
            if line.startswith("#"):
                return line.lstrip("# ").strip()[:120]
            continue
        m = re.match(r'^(?:"""|\'\'\')(.+?)(?:"""|\'\'\')?$', line)
        if m:
            return m.group(1).strip()[:120]
        if line.startswith(("#!", "<!")):
            continue
        if line.startswith("# ") or line.startswith("//"):
            text_ = line.lstrip("#/ ").strip()
            if text_:
                return text_[:120]
        break
    return ""


def scan(root, max_files=3000):
    """Рекурсивно обходит каталог и возвращает [{path, size, about}]. Бинарные и служебные файлы пропускаются."""
    root = Path(root)
    items = []
    for p in sorted(root.rglob("*")):
        if len(items) >= max_files:
            break
        if not p.is_file() or SKIP_DIRS & set(p.relative_to(root).parts) or p.suffix.lower() in SKIP_EXT:
            continue
        rel = p.relative_to(root).as_posix()
        size = p.stat().st_size
        about = ""
        if size <= MAX_FILE_BYTES and p.suffix in (".py", ".md", ".sh", ".js", ".html", ".gd", ".json", ".service", ".conf"):
            try:
                about = describe(rel, p.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                about = ""
        items.append({"path": rel, "size": size, "about": about})
    return items


def render(items, max_chars=4000, depth=2):
    """Компактный текст: группы по папкам до глубины depth, у каждой число файлов и самые информативные файлы."""
    groups = {}
    for it in items:
        parts = it["path"].split("/")
        key = "/".join(parts[:depth]) if len(parts) > depth else (parts[0] if len(parts) > 1 else ".")
        groups.setdefault(key, []).append(it)
    lines, size = [], 0
    for key in sorted(groups, key=lambda k: (-len(groups[k]), k)):
        files = groups[key]
        informative = [f for f in files if f["about"]][:4]
        head = "%s/ (%d файлов)" % (key, len(files)) if key != "." else "корень (%d файлов)" % len(files)
        block = [head] + ["  - %s: %s" % (f["path"], f["about"]) for f in informative]
        text = "\n".join(block)
        if size + len(text) > max_chars:
            lines.append("… ещё %d папок" % (len(groups) - len([l for l in lines if not l.startswith("  ")])))
            break
        lines.append(text)
        size += len(text) + 1
    return "\n".join(lines)
