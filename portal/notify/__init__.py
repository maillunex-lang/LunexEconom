"""Notification delivery, binding and anti-noise. Standard library only."""
from __future__ import annotations
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import time
import urllib.parse
import urllib.request

CHANNELS = ("max", "telegram")
EVENTS = ("task.submitted", "ci.failed", "review.overdue", "plan.sync_failed", "login.new_device", "backup.missing")
MAX_URL = "https://platform-api2.max.ru"
TELEGRAM_URL = "https://api.telegram.org"
DELAY = 300
QUIET = 3600

def token_from_file(channel, paths):
    path = paths.get(channel)
    if not path:
        raise ValueError("token_file_missing")
    p = Path(path)
    if not p.is_file() or p.stat().st_mode & 0o077:
        raise ValueError("token_file_permissions")
    value = p.read_text(encoding="utf-8").strip()
    if not value or len(value) > 512 or any(c.isspace() for c in value):
        raise ValueError("token_invalid")
    return value

def http_json(url, headers, payload=None, timeout=10):
    data = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status < 200 or response.status >= 300:
            raise ValueError("delivery_failed")
        raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError("response_too_large")
        return json.loads(raw)

def send(channel, token, chat_id, message, client=http_json):
    if channel not in CHANNELS or not isinstance(chat_id, str) or not chat_id.isdecimal() or len(chat_id) > 30:
        raise ValueError("invalid_channel_or_chat")
    if not isinstance(message, str) or not 1 <= len(message) <= 2000:
        raise ValueError("invalid_message")
    if channel == "max":
        url = MAX_URL + "/messages?" + urllib.parse.urlencode({"chat_id": chat_id})
        response = client(url, {"Authorization": token, "Content-Type": "application/json"}, {"text": message}, timeout=10)
    else:
        url = TELEGRAM_URL + "/bot" + token + "/sendMessage"
        response = client(url, {"Content-Type": "application/json"}, {"chat_id": chat_id, "text": message}, timeout=10)
        if response.get("ok") is not True:
            raise ValueError("delivery_failed")
    if not isinstance(response, dict):
        raise ValueError("delivery_failed")
    return True

def create_code(conn, channel, now=None):
    if channel not in CHANNELS:
        raise ValueError("invalid_channel")
    now = time.time() if now is None else now
    code = f"{secrets.randbelow(100000000):08d}"
    digest = hashlib.sha256(code.encode()).hexdigest()
    conn.execute("INSERT INTO notify_channels(channel,enabled,chat_id,code_hash,expires) VALUES(?,0,NULL,?,?) ON CONFLICT(channel) DO UPDATE SET code_hash=excluded.code_hash,expires=excluded.expires", (channel, digest, now+600))
    return code

def bind(conn, channel, code, chat_id, now=None):
    now = time.time() if now is None else now
    if channel not in CHANNELS or not isinstance(code, str) or len(code) != 8 or not code.isdecimal() or not isinstance(chat_id, str) or not chat_id.isdecimal() or len(chat_id)>30:
        return False
    row = conn.execute("SELECT code_hash,expires FROM notify_channels WHERE channel=?", (channel,)).fetchone()
    if not row or not row["code_hash"] or row["expires"] <= now or not hmac.compare_digest(row["code_hash"], hashlib.sha256(code.encode()).hexdigest()):
        return False
    conn.execute("UPDATE notify_channels SET chat_id=?,code_hash=NULL,expires=NULL,enabled=1 WHERE channel=?", (chat_id, channel))
    return True

def settings(conn):
    result = {}
    for channel in CHANNELS:
        row = conn.execute("SELECT enabled,chat_id FROM notify_channels WHERE channel=?", (channel,)).fetchone()
        result[channel] = {"enabled": bool(row["enabled"]) if row else False, "linked": bool(row["chat_id"]) if row else False,
                           "events": {event: bool((r := conn.execute("SELECT enabled FROM notify_preferences WHERE channel=? AND event=?", (channel,event)).fetchone()) is None or r["enabled"]) for event in EVENTS}}
    return result

def enqueue(conn, event, key, message, now=None):
    now = time.time() if now is None else now
    if event not in EVENTS or not isinstance(key, str) or not 1 <= len(key) <= 120 or not isinstance(message, str) or not 1 <= len(message) <= 2000:
        return 0
    count = 0
    for channel in CHANNELS:
        row = conn.execute("SELECT enabled,chat_id FROM notify_channels WHERE channel=?", (channel,)).fetchone()
        pref = conn.execute("SELECT enabled FROM notify_preferences WHERE channel=? AND event=?", (channel,event)).fetchone()
        if not row or not row["enabled"] or not row["chat_id"] or (pref is not None and not pref["enabled"]):
            continue
        last = conn.execute("SELECT created FROM notify_jobs WHERE channel=? AND event=? AND event_key=? ORDER BY created DESC LIMIT 1", (channel,event,key)).fetchone()
        if last and now - last["created"] < QUIET:
            continue
        conn.execute("INSERT INTO notify_jobs(channel,event,event_key,message,created,next_at,attempts,status) VALUES(?,?,?,?,?,?,0,'pending')", (channel,event,key,message,now,now))
        count += 1
    return count

def deliver_due(conn, paths, client=http_json, now=None):
    now = time.time() if now is None else now
    completed = 0
    for job in conn.execute("SELECT * FROM notify_jobs WHERE status='pending' AND next_at<=? ORDER BY id LIMIT 50", (now,)).fetchall():
        row = conn.execute("SELECT enabled,chat_id FROM notify_channels WHERE channel=?", (job["channel"],)).fetchone()
        outcome = "failed"
        if not row or not row["enabled"] or not row["chat_id"]:
            outcome = "disabled"
        else:
            try:
                send(job["channel"], token_from_file(job["channel"], paths), row["chat_id"], job["message"], client)
                outcome = "delivered"
            except (OSError, ValueError, KeyError, TypeError, TimeoutError):
                outcome = "failed"
        attempts = job["attempts"]+1
        status = outcome if outcome != "failed" or attempts >= 4 else "pending"
        conn.execute("UPDATE notify_jobs SET attempts=?,status=?,next_at=? WHERE id=?", (attempts,status,now+DELAY,job["id"]))
        conn.execute("INSERT INTO notify_log(ts,channel,event,event_key,result,attempt) VALUES(?,?,?,?,?,?)", (now,job["channel"],job["event"],job["event_key"],outcome,attempts))
        completed += 1
    return completed

def parse_update(channel, payload):
    if channel == "telegram":
        msg = payload.get("message", {})
        chat = msg.get("chat", {})
        return str(chat.get("id","")), msg.get("text","")
    if channel == "max":
        msg = payload.get("message", {})
        body = msg.get("body", {})
        recipient = msg.get("recipient", {})
        return str(recipient.get("chat_id","")), body.get("text","")
    return "", ""

def poll_bindings(conn, channel, paths, client=http_json, now=None):
    """Owner-initiated long polling for initial pairing; production should use signed webhook."""
    if channel not in CHANNELS:
        raise ValueError("invalid_channel")
    token = token_from_file(channel, paths)
    if channel == "max":
        url = MAX_URL + "/updates?limit=100&timeout=0"
        result = client(url, {"Authorization": token}, timeout=10)
        updates = result.get("updates", [])
    else:
        url = TELEGRAM_URL + "/bot" + token + "/getUpdates?timeout=0&limit=100"
        result = client(url, {}, timeout=10)
        if result.get("ok") is not True:
            raise ValueError("poll_failed")
        updates = result.get("result", [])
    if not isinstance(updates, list) or len(updates) > 100:
        raise ValueError("invalid_updates")
    matched = 0
    for update in updates:
        if not isinstance(update, dict):
            continue
        ident = update.get("update_id")
        if type(ident) not in (str,int) or not 1 <= len(str(ident)) <= 100:
            continue
        if conn.execute("SELECT 1 FROM notify_inbound WHERE channel=? AND update_id=?", (channel,str(ident))).fetchone():
            continue
        chat, text = parse_update(channel, update)
        if isinstance(text,str) and bind(conn,channel,text.strip(),chat,now):
            matched += 1
            try:
                send(channel,token,chat,"CreatePortal: канал подключён.",client)
            except (ValueError,OSError,TimeoutError,TypeError):
                pass
        conn.execute("INSERT OR IGNORE INTO notify_inbound(channel,update_id) VALUES(?,?)",(channel,str(ident)))
    return matched
