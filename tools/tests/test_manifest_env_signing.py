import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sign_manifest_env import sign
from manifest_security import canonical_json, verify_file


class ManifestEnvironmentSigningTests(unittest.TestCase):
    def test_sign_verify_and_tamper(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
        private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
        public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "update.json"
            s = Path(d) / "update.json.sig"
            pub = Path(d) / "public.pem"
            pub.write_bytes(public)
            p.write_bytes(canonical_json({"version_code": 1}))
            sign(p, s, pub, private)
            self.assertTrue(verify_file(p, s, pub))
            with self.assertRaises(FileExistsError):
                sign(p, s, pub, private)
            p.write_bytes(canonical_json({"version_code": 2}))
            self.assertFalse(verify_file(p, s, pub))

    def test_missing_secret_fails_closed(self):
        with self.assertRaises(ValueError):
            sign("missing.json", "missing.sig", "missing.pem", None)


if __name__ == "__main__":
    unittest.main()
