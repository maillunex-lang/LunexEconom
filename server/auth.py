"""Prototype persistent accounts for LunexEconom. SQLite until PostgreSQL migration."""
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import psycopg
import postgres_db
import threading
import time
import smtplib
import ssl
from email.message import EmailMessage

DB_PATH = os.environ.get("LUNEX_AUTH_DB", "/home/gamedev/projects/LunexEconom-runtime/accounts.sqlite3")
USE_POSTGRES = os.environ.get("LUNEX_DB_ENGINE") == "postgres"
_lock = threading.RLock()
_attempts = {}
ITERATIONS = 310_000

def _db():
    if USE_POSTGRES:
        return postgres_db.connect()
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.execute("PRAGMA busy_timeout=10000")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, email TEXT UNIQUE NOT NULL, salt BLOB NOT NULL, password_hash BLOB NOT NULL, created_at INTEGER NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires_at INTEGER NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS auth_attempts (attempt_key TEXT PRIMARY KEY, window_start BIGINT NOT NULL, attempts INTEGER NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS auth_tokens (token_hash TEXT PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id), purpose TEXT NOT NULL, expires_at BIGINT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS email_verified (user_id BIGINT PRIMARY KEY REFERENCES users(id), verified_at BIGINT NOT NULL)")
    db.commit()
    return db

def _hash_password(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)

def _rate_limit(key):
    """Persistent fixed-window throttle shared by workers and surviving restarts."""
    now = int(time.time())
    window = now // 600
    with _lock, _db() as db:
        ph = "%s" if USE_POSTGRES else "?"
        if USE_POSTGRES:
            # Serialize competing workers for this key using an atomic UPSERT.
            row = db.execute(
                "INSERT INTO auth_attempts(attempt_key,window_start,attempts) "
                "VALUES(%s,%s,1) ON CONFLICT(attempt_key) DO UPDATE SET "
                "window_start=EXCLUDED.window_start, "
                "attempts=CASE WHEN auth_attempts.window_start=EXCLUDED.window_start "
                "THEN auth_attempts.attempts+1 ELSE 1 END RETURNING attempts",
                (key, window),
            ).fetchone()
            count = row[0]
        else:
            db.execute(
                "INSERT INTO auth_attempts(attempt_key,window_start,attempts) "
                "VALUES(?,?,1) ON CONFLICT(attempt_key) DO UPDATE SET "
                "window_start=excluded.window_start, "
                "attempts=CASE WHEN auth_attempts.window_start=excluded.window_start "
                "THEN auth_attempts.attempts+1 ELSE 1 END",
                (key, window),
            )
            count = db.execute("SELECT attempts FROM auth_attempts WHERE attempt_key=?", (key,)).fetchone()[0]
        db.commit()
        return count <= 12


def _session(db, user_id, username):
    token = secrets.token_urlsafe(32)
    expires = int(time.time()) + 7*86400
    db.execute("INSERT INTO sessions(token_hash,user_id,expires_at) VALUES("+("%s,%s,%s" if USE_POSTGRES else "?,?,?")+")", (hashlib.sha256(token.encode()).hexdigest(),user_id,expires))
    db.commit()
    return 200, {"token": token, "expires_at": expires, "username": username}

def register(payload, client):
    if not _rate_limit("register:"+client): return 429, {"error":"rate_limited"}
    username = str(payload.get("username","")).strip()
    email = str(payload.get("email","")).strip().lower()
    password = payload.get("password","")
    if not re.fullmatch(r"[A-Za-zА-Яа-яЁё0-9_]{3,24}", username): return 400, {"error":"invalid_username"}
    if len(email)>254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",email): return 400, {"error":"invalid_email"}
    if not isinstance(password,str) or len(password)<4 or len(password)>128: return 400, {"error":"invalid_password"}
    salt = secrets.token_bytes(16)
    with _lock, _db() as db:
        try:
            cursor=db.execute("INSERT INTO users(username,email,salt,password_hash,created_at) VALUES("+("%s,%s,%s,%s,%s" if USE_POSTGRES else "?,?,?,?,?")+")"+(" RETURNING id" if USE_POSTGRES else ""), (username,email,salt,_hash_password(password,salt),int(time.time())))
            db.commit()
        except (sqlite3.IntegrityError, psycopg.errors.UniqueViolation):
            return 409, {"error":"account_exists"}
        return _session(db,cursor.fetchone()[0] if USE_POSTGRES else cursor.lastrowid,username)

def login(payload, client):
    if not _rate_limit("login:"+client): return 429, {"error":"rate_limited"}
    identifier = str(payload.get("identifier","")).strip()
    password = payload.get("password","")
    if not isinstance(password,str) or len(password)>128: return 400, {"error":"invalid_credentials"}
    with _lock, _db() as db:
        row=db.execute("SELECT id,username,salt,password_hash FROM users WHERE username="+("%s" if USE_POSTGRES else "?")+" OR email="+("%s" if USE_POSTGRES else "?"),(identifier,identifier.lower())).fetchone()
        if row is None:
            _hash_password(password,secrets.token_bytes(16))
            return 401, {"error":"invalid_credentials"}
        if not hmac.compare_digest(_hash_password(password,row[2]),row[3]):
            return 401, {"error":"invalid_credentials"}
        return _session(db,row[0],row[1])

def profile(token):
    if not token: return 401, {"error":"unauthorized"}
    digest=hashlib.sha256(token.encode()).hexdigest()
    with _lock, _db() as db:
        row=db.execute("SELECT u.username,s.expires_at FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash="+("%s" if USE_POSTGRES else "?"),(digest,)).fetchone()
        if row is None or row[1] < time.time(): return 401, {"error":"unauthorized"}
        return 200, {"username":row[0]}

def logout(token):
    if token:
        with _lock, _db() as db:
            db.execute("DELETE FROM sessions WHERE token_hash="+("%s" if USE_POSTGRES else "?"),(hashlib.sha256(token.encode()).hexdigest(),))
            db.commit()
    return 200, {"ok":True}

# Transactional one-time account tokens. Only SHA-256 hashes are persisted.
def _digest(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _send_account_email(address, subject, message):
    """Send using authenticated SMTP over TLS; fail closed if unavailable.

    Mail.ru uses implicit TLS on port 465. The application password is read
    from a root-managed file, never committed to the repository.
    """
    host = os.environ.get("LUNEX_SMTP_HOST")
    sender = os.environ.get("LUNEX_SMTP_FROM")
    user = os.environ.get("LUNEX_SMTP_USER")
    password_file = os.environ.get("LUNEX_SMTP_PASSWORD_FILE")
    if not all((host, sender, user, password_file)):
        return False
    try:
        with open(password_file, encoding="utf-8") as handle:
            password = handle.read().strip()
        if not password:
            return False
        port = int(os.environ.get("LUNEX_SMTP_PORT", "465"))
        email = EmailMessage()
        email["From"], email["To"], email["Subject"] = sender, address, subject
        email.set_content(message)
        context = ssl.create_default_context()
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=10, context=context) as smtp:
                smtp.login(user, password)
                smtp.send_message(email)
        else:
            with smtplib.SMTP(host, port, timeout=10) as smtp:
                smtp.ehlo()
                smtp.starttls(context=context)
                smtp.ehlo()
                smtp.login(user, password)
                smtp.send_message(email)
        return True
    except (OSError, ValueError, smtplib.SMTPException, ssl.SSLError):
        return False



def _issue_email_token(identifier, purpose, client):
    if not _rate_limit(purpose + ":" + client):
        return 429, {"error": "rate_limited"}
    # No account enumeration; do not reveal whether an address exists.
    generic = (200, {"ok": True, "message": "If the account exists, an email will be sent"})
    if not isinstance(identifier, str) or len(identifier) > 254:
        return generic
    with _lock, _db() as db:
        ph = "%s" if USE_POSTGRES else "?"
        row = db.execute("SELECT id,email FROM users WHERE lower(email)=" + ph, (identifier.strip().lower(),)).fetchone()
        if not row:
            return generic
        if purpose == "verify" and db.execute("SELECT 1 FROM email_verified WHERE user_id=" + ph, (row[0],)).fetchone():
            return generic
        token = secrets.token_urlsafe(32)
        expires = int(time.time()) + 1800
        # Mail first, then persist. A failed SMTP send never exposes a usable token.
        message = "Your LunexEconom " + purpose + " code (valid 30 minutes): " + token
        if not _send_account_email(row[1], "LunexEconom account " + purpose, message):
            return 503, {"error": "email_unavailable"}
        db.execute("DELETE FROM auth_tokens WHERE user_id=" + ph + " AND purpose=" + ph, (row[0], purpose))
        db.execute("INSERT INTO auth_tokens(token_hash,user_id,purpose,expires_at) VALUES(" +
                   ("%s,%s,%s,%s" if USE_POSTGRES else "?,?,?,?") + ")",
                   (_digest(token), row[0], purpose, expires))
        db.commit()
    return generic


def request_verification(payload, client):
    return _issue_email_token(payload.get("email"), "verify", client)


def request_password_reset(payload, client):
    return _issue_email_token(payload.get("email"), "reset", client)


def _consume_token(db, token, purpose):
    if not isinstance(token, str) or len(token) > 256:
        return None
    ph = "%s" if USE_POSTGRES else "?"
    row = db.execute("SELECT user_id,expires_at FROM auth_tokens WHERE token_hash=" + ph +
                     " AND purpose=" + ph, (_digest(token), purpose)).fetchone()
    if row is None or row[1] < int(time.time()):
        return None
    db.execute("DELETE FROM auth_tokens WHERE token_hash=" + ph, (_digest(token),))
    return row[0]


def confirm_email(payload, client):
    if not _rate_limit("confirm:" + client):
        return 429, {"error": "rate_limited"}
    with _lock, _db() as db:
        user_id = _consume_token(db, payload.get("token"), "verify")
        if user_id is None:
            return 400, {"error": "invalid_or_expired_token"}
        db.execute("INSERT INTO email_verified(user_id,verified_at) VALUES(" +
                   ("%s,%s" if USE_POSTGRES else "?,?") +
                   ") ON CONFLICT(user_id) DO UPDATE SET verified_at=excluded.verified_at",
                   (user_id, int(time.time())))
        db.commit()
    return 200, {"ok": True}


def reset_password(payload, client):
    if not _rate_limit("reset-confirm:" + client):
        return 429, {"error": "rate_limited"}
    password = payload.get("password")
    if not isinstance(password, str) or not 4 <= len(password) <= 128:
        return 400, {"error": "invalid_password"}
    with _lock, _db() as db:
        user_id = _consume_token(db, payload.get("token"), "reset")
        if user_id is None:
            return 400, {"error": "invalid_or_expired_token"}
        ph = "%s" if USE_POSTGRES else "?"
        salt = secrets.token_bytes(16)
        db.execute("UPDATE users SET salt=" + ph + ",password_hash=" + ph + " WHERE id=" + ph,
                   (salt, _hash_password(password, salt), user_id))
        db.execute("DELETE FROM sessions WHERE user_id=" + ph, (user_id,))
        db.execute("DELETE FROM auth_tokens WHERE user_id=" + ph, (user_id,))
        db.commit()
    return 200, {"ok": True}


def rotate_token(token):
    if not token:
        return 401, {"error": "unauthorized"}
    with _lock, _db() as db:
        ph = "%s" if USE_POSTGRES else "?"
        row = db.execute("SELECT s.user_id,u.username,s.expires_at FROM sessions s "
                         "JOIN users u ON u.id=s.user_id WHERE s.token_hash=" + ph,
                         (_digest(token),)).fetchone()
        if not row or row[2] < int(time.time()):
            return 401, {"error": "unauthorized"}
        deleted = db.execute("DELETE FROM sessions WHERE token_hash=" + ph, (_digest(token),))
        if deleted.rowcount != 1:
            return 401, {"error": "unauthorized"}
        return _session(db, row[0], row[1])


def logout_all(token):
    if not token:
        return 401, {"error": "unauthorized"}
    with _lock, _db() as db:
        ph = "%s" if USE_POSTGRES else "?"
        row = db.execute("SELECT user_id,expires_at FROM sessions WHERE token_hash=" + ph,
                         (_digest(token),)).fetchone()
        if not row or row[1] < int(time.time()):
            return 401, {"error": "unauthorized"}
        db.execute("DELETE FROM sessions WHERE user_id=" + ph, (row[0],))
        db.commit()
    return 200, {"ok": True}
