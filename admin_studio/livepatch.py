"""Isolated content patch store. Never executes uploaded content."""
import hashlib
import json
import os
import base64
import binascii
import re
import sqlite3
import struct
import subprocess
import tempfile
import threading
import time
from pathlib import Path

CATEGORIES = {"agriculture", "industry", "housing", "municipal", "commerce", "nature", "roads", "ui"}
MIMES = {"png": b"\x89PNG\r\n\x1a\n", "webp": b"RIFF"}
MAX_FILE = 8 * 1024 * 1024
MAX_GLB = 20 * 1024 * 1024
MAX_DIMENSION = 2048                       # also enforced by the Android client before decoding
MAX_PIXELS = 4 * 1024 * 1024
MAX_SIGNATURE = 2048
LOCK = threading.RLock()


def image_dimensions(extension, payload):
    """(width, height) read from the file header only; raises ValueError for anything that is not a plain PNG / WebP header.

    Reading the header instead of decoding keeps a tiny file that expands to gigabytes ("decompression bomb") away from every decoder."""
    if extension == "png":
        if len(payload) < 24 or payload[:8] != MIMES["png"] or payload[12:16] != b"IHDR":
            raise ValueError("invalid PNG")
        width, height = struct.unpack(">II", payload[16:24])
    elif extension == "webp":
        if len(payload) < 30 or payload[:4] != b"RIFF" or payload[8:12] != b"WEBP":
            raise ValueError("invalid WebP")
        kind = payload[12:16]
        if kind == b"VP8 ":
            if payload[23:26] != b"\x9d\x01\x2a":
                raise ValueError("invalid WebP")
            width, height = struct.unpack("<HH", payload[26:30])
            width, height = width & 0x3FFF, height & 0x3FFF
        elif kind == b"VP8L":
            if payload[20] != 0x2F:
                raise ValueError("invalid WebP")
            bits = struct.unpack("<I", payload[21:25])[0]
            width, height = (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        elif kind == b"VP8X":
            width = int.from_bytes(payload[24:27], "little") + 1
            height = int.from_bytes(payload[27:30], "little") + 1
        else:
            raise ValueError("invalid WebP")
    else:
        raise ValueError("invalid image")
    if not (1 <= width <= MAX_DIMENSION and 1 <= height <= MAX_DIMENSION and width * height <= MAX_PIXELS):
        raise ValueError("image dimensions out of range (max %d x %d)" % (MAX_DIMENSION, MAX_DIMENSION))
    return width, height

def _ip(ip):
    return " · ip=" + str(ip)[:64] if ip else ""


def canonical(manifest):
    """The exact bytes that are signed, stored and served: stable key order, no whitespace."""
    return json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class _Closing:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        self.db.__enter__()
        return self.db

    def __exit__(self, *exc):
        try:
            return self.db.__exit__(*exc)
        finally:
            self.db.close()


class Store:
    def __init__(self, root, public_key=None):
        # `public_key`: path of the PEM public key that verifies release signatures. The private key never reaches this service.
        self.public_key = Path(public_key) if public_key else None
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "blobs").mkdir(exist_ok=True)
        self.db = self.root / "studio.sqlite3"
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS assets(
                id TEXT PRIMARY KEY, category TEXT NOT NULL, title TEXT NOT NULL,
                prompt TEXT NOT NULL, digest TEXT NOT NULL, extension TEXT NOT NULL,
                bytes INTEGER NOT NULL, updated INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS releases(
                revision INTEGER PRIMARY KEY AUTOINCREMENT,
                created INTEGER NOT NULL, manifest TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS audit(
                id INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER NOT NULL,
                action TEXT NOT NULL, subject TEXT NOT NULL, details TEXT NOT NULL);
            """)
            if "signature" not in [row[1] for row in db.execute("PRAGMA table_info(releases)")]:
                db.execute("ALTER TABLE releases ADD COLUMN signature TEXT")

    def connect(self):
        """A connection that is really closed at the end of a `with` block (sqlite3's own context manager only commits)."""
        db = sqlite3.connect(self.db, timeout=10)
        db.row_factory = sqlite3.Row
        return _Closing(db)

    def list_assets(self):
        with self.connect() as db:
            return [dict(x) for x in db.execute("SELECT * FROM assets ORDER BY category,title,id")]

    def add_asset(self, asset_id, category, title, prompt, extension, payload, ip=""):
        if not re.fullmatch(r"[a-z][a-z0-9_-]{1,63}", asset_id):
            raise ValueError("invalid asset id")
        if category not in CATEGORIES or not 1 <= len(title) <= 100 or len(prompt) > 4000:
            raise ValueError("invalid metadata")
        if extension not in (*MIMES, "glb") or not 12 <= len(payload) <= (MAX_GLB if extension == "glb" else MAX_FILE):
            raise ValueError("invalid asset")
        if extension == "glb":
            # GLB 2.0 only: 12-byte header and strict total length.
            if payload[:4] != b"glTF" or struct.unpack("<II", payload[4:12]) != (2, len(payload)):
                raise ValueError("invalid_glb")
        if extension == "png" and not payload.startswith(MIMES["png"]):
            raise ValueError("invalid PNG")
        if extension == "webp" and not (payload.startswith(b"RIFF") and payload[8:12] == b"WEBP"):
            raise ValueError("invalid WebP")
        if extension != "glb": image_dimensions(extension, payload)
        digest = hashlib.sha256(payload).hexdigest()
        filename = digest + "." + extension
        with LOCK:
            target = self.root / "blobs" / filename
            if not target.exists():
                fd, temp = tempfile.mkstemp(dir=self.root / "blobs")
                try:
                    with os.fdopen(fd, "wb") as f:
                        f.write(payload)
                    os.replace(temp, target)
                finally:
                    if os.path.exists(temp):
                        os.unlink(temp)
            with self.connect() as db:
                db.execute("""INSERT INTO assets VALUES(?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET category=excluded.category,
                    title=excluded.title,prompt=excluded.prompt,digest=excluded.digest,
                    extension=excluded.extension,bytes=excluded.bytes,updated=excluded.updated""",
                    (asset_id, category, title, prompt, digest, extension, len(payload), int(time.time())))
                db.execute("INSERT INTO audit(at,action,subject,details) VALUES(?,?,?,?)",
                           (int(time.time()), "asset_upsert", asset_id, digest + _ip(ip)))
        return {"id": asset_id, "sha256": digest, "size": len(payload)}

    def publish(self, ip=""):
        with LOCK, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            assets = [dict(row) for row in db.execute("SELECT * FROM assets ORDER BY id")]
            if len(assets) > 300:
                raise ValueError("asset_limit_exceeded")
            revision = int(db.execute("SELECT COALESCE(MAX(revision),0)+1 FROM releases").fetchone()[0])
            manifest = {"schema": 1, "revision": revision, "assets": [
                {"id": a["id"], "category": a["category"], "title": a["title"],
                 "sha256": a["digest"], "size": a["bytes"], "extension": a["extension"],
                 "url": "blobs/" + a["digest"] + "." + a["extension"]}
                for a in assets]}
            db.execute("INSERT INTO releases(revision,created,manifest) VALUES(?,?,?)",
                       (revision, int(time.time()), canonical(manifest)))
            db.execute("INSERT INTO audit(at,action,subject,details) VALUES(?,?,?,?)",
                       (int(time.time()), "publish", str(revision), str(len(assets)) + _ip(ip)))
            return manifest

    def rollback(self, target_revision, ip=""):
        """Reissue a historical snapshot as a NEW monotonic revision; never mutate history."""
        if type(target_revision) is not int or target_revision < 1:
            raise ValueError("invalid_revision")
        with LOCK, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT manifest FROM releases WHERE revision=?", (target_revision,)).fetchone()
            if row is None:
                raise ValueError("revision_not_found")
            snapshot = json.loads(row[0])
            for asset in snapshot["assets"]:
                name = asset["sha256"] + "." + asset["extension"]
                if not (self.root / "blobs" / name).is_file():
                    raise ValueError("missing_release_blob")
            revision = db.execute("SELECT COALESCE(MAX(revision),0)+1 FROM releases").fetchone()[0]
            snapshot["revision"] = revision
            db.execute("INSERT INTO releases(revision,created,manifest) VALUES(?,?,?)",
                       (revision, int(time.time()), canonical(snapshot)))
            db.execute("INSERT INTO audit(at,action,subject,details) VALUES(?,?,?,?)",
                       (int(time.time()), "rollback_release", str(revision), str(target_revision) + _ip(ip)))
            return snapshot

    def releases(self):
        with self.connect() as db:
            return [{"revision": row["revision"], "created": row["created"], "signed": row["signature"] is not None,
                     "assets": len(json.loads(row["manifest"])["assets"])}
                    for row in db.execute("SELECT revision,created,manifest,signature FROM releases ORDER BY revision DESC LIMIT 100")]

    def manifest_text(self, revision):
        with self.connect() as db:
            row = db.execute("SELECT manifest FROM releases WHERE revision=?", (revision,)).fetchone()
            return None if row is None else row[0]

    def manifest(self, revision=None):
        with self.connect() as db:
            if revision is None:
                row = db.execute("SELECT manifest FROM releases ORDER BY revision DESC LIMIT 1").fetchone()
            else:
                row = db.execute("SELECT manifest FROM releases WHERE revision=?", (revision,)).fetchone()
            return json.loads(row[0]) if row else {"schema": 1, "revision": 0, "assets": []}

    @property
    def signing_enabled(self):
        return self.public_key is not None and self.public_key.is_file()

    def public_manifest(self):
        """(manifest_text, signature_base64 or None) for clients. With a public key configured only a SIGNED release is ever served."""
        empty = canonical({"schema": 1, "revision": 0, "assets": []})
        with self.connect() as db:
            if self.signing_enabled:
                row = db.execute("SELECT manifest,signature FROM releases WHERE signature IS NOT NULL ORDER BY revision DESC LIMIT 1").fetchone()
                return (row[0], row[1]) if row else (empty, None)
            row = db.execute("SELECT manifest FROM releases ORDER BY revision DESC LIMIT 1").fetchone()
            return (row[0], None) if row else (empty, None)

    def sign(self, revision, signature_b64, ip=""):
        """Store a detached RSA-SHA256 signature made offline over the exact manifest bytes; verified here before it is accepted."""
        if not self.signing_enabled:
            raise ValueError("signing_not_configured")
        if type(revision) is not int or revision < 1 or not isinstance(signature_b64, str) or not 1 <= len(signature_b64) <= MAX_SIGNATURE:
            raise ValueError("invalid_signature_request")
        try:
            signature = base64.b64decode(signature_b64, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("invalid_signature_encoding")
        text = self.manifest_text(revision)
        if text is None:
            raise ValueError("revision_not_found")
        if not verify_signature(self.public_key, text.encode("utf-8"), signature):
            raise ValueError("signature_does_not_verify")
        with LOCK, self.connect() as db:
            db.execute("UPDATE releases SET signature=? WHERE revision=?", (signature_b64, revision))
            db.execute("INSERT INTO audit(at,action,subject,details) VALUES(?,?,?,?)",
                       (int(time.time()), "sign_release", str(revision), hashlib.sha256(signature).hexdigest()[:16] + _ip(ip)))
        return {"revision": revision, "signed": True}

    def audit(self):
        with self.connect() as db:
            return [dict(x) for x in db.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 100")]


def verify_signature(public_key, message, signature):
    """RSA PKCS#1 v1.5 / SHA-256 verification through the openssl command line (the Python standard library has no RSA)."""
    with tempfile.TemporaryDirectory() as directory:
        message_path = Path(directory, "message")
        signature_path = Path(directory, "signature")
        message_path.write_bytes(message)
        signature_path.write_bytes(signature)
        try:
            result = subprocess.run(["openssl", "dgst", "-sha256", "-verify", str(public_key), "-signature", str(signature_path), str(message_path)],
                                    capture_output=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0
