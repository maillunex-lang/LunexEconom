"""Фильтр секретов для памяти: всё, что похоже на токен или пароль, заменяется до сохранения и до показа."""
from __future__ import annotations

from portal.review.engine import SECRET_PATTERNS, SAFE_VALUES

MASK = "[скрыто]"


def redact(text):
    """Строка, в которой найденные секреты заменены на [скрыто]. Тестовые значения (SAFE_VALUES) не трогаются."""
    out = []
    for line in (text or "").splitlines():
        if not SAFE_VALUES.search(line):
            for _, rx in SECRET_PATTERNS:
                line = rx.sub(lambda m: MASK, line)
        out.append(line)
    return "\n".join(out)


def has_secret(text):
    return redact(text) != (text or "").replace("\r", "")
