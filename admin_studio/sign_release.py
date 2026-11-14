#!/usr/bin/env python3
"""Sign a World Studio release OFFLINE and upload the detached signature.

The private key stays on the administrator's own machine: this script downloads the exact manifest bytes, signs them with `openssl`
(RSA, SHA-256, PKCS#1 v1.5, the scheme the Android client verifies) and posts only the signature back.

    export LUNEX_ADMIN_TOKEN=...        # studio token, never on the command line
    python3 sign_release.py --studio https://studio.example --key private.pem --revision 7
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path


def call(url, token, data=None):
    req = urllib.request.Request(url, data=None if data is None else json.dumps(data).encode(), method="GET" if data is None else "POST",
                                 headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as response:
        return response.read()


def sign_bytes(key_path, message):
    with tempfile.TemporaryDirectory() as directory:
        message_path, signature_path = Path(directory, "m"), Path(directory, "s")
        message_path.write_bytes(message)
        subprocess.run(["openssl", "dgst", "-sha256", "-sign", str(key_path), "-out", str(signature_path), str(message_path)], check=True, capture_output=True)
        return signature_path.read_bytes()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--studio", required=True, help="studio base URL, e.g. http://127.0.0.1:18991 (through an SSH tunnel)")
    parser.add_argument("--key", required=True, help="private RSA key (PEM); never leaves this machine")
    parser.add_argument("--revision", required=True, type=int)
    args = parser.parse_args(argv)
    token = os.environ.get("LUNEX_ADMIN_TOKEN", "")
    if len(token) < 32:
        print("LUNEX_ADMIN_TOKEN must be set in the environment", file=sys.stderr)
        return 2
    base = args.studio.rstrip("/")
    manifest = call("%s/api/releases/%d/manifest" % (base, args.revision), token)
    info = json.loads(manifest)
    print("Revision %d: %d assets, manifest %d bytes" % (info["revision"], len(info["assets"]), len(manifest)))
    signature = base64.b64encode(sign_bytes(args.key, manifest)).decode()
    result = json.loads(call(base + "/api/sign", token, {"revision": args.revision, "signature": signature}))
    print("Signed:", result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
