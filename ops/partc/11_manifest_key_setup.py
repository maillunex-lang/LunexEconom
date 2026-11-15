#!/usr/bin/env python3
"""Create a NEW manifest signing key and store it ONLY as an encrypted GitHub environment secret.

Run once on the VPS by the infrastructure assistant (not CI). The private key exists only in memory: it is generated,
encrypted with the environment public key (libsodium sealed box) and uploaded; it is never written to disk and never
printed. The script also creates the protected environment `manifest-signing` restricted to the `main` branch.

Requirements: python3 with `cryptography` and `PyNaCl` (see 11_manifest_key_setup.sh which prepares a temporary venv).
Token: a TEMPORARY fine-grained GitHub token in a root-only file (default /root/.lunex-github-admin-token) with repository
permissions Environments: write, Secrets: write, Metadata: read. Delete the token on GitHub afterwards.

  python3 11_manifest_key_setup.py --dry-run
  python3 11_manifest_key_setup.py            # refuses to overwrite an existing secret
  python3 11_manifest_key_setup.py --rotate   # overwrite an existing secret (only by director's instruction)
"""
import argparse
import base64
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = os.getenv('LUNEX_REPO', 'maillunex-lang/LunexEconom')
ENV_NAME = 'manifest-signing'
SECRET_NAME = 'MANIFEST_SIGNING_KEY'
TOKEN_FILE = Path(os.getenv('LUNEX_ADMIN_TOKEN_FILE', '/root/.lunex-github-admin-token'))
PUBLIC_OUT = Path(os.getenv('LUNEX_MANIFEST_PUBLIC_OUT', '/root/lunex-manifest-public.pem'))
API = 'https://api.github.com'


def token():
    value = TOKEN_FILE.read_text(encoding='ascii').strip()
    if not re.fullmatch(r'[A-Za-z0-9_\-]{20,255}', value):
        raise SystemExit('token file has an unexpected format')
    return value


def call(method, path, body=None, ok=(200, 201, 204), tok=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method, headers={
        'Authorization': 'Bearer ' + tok, 'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'LunexEconom-key-setup',
        'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            code = resp.status
    except urllib.error.HTTPError as exc:
        raw, code = exc.read(), exc.code
    if code not in ok:
        raise SystemExit('GitHub API %s %s failed with HTTP %s (details withheld)' % (method, path, code))
    return code, (json.loads(raw) if raw else {})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--rotate', action='store_true')
    args = ap.parse_args()
    tok = token()
    base = '/repos/%s' % REPO
    call('GET', base, tok=tok)
    print('repository reachable:', REPO)
    env_path = '%s/environments/%s' % (base, ENV_NAME)
    exists = call('GET', env_path + '/secrets', tok=tok, ok=(200, 404))
    already = exists[0] == 200 and any(s.get('name') == SECRET_NAME for s in exists[1].get('secrets', []))
    if already and not args.rotate:
        raise SystemExit('secret %s already exists in environment %s: refusing to overwrite (use --rotate only by director instruction)' % (SECRET_NAME, ENV_NAME))
    if args.dry_run:
        print('DRY RUN: would create environment %s restricted to branch main, generate a new RSA-4096 key in memory, upload it as secret %s and write the public key to %s' % (ENV_NAME, SECRET_NAME, PUBLIC_OUT))
        return 0
    # 1. environment restricted to the main branch, no manual reviewers (director decision: automatic, guarded by release checks)
    call('PUT', env_path, {'deployment_branch_policy': {'protected_branches': False, 'custom_branch_policies': True}}, tok=tok)
    code, _ = call('POST', env_path + '/deployment-branch-policies', {'name': 'main', 'type': 'branch'}, ok=(200, 201, 422), tok=tok)
    print('environment %s ready, branch policy main (HTTP %s)' % (ENV_NAME, code))
    # 2. key pair in memory only
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from nacl import encoding, public
    key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    private_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    public_der = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    public_pem = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    # 3. encrypt with the environment public key and upload
    _, pk = call('GET', env_path + '/secrets/public-key', tok=tok)
    sealed = public.SealedBox(public.PublicKey(pk['key'].encode(), encoding.Base64Encoder())).encrypt(private_pem)
    call('PUT', '%s/secrets/%s' % (env_path, SECRET_NAME),
         {'encrypted_value': base64.b64encode(sealed).decode(), 'key_id': pk['key_id']}, ok=(201, 204), tok=tok)
    del private_pem, key
    # 4. verify the secret exists (value is never readable) and publish the PUBLIC half
    _, listing = call('GET', env_path + '/secrets', tok=tok)
    assert any(s.get('name') == SECRET_NAME for s in listing.get('secrets', [])), 'secret not found after upload'
    PUBLIC_OUT.write_bytes(public_pem)
    os.chmod(PUBLIC_OUT, 0o644)
    print('secret %s stored in environment %s (private key was never written to disk)' % (SECRET_NAME, ENV_NAME))
    print('PUBLIC KEY SHA-256 (DER):', hashlib.sha256(public_der).hexdigest())
    print('PUBLIC KEY FILE:', PUBLIC_OUT)
    print(public_pem.decode())
    print('NEXT: delete the temporary GitHub token; send the public key text to the director (it is public).')
    return 0


if __name__ == '__main__':
    sys.exit(main())
