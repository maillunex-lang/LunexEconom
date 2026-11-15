"""Signed GLB uploads reject bogus headers and preserve bytes."""
import struct
import tempfile
import unittest
from livepatch import Store, validate_glb

class LiveGLBTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def test_valid_glb_header_and_strict_length(self):
        import json
        chunk=json.dumps({"asset":{"version":"2.0"},"scenes":[{}],"scene":0},separators=(",", ":")).encode()
        chunk+=b" "*(-len(chunk)%4)
        blob=b"glTF"+struct.pack("<II",2,20+len(chunk))+struct.pack("<I4s",len(chunk),b"JSON")+chunk
        self.assertTrue(validate_glb(blob))
        result=self.store.add_asset("house_panel_1x1","housing","Дом","","glb",blob)
        self.assertEqual(result["size"],len(blob))
        with self.assertRaisesRegex(ValueError,"invalid_glb"):
            self.store.add_asset("badmodel","housing","Дом","","glb",blob+b"x")
        with self.assertRaisesRegex(ValueError,"invalid_glb"):
            self.store.add_asset("badmodel","housing","Дом","","glb",
                                 b"glTF"+struct.pack("<II",1,len(blob))+blob[12:])
        bad=json.dumps({"asset":{"version":"2.0"},"buffers":[{"uri":"../../private"}]}).encode()
        bad+=b" "*(-len(bad)%4)
        dangerous=b"glTF"+struct.pack("<II",2,20+len(bad))+struct.pack("<I4s",len(bad),b"JSON")+bad
        with self.assertRaisesRegex(ValueError,"invalid_glb_external_uri"):
            self.store.add_asset("malicious","housing","Дом","","glb",dangerous)

if __name__=="__main__":unittest.main()
