"""Isolated content patch store. Never executes uploaded content."""
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import threading
import time
from pathlib import Path

CATEGORIES = {"agriculture", "industry", "housing", "municipal", "commerce", "nature", "roads", "ui"}
MIMES = {"png": b"\x89PNG\r\n\x1a\n", "webp": b"RIFF"}
MAX_FILE = 8 * 1024 * 1024
LOCK = threading.RLock()

class Store:
    def __init__(self, root):
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

    def connect(self):
        db = sqlite3.connect(self.db, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def list_assets(self):
        with self.connect() as db:
            return [dict(x) for x in db.execute("SELECT * FROM assets ORDER BY category,title,id")]

    def add_asset(self, asset_id, category, title, prompt, extension, payload):
        if not re.fullmatch(r"[a-z][a-z0-9_-]{1,63}", asset_id):
            raise ValueError("invalid asset id")
        if category not in CATEGORIES or not 1 <= len(title) <= 100 or len(prompt) > 4000:
            raise ValueError("invalid metadata")
        if extension not in MIMES or not 12 <= len(payload) <= MAX_FILE:
            raise ValueError("invalid image")
        if extension == "png" and not payload.startswith(MIMES["png"]):
            raise ValueError("invalid PNG")
        if extension == "webp" and not (payload.startswith(b"RIFF") and payload[8:12] == b"WEBP"):
            raise ValueError("invalid WebP")
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
                           (int(time.time()), "asset_upsert", asset_id, digest))
        return {"id": asset_id, "sha256": digest, "size": len(payload)}

    def publish(self):
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
                       (revision, int(time.time()), json.dumps(manifest, ensure_ascii=False)))
            db.execute("INSERT INTO audit(at,action,subject,details) VALUES(?,?,?,?)",
                       (int(time.time()), "publish", str(revision), str(len(assets))))
            return manifest

    def rollback(self, target_revision):
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
                       (revision, int(time.time()), json.dumps(snapshot, ensure_ascii=False)))
            db.execute("INSERT INTO audit(at,action,subject,details) VALUES(?,?,?,?)",
                       (int(time.time()), "rollback_release", str(revision), str(target_revision)))
            return snapshot

    def releases(self):
        with self.connect() as db:
            return [{"revision": row["revision"], "created": row["created"],
                     "assets": len(json.loads(row["manifest"])["assets"])}
                    for row in db.execute("SELECT revision,created,manifest FROM releases ORDER BY revision DESC LIMIT 100")]

    def manifest(self, revision=None):
        with self.connect() as db:
            if revision is None:
                row = db.execute("SELECT manifest FROM releases ORDER BY revision DESC LIMIT 1").fetchone()
            else:
                row = db.execute("SELECT manifest FROM releases WHERE revision=?", (revision,)).fetchone()
            return json.loads(row[0]) if row else {"schema": 1, "revision": 0, "assets": []}

    def audit(self):
        with self.connect() as db:
            return [dict(x) for x in db.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 100")]
