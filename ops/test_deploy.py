import tempfile
import unittest
from pathlib import Path
from deploy import check_web, publish_update_manifest
from unittest.mock import patch
import json

class DeployChecks(unittest.TestCase):
    def test_missing_markers_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            for name in ("index.html","style.css","app.js"):
                (p/name).write_text("x",encoding="utf-8")
            with self.assertRaises(ValueError):
                check_web(p)

class UpdateManifestTests(unittest.TestCase):
    def sample(self, code=42, channel="release"):
        return {"status": "published", "channel": channel, "version_code": code,
                "version_name": "0.3.42", "size": 123456,
                "sha256": "a" * 64,
                "url": "https://rikagro.ru/lunexeconom/versions/LunexEconom-release.apk"}

    def test_publish_and_schema(self):
        with tempfile.TemporaryDirectory() as d, patch("deploy.BASE", Path(d)):
            self.assertTrue(publish_update_manifest(self.sample()))
            data=json.loads((Path(d)/"updates/manifest.json").read_text())
            self.assertEqual(data["schema"], 1)
            self.assertEqual(data["apk"]["version_code"], 42)
            self.assertEqual(data["apk"]["size"], 123456)

    def test_debug_does_not_replace_manifest(self):
        with tempfile.TemporaryDirectory() as d, patch("deploy.BASE", Path(d)):
            self.assertFalse(publish_update_manifest(self.sample(channel="debug")))
            self.assertFalse((Path(d)/"updates/manifest.json").exists())

    def test_rollback_rejected(self):
        with tempfile.TemporaryDirectory() as d, patch("deploy.BASE", Path(d)):
            publish_update_manifest(self.sample(42))
            before=(Path(d)/"updates/manifest.json").read_bytes()
            with self.assertRaises(ValueError): publish_update_manifest(self.sample(41))
            self.assertEqual((Path(d)/"updates/manifest.json").read_bytes(), before)

    def test_invalid_external_url_rejected(self):
        with tempfile.TemporaryDirectory() as d, patch("deploy.BASE", Path(d)):
            data=self.sample();data["url"]="https://evil.example/release.apk"
            with self.assertRaises(ValueError): publish_update_manifest(data)

    def test_conflicting_same_version_rejected(self):
        with tempfile.TemporaryDirectory() as d, patch("deploy.BASE", Path(d)):
            publish_update_manifest(self.sample())
            data=self.sample();data["sha256"]="b"*64
            with self.assertRaises(ValueError): publish_update_manifest(data)

if __name__=="__main__":
    unittest.main()
