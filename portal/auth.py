"""Один владелец: пароль scrypt, сессии с CSRF, лимит попыток входа. Пароль задаётся только на сервере (portal.manage), не в чате."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time

SESSION_TTL = 12 * 3600
ATTEMPT_WINDOW = 15 * 60
ATTEMPT_LIMIT = 8
MIN_PASSWORD = 14


def hash_password(password):
    salt = os.urandom(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return "scrypt$" + salt.hex() + "$" + h.hex()


def verify_password(password, stored):
    try:
        kind, salt, h = stored.split("$")
        calc = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1, dklen=32)
        return kind == "scrypt" and hmac.compare_digest(calc.hex(), h)
    except Exception:
        return False


def th(token):
    return hashlib.sha256(token.encode()).hexdigest()


def too_many(conn, ip, now=None):
    now = now or time.time()
    n = conn.execute("SELECT count(*) FROM attempts WHERE ip=? AND ts>?", (ip, now - ATTEMPT_WINDOW)).fetchone()[0]
    return n >= ATTEMPT_LIMIT


def note_attempt(conn, ip, now=None):
    conn.execute("INSERT INTO attempts(ip,ts) VALUES(?,?)", (ip, now or time.time()))
    conn.execute("DELETE FROM attempts WHERE ts<?", ((now or time.time()) - ATTEMPT_WINDOW,))


def login(conn, username, password, ip, now=None):
    """Возвращает (token, csrf) или None. Ошибка и неверный пароль неразличимы; лимит по IP."""
    now = now or time.time()
    if too_many(conn, ip, now):
        return "rate"
    row = conn.execute("SELECT id,pw_hash FROM users WHERE username=?", (username,)).fetchone()
    ok = bool(row) and verify_password(password, row["pw_hash"])
    if not row:
        verify_password(password, "scrypt$" + "00" * 16 + "$" + "00" * 32)  # выравниваем время
    if not ok:
        note_attempt(conn, ip, now)
        return None
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(16)
    conn.execute("INSERT INTO sessions(token_hash,user_id,csrf,expires) VALUES(?,?,?,?)", (th(token), row["id"], csrf, now + SESSION_TTL))
    return token, csrf


def session(conn, token, now=None):
    if not token:
        return None
    now = now or time.time()
    row = conn.execute("SELECT s.user_id,s.csrf,u.username FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>?", (th(token), now)).fetchone()
    return dict(row) if row else None


def logout(conn, token):
    conn.execute("DELETE FROM sessions WHERE token_hash=?", (th(token),))


def set_password(conn, username, password):
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"пароль не короче {MIN_PASSWORD} символов")
    conn.execute("INSERT INTO users(username,pw_hash,created) VALUES(?,?,?) ON CONFLICT(username) DO UPDATE SET pw_hash=excluded.pw_hash",
                 (username, hash_password(password), time.time()))
    conn.execute("DELETE FROM sessions")
