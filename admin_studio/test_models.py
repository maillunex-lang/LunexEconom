"""GLB catalog tests: parser, secure HTTP, SHA manifest and version retention."""
import base64
import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from livepatch import Store
from model_catalog import ModelCatalog, validate_glb
from server import handler_factory

TOKEN = "m" * 40
MODELS = Path(__file__).resolve().parents[1] / "client/world3d/models"


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.catalog = ModelCatalog(Path(self.temp.name) / "models")

    def tearDown(self):
        self.temp.cleanup()

    def blob(self, name):
        return (MODELS / name).read_bytes()

    def test_all_original_models_are_valid(self):
        names = [x.name for x in MODELS.glob("*.glb") if x.name.startswith(
            ("house_", "shop_", "warehouse_", "school_", "hospital_",
             "park_", "road_", "bridge_"))]
        self.assertEqual(len(names), 13)
        for name in names:
            with self.subTest(name=name):
                report = validate_glb(self.blob(name))
                self.assertGreater(report["triangles"], 0)
                self.assertLessEqual(report["triangles"], 3000)
                self.assertLessEqual(report["materials"], 1)

    def test_manifest_and_previous_version_retention(self):
        a = self.blob("house_panel_1x1.glb")
        b = self.blob("house_brick_1x1.glb")
        first = self.catalog.upload("house_panel_1x1.glb", base64.b64encode(a).decode())
        self.assertFalse(first["unchanged"])
        self.assertTrue(self.catalog.upload("house_panel_1x1.glb", base64.b64encode(a).decode())["unchanged"])
        self.catalog.upload("house_panel_1x1.glb", base64.b64encode(b).decode())
        manifest = self.catalog.manifest()
        self.assertEqual(len(manifest["files"]), 1)
        self.assertEqual(manifest["files"][0]["sha256"], __import__("hashlib").sha256(b).hexdigest())
        self.assertTrue((self.catalog.root / ".versions" / ("house_panel_1x1.glb." + first["sha256"])).is_file())
        self.assertEqual(json.loads((self.catalog.root / "manifest.json").read_text()), manifest)

    def test_rejects_invalid_inputs_and_external_resources(self):
        blob = self.blob("house_panel_1x1.glb")
        for name, encoded in (
            ("../secret.glb", base64.b64encode(blob).decode()),
            ("shop_2x2.glb", "not_base64!"),
            ("shop_2x2.glb", base64.b64encode(b"not a glb").decode()),
        ):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    self.catalog.upload(name, encoded)
        for bad in (b"bad!" + blob[4:], blob[:-1], blob[:8] + b"\0" * 4 + blob[12:]):
            with self.assertRaises(ValueError):
                validate_glb(bad)


class ModelHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), handler_factory(self.store, TOKEN))
        self.http.log_message = lambda *args: None
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.temp.cleanup()

    def request(self, method, path, body=None, token=TOKEN):
        c = http.client.HTTPConnection("127.0.0.1", self.http.server_address[1], timeout=5)
        h = {"Authorization": "Bearer " + token} if token else {}
        raw = json.dumps(body).encode() if body is not None else None
        if raw is not None:
            h["Content-Type"] = "application/json"
        c.request(method, path, body=raw, headers=h)
        r = c.getresponse()
        result = (r.status, json.loads(r.read()))
        c.close()
        return result

    def test_authorization_and_upload(self):
        self.assertEqual(self.request("GET", "/api/models", token="")[0], 401)
        self.assertEqual(self.request("GET", "/api/models")[1]["files"], [])
        data = (MODELS / "shop_2x2.glb").read_bytes()
        posted = self.request("POST", "/api/models",
                              {"name": "shop_2x2.glb", "data_base64": base64.b64encode(data).decode()})
        self.assertEqual(posted[0], 201, posted)
        files = self.request("GET", "/api/models")[1]["files"]
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0]["name"], "shop_2x2.glb")
        self.assertEqual(self.request("POST", "/api/models", {"name": "shop_2x2.glb",
                           "data_base64": base64.b64encode(b"wrong").decode()})[0], 400)
        self.assertEqual(len(self.request("GET", "/api/models")[1]["files"]), 1)


if __name__ == "__main__":
    unittest.main()
