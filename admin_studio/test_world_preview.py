import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from livepatch import Store
from world_editor import WorldDrafts, DEFAULTS
from world_preview import Preview

class Stub(BaseHTTPRequestHandler):
    def do_GET(self):
        data = {"cx":0,"cy":0,"version":7,"cells":[
            {"x":2,"y":4,"kind":"building_created","object_id":"existing"},
            {"x":999,"y":999,"kind":"invalid","object_id":"outside"}]}
        payload = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Length",str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
    def log_message(self, *_): pass

class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1",0),Stub)
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.preview = Preview("http://127.0.0.1:"+str(self.server.server_port))
        self.tmp = tempfile.TemporaryDirectory()
        self.world = WorldDrafts(Store(self.tmp.name))
        self.world.save_city("ufa","Уфа",dict(DEFAULTS))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def test_read_only_chunk_and_conflicts(self):
        self.assertEqual(self.preview.chunk(0,0)["version"],7)
        self.assertEqual(len(self.preview.chunk(0,0)["cells"]),1)
        self.world.place("ufa","school",1,3)
        self.assertEqual(len(self.preview.collisions(self.world.city("ufa"),0,0)["conflicts"]),1)

    def test_invalid_coordinates(self):
        for args in [(10001,0),(True,0),("0",0)]:
            with self.assertRaises(ValueError):
                self.preview.chunk(*args)

if __name__=="__main__":
    unittest.main()
