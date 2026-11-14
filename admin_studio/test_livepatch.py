import base64
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from livepatch import Store
from server import handler_factory

PNG = b"\x89PNG\r\n\x1a\n" + b"fake test bytes"
TOKEN = "a" * 40

class PatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), handler_factory(self.store, TOKEN))
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:" + str(self.http.server_port)

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, path, method="GET", data=None, auth=False):
        headers = {"Content-Type":"application/json"}
        if auth: headers["Authorization"] = "Bearer " + TOKEN
        req = Request(self.base+path, data=json.dumps(data).encode() if data is not None else None, method=method, headers=headers)
        try:
            with urlopen(req, timeout=4) as response:
                return response.status, response.read()
        except HTTPError as e:
            return e.code, e.read()

    def test_requires_admin(self):
        self.assertEqual(self.request("/api/assets")[0], 401)
        self.assertEqual(self.request("/api/publish", "POST", {})[0], 401)

    def test_asset_publish_and_blob(self):
        body = {"id":"farm_1","category":"agriculture","title":"Ферма","prompt":"isometric","extension":"png","data_base64":base64.b64encode(PNG).decode()}
        self.assertEqual(self.request("/api/assets", "POST", body, True)[0], 201)
        self.assertEqual(self.request("/patch/manifest.json")[0], 200)
        code, raw = self.request("/api/publish", "POST", {}, True)
        self.assertEqual(code, 200)
        m = json.loads(raw)
        self.assertEqual(m["revision"], 1)
        self.assertEqual(len(m["assets"]), 1)
        self.assertEqual(self.request("/patch/"+m["assets"][0]["url"])[1], PNG)
        self.assertEqual(json.loads(self.request("/patch/manifest.json")[1])["revision"], 1)
        self.assertEqual(len(json.loads(self.request("/api/audit", auth=True)[1])["audit"]), 2)

    def test_rejects_bad_inputs(self):
        with self.assertRaises(ValueError):
            self.store.add_asset("../bad", "agriculture", "Test", "", "png", PNG)
        with self.assertRaises(ValueError):
            self.store.add_asset("valid", "agriculture", "Test", "", "png", b"not an image")
        self.assertEqual(self.request("/patch/blobs/../../etc/passwd")[0], 404)

    def test_revision_snapshot(self):
        self.store.add_asset("farm_1", "agriculture", "A", "", "png", PNG)
        one = self.store.publish()
        self.store.add_asset("farm_1", "agriculture", "B", "", "png", PNG)
        two = self.store.publish()
        self.assertEqual(one["assets"][0]["title"], "A")
        self.assertEqual(two["assets"][0]["title"], "B")
        self.assertEqual(self.store.manifest(1), one)

if __name__ == "__main__":
    unittest.main()
