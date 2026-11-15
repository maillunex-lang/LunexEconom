"""V2-A4: no-key regression tests for the release plan and asset gate."""
import hashlib
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from alpha_release_plan import plan, alpha_tag, select_previous
from manifest_security import canonical_json


class AlphaReleasePlanTests(unittest.TestCase):
    def test_first_and_second_release_default_minimum(self):
        first = plan("0.1.0", "Первая альфа", [], [])
        self.assertEqual((first["version_tag"], first["version_code"], first["min_version_code"]), ("v0.1.0", 1000, 1))
        second = plan("0.1.5", "Исправлены ошибки", ["v0.1.3", "v0.1.2"], ["v0.1.3"])
        self.assertEqual((second["min_version_code"], second["previous_tag"]), (1003, "v0.1.3"))

    def test_explicit_minimum(self):
        self.assertEqual(plan("0.1.4", "Улучшения", ["v0.1.3"], ["v0.1.3"], "1004")["min_version_code"], 1004)
        for minimum in ("0", "-1", "1.0", "1005", "xyz"):
            with self.subTest(minimum=minimum), self.assertRaises(ValueError):
                plan("0.1.4", "Улучшения", ["v0.1.3"], ["v0.1.3"], minimum)

    def test_reject_reuse_or_lower_version(self):
        for tags in (["v0.1.3"], ["v0.1.7"]):
            with self.assertRaises(ValueError):
                plan("0.1.3", "Тестовый выпуск", tags, tags)
        with self.assertRaises(ValueError):
            plan("0.1.4", "Исправления", ["v0.1.3"], ["v0.1.5"])

    def test_reject_nonalpha_version_and_bad_notes(self):
        for version in ("0.2.1", "v0.1.1", "0.1.-1", "0.1.01", "0.1.1000", "0.1.3-beta"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                alpha_tag(version)
        for notes in ("", "Only English", "   ", "а" * 301):
            with self.subTest(notes=notes), self.assertRaises(ValueError):
                plan("0.1.1", notes, [], [])

    def test_ignore_nonalpha_tags(self):
        self.assertEqual(select_previous(["v1.0.0", "v1-archive", "v0.1.7"])[1], "v0.1.7")


if __name__ == "__main__":
    unittest.main()


class AlphaAssetGateTests(unittest.TestCase):
    def setUp(self):
        from cryptography.hazmat.primitives.asymmetric import rsa, padding
        from cryptography.hazmat.primitives import hashes, serialization
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.apk = d / "lunex.apk"
        self.aab = d / "lunex.aab"
        self.sums = d / "SHA256SUMS"
        self.badging = d / "badging.txt"
        self.cert = d / "cert.txt"
        self.expected = d / "expected.txt"
        self.manifest = d / "update.json"
        self.sig = d / "update.json.sig"
        self.public = d / "public.pem"
        self.apk.write_bytes(b"signed-test-apk-bytes")
        self.aab.write_bytes(b"signed-test-aab-bytes")
        self.refresh_hashes()
        self.badging.write_text("package: name='org.lunex.bashkiria.v2' versionCode='1004' versionName='0.1.4'\nnative-code: 'arm64-v8a'\n")
        self.cert.write_text("Signer #1 certificate SHA-256 digest: " + "ab" * 32 + "\n")
        self.expected.write_text("ab" * 32)
        body = {
            "version_code": 1004, "version_name": "0.1.4",
            "min_version_code": 1003, "size": self.apk.stat().st_size,
            "sha256": hashlib.sha256(self.apk.read_bytes()).hexdigest(),
            "apk_url": "https://rikagro.ru/lunexeconom/v2/download/lunex-0.1.4.apk",
            "notes": "Исправления игры", "released": "2026-11-16T00:00:00Z",
        }
        self.manifest.write_bytes(canonical_json(body))
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.public.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo))
        import base64
        self.sig.write_text(base64.b64encode(key.sign(self.manifest.read_bytes(),
            padding.PKCS1v15(), hashes.SHA256())).decode() + "\n")

    def tearDown(self):
        self.tmp.cleanup()

    def refresh_hashes(self):
        self.sums.write_text("".join(hashlib.sha256(file.read_bytes()).hexdigest() + "  build/" + file.name + "\n"
            for file in (self.apk, self.aab)))

    def verify(self):
        from verify_alpha_assets import verify_assets
        return verify_assets("v0.1.4", self.apk, self.aab, self.sums,
            self.badging, self.cert, self.expected, self.manifest,
            self.sig, self.public, 1003)

    def test_accept_complete_valid_artifacts(self):
        self.assertTrue(self.verify())

    def test_reject_tampered_apk(self):
        self.apk.write_bytes(b"modified apk")
        with self.assertRaisesRegex(ValueError, "hash"):
            self.verify()

    def test_reject_wrong_certificate(self):
        self.expected.write_text("cd" * 32)
        with self.assertRaises(ValueError):
            self.verify()

    def test_reject_wrong_abi(self):
        self.badging.write_text(self.badging.read_text().replace("'arm64-v8a'", "'armeabi-v7a'"))
        with self.assertRaisesRegex(ValueError, "arm64"):
            self.verify()

    def test_reject_tampered_manifest_and_wrong_minimum(self):
        payload = json.loads(self.manifest.read_bytes())
        payload["min_version_code"] = 1004
        self.manifest.write_bytes(canonical_json(payload))
        with self.assertRaises(ValueError):
            self.verify()

    def test_reject_missing_manifest_signature(self):
        self.sig.unlink()
        with self.assertRaisesRegex(ValueError, "signature"):
            self.verify()

    def test_reject_duplicate_checksum_entry(self):
        self.sums.write_text(self.sums.read_text() + self.sums.read_text().splitlines()[0] + "\n")
        with self.assertRaisesRegex(ValueError, "SHA256SUMS"):
            self.verify()


class OrchestratorWorkflowStructureTests(unittest.TestCase):
    def test_guards_and_reuse(self):
        repo = Path(__file__).resolve().parents[2]
        orchestration = (repo / ".github/workflows/android-alpha-release.yml").read_text()
        candidate = (repo / ".github/workflows/android-release.yml").read_text()
        self.assertIn("workflow_call:", candidate)
        self.assertIn("concurrency:", orchestration)
        self.assertIn("cancel-in-progress: false", orchestration)
        self.assertIn("environment: production", orchestration)
        self.assertIn("environment: ${{ needs.preflight.outputs.test_mode == 'true' && 'ci-test' || 'manifest-signing' }}", orchestration)
        self.assertIn("gh release create", orchestration)
        self.assertIn("--draft", orchestration)
        self.assertIn("gh release edit", orchestration)
        self.assertIn("needs: [preflight, candidate, manifest]", orchestration)
        self.assertIn("github.ref == 'refs/heads/main'", orchestration)
        self.assertNotIn("id-token: write", orchestration)
        self.assertNotIn("set -x", orchestration)