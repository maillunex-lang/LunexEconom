import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from manifest_security import canonical_json, sign_file, verify_file, validate_https_file_url
from release_version import parse
from verify_apk_cert import verify_file as verify_cert

class ReleaseTests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(parse("v1.2.3"), (1002003, "1.2.3"))
        self.assertLess(parse("v1.2.99")[0], parse("v1.3.0")[0])
        for bad in ("v1.1000.0", "1.2.3", "v0.0.0", "v1.2.3-beta"):
            with self.assertRaises(ValueError):
                parse(bad)

    def test_urls(self):
        base = "https://rikagro.ru/lunexeconom"
        self.assertTrue(validate_https_file_url(base+"/packs/core-1.pck",base))
        for url in ("http://rikagro.ru/lunexeconom/x", "https://evil.io/x",
                    "https://rikagro.ru.other.com/lunexeconom/x", base+"/../secret",
                    base+"/file.apk?redirect=1", "https://rikagro.ru/other/x"):
            self.assertFalse(validate_https_file_url(url,base))

    def test_cert(self):
        with tempfile.TemporaryDirectory() as temp:
            r=Path(temp)/"report"; expected=Path(temp)/"cert"
            digest="ab"*32
            r.write_text("Signer #1 certificate SHA-256 digest: "+digest+"\n")
            expected.write_text(digest+"\n")
            verify_cert(r,expected)
            expected.write_text("cd"*32)
            with self.assertRaises(ValueError):
                verify_cert(r,expected)
            expected.unlink()
            with self.assertRaises(FileNotFoundError):
                verify_cert(r,expected)

    def test_signed_manifests(self):
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.serialization import NoEncryption
        with tempfile.TemporaryDirectory() as temp:
            temp=Path(temp); priv=temp/"key.pem";pub=temp/"pub.pem"
            key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
            priv.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,NoEncryption()))
            pub.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))
            path=temp/"update.json"
            path.write_bytes(canonical_json(dict(version_code=2,notes="Обновление")))
            sig=sign_file(path,priv)
            self.assertTrue(verify_file(path,sig,pub))
            path.write_bytes(canonical_json(dict(version_code=3,notes="Обновление")))
            self.assertFalse(verify_file(path,sig,pub))
            path.write_text('{"version_code":2,"notes":"Обновление"}')
            self.assertFalse(verify_file(path,sig,pub))
            sig.write_text(base64.b64encode(b"wrong").decode())
            self.assertFalse(verify_file(path,sig,pub))

if __name__=="__main__":
    unittest.main()
