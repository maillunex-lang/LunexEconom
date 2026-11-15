"""Signed public client configuration.

The running server never holds the private signing key. The operator signs a
candidate offline and uploads a detached RSA-SHA256 signature to the protected
administrative API. Client changes remain staged until that signature is accepted.
"""
import base64
import binascii
import json
import os
import subprocess
import tempfile
from pathlib import Path

import runtime_config

PUBLIC_KEY_ENV = "LUNEX_LIVE_CONFIG_PUBLIC_KEY"
MAX_CONFIG_BYTES = 65536
MAX_SIGNATURE_BYTES = 1024


def ensure(db, ph):
    db.execute("""CREATE TABLE IF NOT EXISTS signed_live_config(
      id INTEGER PRIMARY KEY, revision INTEGER NOT NULL,
      payload TEXT NOT NULL, signature TEXT NOT NULL, signed_at BIGINT NOT NULL)""")


def canonical(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def candidate(db):
    snap = runtime_config.snapshot(db)
    client = runtime_config.client_settings(db)
    current = runtime_config.values(db)
    flags = {name.lower(): bool(current.get(name, runtime_config._initial(name)))
             for name in sorted(runtime_config.CLIENT_FLAGS)}
    return {"schema": 1, "revision": snap["revision"],
            "flags": flags, "parameters": {}, "texts": client["texts"],
            "min_version": client["min_version"],
            "recommended_version": client["recommended_version"],
            "patch_manifest_url": client["patch_url"],
            "maintenance": bool(current.get("MAINTENANCE_MODE", runtime_config._initial("MAINTENANCE_MODE")))}


def verify(public_key, data, signature):
    if not public_key or not Path(public_key).is_file():
        return False
    if not data or len(data) > MAX_CONFIG_BYTES or not signature or len(signature) > MAX_SIGNATURE_BYTES:
        return False
    try:
        with tempfile.TemporaryDirectory() as tmp:
            source, sig = Path(tmp, "config"), Path(tmp, "signature")
            source.write_bytes(data)
            sig.write_bytes(signature)
            check = subprocess.run(["openssl", "dgst", "-sha256", "-verify",
                                    str(public_key), "-signature", str(sig), str(source)],
                                   capture_output=True, timeout=4, check=False)
            return check.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def prepare_candidate(db):
    payload = canonical(candidate(db))
    return {"revision": runtime_config.snapshot(db)["revision"],
            "payload_b64": base64.b64encode(payload).decode("ascii")}


def publish(db, ph, actor, ip, now, payload):
    if not isinstance(payload, dict):
        raise ValueError("invalid_request")
    if payload.get("confirm") is not True:
        raise ValueError("confirmation_required")
    if type(payload.get("revision")) is not int:
        raise ValueError("revision_conflict")
    if payload["revision"] != runtime_config.snapshot(db)["revision"]:
        raise ValueError("revision_conflict")
    signature_b64 = payload.get("signature", "")
    if not isinstance(signature_b64, str) or len(signature_b64) > 2048:
        raise ValueError("invalid_signature")
    try:
        signature = base64.b64decode(signature_b64, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("invalid_signature")
    raw = canonical(candidate(db))
    key = os.environ.get(PUBLIC_KEY_ENV, "")
    if not verify(key, raw, signature):
        raise ValueError("invalid_signature")
    # Immutable revision already signed; do not silently replace a release.
    previous = db.execute("SELECT revision,payload,signature FROM signed_live_config WHERE id=1").fetchone()
    if previous and previous[0] == payload["revision"]:
        if previous[1] == raw.decode("utf-8") and previous[2] == signature_b64:
            return {"revision": payload["revision"], "already_signed": True}
        raise ValueError("revision_already_signed")
    db.execute("""INSERT INTO signed_live_config(id,revision,payload,signature,signed_at)
       VALUES(1,%s,%s,%s,%s)
       ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,
       payload=excluded.payload,signature=excluded.signature,signed_at=excluded.signed_at""".replace("%s", ph),
       (payload["revision"], raw.decode("utf-8"), signature_b64, now))
    import admin_api
    admin_api.audit(db, ph, actor, "client_config_signed", str(payload["revision"]),
                    "RSA-SHA256 client config release", ip, now)
    return {"revision": payload["revision"], "signed": True}


def public(db, ph):
    row = db.execute("SELECT revision,payload,signature FROM signed_live_config WHERE id=1").fetchone()
    if row is None:
        return 503, {"error": "signed_configuration_unavailable"}
    raw = row[1].encode("utf-8")
    key = os.environ.get(PUBLIC_KEY_ENV, "")
    try:
        sig = base64.b64decode(row[2], validate=True)
    except (binascii.Error, ValueError):
        return 503, {"error": "signed_configuration_unavailable"}
    if not verify(key, raw, sig):
        return 503, {"error": "signed_configuration_unavailable"}
    return 200, {"schema": 1, "revision": int(row[0]),
                 "payload_b64": base64.b64encode(raw).decode("ascii"),
                 "signature": row[2]}
