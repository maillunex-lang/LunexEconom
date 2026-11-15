"""Offline operator CLI: sign canonical JSON with RSA PKCS#1 v1.5 SHA256.

Private key stays outside the repository. Example:
  LUNEX_DATABASE_URL=... python tools/sign_config.py --private-key /secure/config-private.pem --payload ./config.json
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import padding,rsa
from server import db


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')


def sign(private_key, payload):
    if not isinstance(private_key,rsa.RSAPrivateKey) or private_key.key_size<2048:
        raise ValueError('RSA >=2048 required')
    wire=canonical(payload)
    return base64.b64encode(wire).decode(),base64.b64encode(private_key.sign(wire,padding.PKCS1v15(),hashes.SHA256())).decode()


def verify(public_key,payload_b64,signature):
    try:
        wire=base64.b64decode(payload_b64,validate=True)
        obj=json.loads(wire)
        if canonical(obj)!=wire:
            return False
        public_key.verify(base64.b64decode(signature,validate=True),wire,padding.PKCS1v15(),hashes.SHA256())
        return True
    except Exception:
        return False


def main():
    parser=argparse.ArgumentParser(description='Offline signed client config publisher')
    parser.add_argument('--private-key',type=Path,required=True)
    parser.add_argument('--payload',type=Path,required=True)
    args=parser.parse_args()
    if not args.private_key.is_file() or not args.payload.is_file():
        parser.error('key or JSON payload missing')
    key=serialization.load_pem_private_key(args.private_key.read_bytes(),password=None)
    payload=json.loads(args.payload.read_text('utf-8'))
    if not isinstance(payload,dict):
        parser.error('JSON object required')
    encoded,signature=sign(key,payload)
    with db.connect() as conn:
        with conn.transaction():
            conn.execute('SELECT pg_advisory_xact_lock(2026111599)')
            revision=conn.execute('SELECT COALESCE(MAX(revision),0)+1 FROM signed_client_config').fetchone()[0]
            conn.execute('INSERT INTO signed_client_config(revision,payload_b64,signature) VALUES(%s,%s,%s)',(revision,encoded,signature))
            from psycopg.types.json import Jsonb
            conn.execute('INSERT INTO audit(actor,action,payload) VALUES(%s,%s,%s)',('operator:cli','config.sign',Jsonb({'revision':revision,'sha256':hashlib.sha256(canonical(payload)).hexdigest()})))
        conn.commit()
    print('Signed public config revision',revision)

if __name__=='__main__': main()
