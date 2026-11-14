"""Prototype persistent accounts for LunexEconom. SQLite until PostgreSQL migration."""
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import threading
import time

DB_PATH = os.environ.get("LUNEX_AUTH_DB", "/home/gamedev/projects/LunexEconom-runtime/accounts.sqlite3")
_lock = threading.RLock()
_attempts = {}
ITERATIONS = 310_000

def _db():
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.execute("PRAGMA busy_timeout=10000")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, email TEXT UNIQUE NOT NULL, salt BLOB NOT NULL, password_hash BLOB NOT NULL, created_at INTEGER NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires_at INTEGER NOT NULL)")
    db.commit()
    return db

def _hash_password(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)

def _rate_limit(key):
    now = time.monotonic()
    with _lock:
        entries = [t for t in _attempts.get(key, []) if now-t < 600]
        if len(entries) >= 12:
            _attempts[key] = entries
            return False
        entries.append(now)
        _attempts[key] = entries
        if len(_attempts) > 10000:
            _attempts.clear()
        return True

def _session(db, user_id, username):
    token = secrets.token_urlsafe(32)
    expires = int(time.time()) + 7*86400
    db.execute("INSERT INTO sessions(token_hash,user_id,expires_at) VALUES(?,?,?)", (hashlib.sha256(token.encode()).hexdigest(),user_id,expires))
    db.commit()
    return 200, {"token": token, "expires_at": expires, "username": username}

def register(payload, client):
    if not _rate_limit("register:"+client): return 429, {"error":"rate_limited"}
    username = str(payload.get("username","")).strip()
    email = str(payload.get("email","")).strip().lower()
    password = payload.get("password","")
    if not re.fullmatch(r"[A-Za-zА-Яа-яЁё0-9_]{3,24}", username): return 400, {"error":"invalid_username"}
    if len(email)>254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",email): return 400, {"error":"invalid_email"}
    if not isinstance(password,str) or len(password)<10 or len(password)>128: return 400, {"error":"invalid_password"}
    salt = secrets.token_bytes(16)
    with _lock, _db() as db:
        try:
            cursor=db.execute("INSERT INTO users(username,email,salt,password_hash,created_at) VALUES(?,?,?,?,?)",(username,email,salt,_hash_password(password,salt),int(time.time())))
            db.commit()
        except sqlite3.IntegrityError:
            return 409, {"error":"account_exists"}
        return _session(db,cursor.lastrowid,username)

def login(payload, client):
    if not _rate_limit("login:"+client): return 429, {"error":"rate_limited"}
    identifier = str(payload.get("identifier","")).strip()
    password = payload.get("password","")
    if not isinstance(password,str) or len(password)>128: return 400, {"error":"invalid_credentials"}
    with _lock, _db() as db:
        row=db.execute("SELECT id,username,salt,password_hash FROM users WHERE username=? OR email=?",(identifier,identifier.lower())).fetchone()
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
        row=db.execute("SELECT u.username,s.expires_at FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=?",(digest,)).fetchone()
        if row is None or row[1] < time.time(): return 401, {"error":"unauthorized"}
        return 200, {"username":row[0]}

def logout(token):
    if token:
        with _lock, _db() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?",(hashlib.sha256(token.encode()).hexdigest(),))
            db.commit()
    return 200, {"ok":True}
