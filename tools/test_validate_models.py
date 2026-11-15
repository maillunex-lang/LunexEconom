"""Offline GLB validator regression tests, including deliberately malformed files."""
import json
import struct
import tempfile
import unittest
from pathlib import Path

from validate_models import validate


def glb(document, binary=b""):
    data = json.dumps(document).encode()
    data += b" " * (-len(data) % 4)
    chunks = struct.pack("<I4s", len(data), b"JSON") + data
    if binary:
        binary += b"\0" * (-len(binary) % 4)
        chunks += struct.pack("<I4s", len(binary), b"BIN\0") + binary
    return struct.pack("<4sII", b"glTF", 2, 12 + len(chunks)) + chunks


class ModelValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "test_1x1.glb"

    def test_bad_magic(self):
        self.path.write_bytes(b"invalid")
        self.assertIn("not a GLB", validate(self.path))

    def test_external_buffer_rejected(self):
        self.path.write_bytes(glb({"asset": {"version": "2.0"}, "buffers": [{"uri": "external.bin", "byteLength": 12}]}))
        self.assertTrue(any("external" in e for e in validate(self.path)))

    def test_textures_rejected(self):
        self.path.write_bytes(glb({"asset": {"version": "2.0"}, "images": [{"uri": "x.png"}]}))
        self.assertTrue(any("textures" in e for e in validate(self.path)))

    def test_truncated_chunk(self):
        self.path.write_bytes(glb({"asset": {"version": "2.0"}})[:-1])
        self.assertTrue(validate(self.path))

    def test_valid_minimal_triangle(self):
        # POSITION, NORMAL and COLOR_0, all float VEC3.
        pos = struct.pack("<9f", -0.5, 0, -0.5, 0.5, 0, -0.5, 0, 0, 0.5)
        normals = struct.pack("<9f", *(v for _ in range(3) for v in (0, 1, 0)))
        colors = struct.pack("<9f", *(v for _ in range(3) for v in (1, 0, 0)))
        doc = {"asset": {"version": "2.0"}, "buffers": [{"byteLength": 108}],
               "bufferViews": [{"buffer": 0, "byteOffset": i*36, "byteLength": 36} for i in range(3)],
               "accessors": [{"bufferView": i, "componentType": 5126, "count": 3, "type": "VEC3",
                              **({"min": [-0.5, 0, -0.5], "max": [0.5, 0, 0.5]} if i == 0 else {})} for i in range(3)],
               "materials": [{}],
               "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1, "COLOR_0": 2}, "material": 0}]}]}
        self.path.write_bytes(glb(doc, pos + normals + colors))
        self.assertEqual([], validate(self.path))


if __name__ == "__main__":
    unittest.main()
