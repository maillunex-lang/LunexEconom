import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from make_update_manifest import make
from check_apk_size import check

class ManifestBuilderTests(unittest.TestCase):
    def test_manifest_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"lunex.apk";path.write_bytes(b"some apk bytes")
            m=make(path,"v2.0.1",1,"Исправления","https://rikagro.ru/lunexeconom")
            self.assertEqual(m["version_code"],2000001)
            self.assertEqual(m["apk_url"],"https://rikagro.ru/lunexeconom/download/lunex.apk")
            self.assertEqual(m["size"],14)
            self.assertEqual(len(m["sha256"]),64)
            with self.assertRaises(ValueError):
                make(path,"v2.0.1",2000002,"","https://rikagro.ru/lunexeconom")
    def test_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"apk";path.write_bytes(b"x"*4)
            self.assertEqual(check(path,4),4)
            with self.assertRaises(ValueError):
                check(path,3)
