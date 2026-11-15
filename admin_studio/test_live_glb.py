"""Signed GLB uploads reject bogus headers and preserve bytes."""
import struct
import tempfile
import unittest
from livepatch import Store

class LiveGLBTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def test_valid_glb_header_and_strict_length(self):
        blob=b"glTF"+struct.pack("<II",2,20)+b"\0"*8
        result=self.store.add_asset("house_panel_1x1","housing","Дом","","glb",blob)
        self.assertEqual(result["size"],len(blob))
        with self.assertRaisesRegex(ValueError,"invalid_glb"):
            self.store.add_asset("badmodel","housing","Дом","","glb",blob+b"x")
        with self.assertRaisesRegex(ValueError,"invalid_glb"):
            self.store.add_asset("badmodel","housing","Дом","","glb",
                                 b"glTF"+struct.pack("<II",1,20)+b"\0"*8)

if __name__=="__main__":unittest.main()
