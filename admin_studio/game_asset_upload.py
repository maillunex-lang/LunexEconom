"""Small allowlisted PNG publisher for LunexEconom Android asset cache."""
import base64
import hashlib
import json
import os
import re
import struct
import tempfile
from pathlib import Path

NAMES = (
    "grocery_1x1.png", "house_panel_a_1x1.png", "house_panel_b_1x1.png",
    "house_stalinka_2x1.png", "road_asphalt_1x1.png",
)
MAX_PNG = 8 * 1024 * 1024
PNG_SIG = b"\x89PNG\r\n\x1a\n"

class AssetPublisher:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / ".versions").mkdir(exist_ok=True)

    def manifest(self):
        files = []
        for name in NAMES:
            path = self.root / name
            if path.is_file():
                files.append({"name": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        return {"files": files}

    def publish(self, name, encoded):
        if name not in NAMES:
            raise ValueError("unknown_sprite_name")
        if not isinstance(encoded, str) or len(encoded) > (MAX_PNG * 4 // 3 + 16):
            raise ValueError("invalid_image_size")
        data = base64.b64decode(encoded, validate=True)
        if not (len(PNG_SIG) + 25 <= len(data) <= MAX_PNG and data.startswith(PNG_SIG)):
            raise ValueError("invalid_png")
        if data[12:16] != b"IHDR" or struct.unpack(">I", data[8:12])[0] != 13:
            raise ValueError("invalid_png_header")
        width, height = struct.unpack(">II", data[16:24])
        if not (1 <= width <= 4096 and 1 <= height <= 4096):
            raise ValueError("invalid_png_dimensions")
        # PNG decoder verification: Pillow is optional, but CRC and complete IEND are mandatory.
        import zlib
        cursor = 8
        saw_iend = False
        while cursor + 12 <= len(data):
            length = struct.unpack(">I", data[cursor:cursor+4])[0]
            if length > MAX_PNG or cursor + 12 + length > len(data):
                raise ValueError("invalid_png_chunk")
            chunk = data[cursor+4:cursor+8]
            end = cursor + 8 + length
            crc = struct.unpack(">I", data[end:end+4])[0]
            if zlib.crc32(data[cursor+4:end]) & 0xffffffff != crc:
                raise ValueError("invalid_png_crc")
            cursor = end + 4
            if chunk == b"IEND":
                saw_iend = True
                break
        if not saw_iend or cursor != len(data):
            raise ValueError("invalid_png_end")
        digest = hashlib.sha256(data).hexdigest()
        target = self.root / name
        if target.is_file():
            old = target.read_bytes()
            old_digest = hashlib.sha256(old).hexdigest()
            if old_digest == digest:
                return {"name": name, "sha256": digest, "width": width, "height": height, "unchanged": True}
            backup = self.root / ".versions" / (name + "." + old_digest)
            if not backup.exists():
                self._atomic(backup, old)
        self._atomic(target, data)
        self._atomic(self.root / "manifest.json", json.dumps(self.manifest(), ensure_ascii=False, separators=(",", ":")).encode())
        return {"name": name, "sha256": digest, "width": width, "height": height, "unchanged": False}

    @staticmethod
    def _atomic(target, data):
        fd, temp = tempfile.mkstemp(prefix=".asset-", dir=str(target.parent))
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, target)
            os.chmod(target, 0o644)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)