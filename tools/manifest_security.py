"""Canonical signed-manifest utilities; signatures are detached RSA-PKCS1v15/SHA256."""
import base64
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse


def canonical_json(payload):
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def sign_file(manifest, private_key, signature=None):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    path = Path(manifest)
    key = serialization.load_pem_private_key(Path(private_key).read_bytes(), password=None)
    # Only canonical bytes are signed; no ambiguous equivalent JSON encodings.
    content = canonical_json(json.loads(path.read_text(encoding="utf-8")))
    path.write_bytes(content)
    signature_bytes = key.sign(content, padding.PKCS1v15(), hashes.SHA256())
    target = Path(signature) if signature else Path(str(path) + ".sig")
    target.write_text(base64.b64encode(signature_bytes).decode("ascii") + "\n", encoding="ascii")
    return target


def verify_file(manifest, signature, public_key):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    data = Path(manifest).read_bytes()
    try:
        if canonical_json(json.loads(data)) != data:
            return False
        key = serialization.load_pem_public_key(Path(public_key).read_bytes())
        sig = base64.b64decode(Path(signature).read_text().strip(), validate=True)
        key.verify(sig, data, padding.PKCS1v15(), hashes.SHA256())
        return True
    except (ValueError, TypeError, UnicodeDecodeError):
        return False
    except Exception:
        return False


def validate_https_file_url(url, base):
    candidate, site = urlparse(url), urlparse(base)
    if site.scheme != "https" or not site.hostname or site.username or site.password:
        return False
    return (candidate.scheme == "https" and candidate.hostname == site.hostname
            and candidate.port == site.port and candidate.username is None and candidate.password is None
            and not candidate.fragment and not candidate.query
            and candidate.path.startswith(site.path.rstrip("/") + "/")
            and ".." not in candidate.path.split("/"))


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()
