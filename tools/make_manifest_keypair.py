#!/usr/bin/env python3
"""Generate an offline RSA manifest signing key outside the source tree.

Run only on the owner's trusted local machine, never on CI or the VPS.
"""
import argparse
import os
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def generate(directory: Path, repository: Path | None = None) -> Path:
    directory = directory.expanduser().resolve()
    repository = (repository or Path(__file__).resolve().parents[1]).resolve()
    if directory == repository or repository in directory.parents:
        raise ValueError('Private key directory must be outside the repository')
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    private = directory / 'lunex-manifest-private.pem'
    public = directory / 'lunex-manifest-public.pem'
    if private.exists() or public.exists():
        raise FileExistsError('Key files already exist; refusing overwrite')
    key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    raw = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    fd = os.open(private, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
    except BaseException:
        private.unlink(missing_ok=True)
        raise
    pem = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    public.write_bytes(pem)
    return public


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    pub = generate(args.output_dir)
    print('Private key saved locally with mode 0600 (contents never printed).')
    print('Public key (safe to share):')
    print(pub.read_text(), end='')
