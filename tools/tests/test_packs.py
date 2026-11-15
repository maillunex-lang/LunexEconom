import base64
import json
import subprocess
import os
import sys
import tempfile
import zlib
import struct
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from build_packs import build
from manifest_security import sha256

GODOT = os.environ.get("GODOT", "/opt/game-tools/godot/4.7.2-stable/Godot_v4.7.2-stable_linux.x86_64")
def png_chunk(name,payload):
    return struct.pack(">I",len(payload))+name+payload+struct.pack(">I",zlib.crc32(name+payload)&0xffffffff)
PNG = (b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", struct.pack(">2I5B",1,1,8,2,0,0,0)) + png_chunk(b"IDAT", zlib.compress(b"\0\xff\0\0")) + png_chunk(b"IEND",b""))


class PackTests(unittest.TestCase):
    def test_pack_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/"assets"; (source/"core_start").mkdir(parents=True)
            (source/"core_start"/"icon.png").write_bytes(PNG)
            a=build(source,root/"a","1.0.0","https://rikagro.ru/lunexeconom",GODOT)
            b=build(source,root/"b","1.0.0","https://rikagro.ru/lunexeconom",GODOT)
            self.assertEqual(a,b)
            self.assertEqual(sha256(root/"a/core_start-1.0.0.pck"),sha256(root/"b/core_start-1.0.0.pck"))
            self.assertTrue((root/"a/content.json").is_file())
            done=subprocess.run([GODOT, "--headless", "--path", str(Path(__file__).resolve().parents[2]/"client"), "-s", "tests/pack_smoke.gd", "--", str(root/"a/core_start-1.0.0.pck")],capture_output=True,text=True,timeout=25)
            self.assertEqual(done.returncode,0,done.stdout+done.stderr)
            self.assertIn("runtime content pack mounted",done.stdout)

if __name__=="__main__":
    unittest.main()
