"""Plain-text SMTP delivery and persistent per-address/IP mail quotas.

The caller uses an SQLite connection opened with sqlite_util or a psycopg
connection. The quota reservation is independent of whether the account exists.
"""
import hashlib
import os
import smtplib
import ssl
from email.message import EmailMessage


def _identifier(namespace, value):
    return hashlib.sha256((namespace + ":" + value).encode("utf-8")).hexdigest()


def reserve(db, ph, address, client, now, postgres=False):
    """Reserve one mail request. False on cooldown/quota, no account enumeration.

    A reservation counts even when an address does not exist or SMTP fails.
    This prevents address probing and repeated retries from bypassing limits.
    """
    if postgres:
        db.execute("SELECT pg_advisory_xact_lock(20261114, 78)")
    else:
        db.execute("BEGIN IMMEDIATE")
    db.execute("""
        CREATE TABLE IF NOT EXISTS ops_email_throttle (
            key TEXT PRIMARY KEY,
            window_start BIGINT NOT NULL,
            count INTEGER NOT NULL,
            last_sent_at BIGINT NOT NULL
        )
    """)
    keys = (
        (_identifier("email", address), 5, 60),
        (_identifier("ip", client), 20, 0),
    )
    updates = []
    for key, limit, cooldown in keys:
        row = db.execute(
            "SELECT window_start,count,last_sent_at FROM ops_email_throttle WHERE key=" + ph,
            (key,),
        ).fetchone()
        if row:
            window_start, count, last_sent = row
            if now < last_sent + cooldown:
                db.rollback()
                return False
            if now < window_start + 3600 and count >= limit:
                db.rollback()
                return False
            if now >= window_start + 3600:
                window_start, count = now, 0
        else:
            window_start, count = now, 0
        updates.append((key, window_start, count + 1, now))
    for values in updates:
        placeholders = ",".join([ph] * 4)
        db.execute(
            "INSERT INTO ops_email_throttle(key,window_start,count,last_sent_at) "
            "VALUES(" + placeholders + ") ON CONFLICT(key) DO UPDATE SET "
            "window_start=excluded.window_start,count=excluded.count,"
            "last_sent_at=excluded.last_sent_at",
            values,
        )
    db.commit()
    return True


def send_smtp(address, subject, message):
    """SMTP with TLS by default, plaintext restricted to local fake servers."""
    host = os.environ.get("LUNEX_SMTP_HOST", "").strip()
    sender = os.environ.get("LUNEX_SMTP_FROM", "").strip()
    password = os.environ.get("LUNEX_SMTP_PASSWORD", "")
    user = os.environ.get("LUNEX_SMTP_USER", "")
    if not host or not sender:
        return False
    loopback = host in ("127.0.0.1", "::1", "localhost")
    try:
        port = int(os.environ.get("LUNEX_SMTP_PORT", "587"))
        if not (1 <= port <= 65535):
            return False
        mode = os.environ.get("LUNEX_SMTP_TLS", "implicit" if port == 465 else "starttls").lower()
        if mode not in ("implicit", "starttls", "off"):
            return False
        if mode == "off" and not loopback:
            return False
        if (not user or not password) and not (loopback and mode == "off"):
            return False
        mail = EmailMessage()
        mail["From"] = sender
        mail["To"] = address
        mail["Subject"] = subject
        mail.set_content(message, subtype="plain", charset="utf-8")
        tls_context = ssl.create_default_context()
        if mode == "implicit":
            connection = smtplib.SMTP_SSL(host, port, timeout=10, context=tls_context)
        else:
            connection = smtplib.SMTP(host, port, timeout=10)
        with connection as smtp:
            if mode == "starttls":
                smtp.ehlo()
                smtp.starttls(context=tls_context)
                smtp.ehlo()
            if user:
                smtp.login(user, password)
            smtp.send_message(mail)
        return True
    except (OSError, ValueError, smtplib.SMTPException, ssl.SSLError):
        return False
