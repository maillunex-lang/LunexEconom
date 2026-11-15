#!/usr/bin/env python3
"""Sign a canonical manifest with an environment-provided PEM; no private-key file."""
import argparse
import base64
import json
import os
from pathlib import Path

from manifest_security import canonical_json, verify_file


def sign(manifest, signature, public_key, pem):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    if not pem:
        raise ValueError("MANIFEST_SIGNING_KEY is missing")
    key = serialization.load_pem_private_key(pem.encode("ascii"), password=None)
    if not isinstance(key, rsa.RSAPrivateKey) or key.key_size != 4096:
        raise ValueError("Expected RSA-4096 manifest signing key")
    path = Path(manifest)
    original = path.read_bytes()
    canonical = canonical_json(json.loads(original))
    if original != canonical:
        raise ValueError("Manifest must already be canonical")
    signature_path = Path(signature)
    if signature_path.exists():
        raise FileExistsError("Signature already exists")
    signed = key.sign(canonical, padding.PKCS1v15(), hashes.SHA256())
    signature_path.write_text(base64.b64encode(signed).decode("ascii") + "\n", encoding="ascii")
    if not verify_file(path, signature_path, public_key):
        signature_path.unlink()
        raise ValueError("Signature verification failed")
    return signature_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest")
    parser.add_argument("--public-key", required=True)
    parser.add_argument("--signature", required=True)
    args = parser.parse_args()
    sign(args.manifest, args.signature, args.public_key, os.environ.get("MANIFEST_SIGNING_KEY"))
    print("Manifest signature verified")


if __name__ == "__main__":
    main()
