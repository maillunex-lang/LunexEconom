"""Versioned art overrides. Never changes gameplay data or existing livepatch."""
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from game_asset_upload import AssetPublisher

CATEGORIES = {
    "roads": ("straight", "corner", "tee", "cross"),
    "housing": ("small", "panel_a", "panel_b", "apartment", "stalinka"),
    "retail": ("grocery", "supermarket", "hypermarket", "butcher", "fish", "bakery",
               "produce", "confectionery", "clothing", "shoes", "sports", "children",
               "jewelry", "electronics", "appliances", "car_dealer", "auto_parts",
               "motorcycle", "agro_machinery", "furniture", "building_materials",
               "plumbing", "hardware", "garden", "pharmacy", "books", "pet",
               "cosmetics", "outdoor", "food_wholesale", "building_wholesale",
               "fuel_wholesale", "agro_wholesale"),
    "industry": ("farm", "livestock", "grain_silo", "mine", "oil_well", "quarry",
                 "factory", "warehouse", "logistics", "research"),
    "municipal": ("school", "hospital", "park"),
}
ALLOWED = frozenset(f"{cat}.{name}" for cat, names in CATEGORIES.items() for name in names)
ASSET_ID = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")

class ArtCatalog:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "custom").mkdir(exist_ok=True)
        (self.root / "defaults").mkdir(exist_ok=True)
        (self.root / ".versions").mkdir(exist_ok=True)
        self.publisher = AssetPublisher(self.root / ".validation")

    def _read(self):
        path = self.root / "catalog.json"
        if not path.exists():
            return {"revision": 0, "items": {}}
        data = json.loads(path.read_text())
        if not isinstance(data, dict) or not isinstance(data.get("items"), dict):
            raise ValueError("invalid_catalog")
        return data

    def _save(self, data):
        fd, name = tempfile.mkstemp(prefix=".catalog-", dir=self.root)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(data, stream, ensure_ascii=False, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(name, 0o644)
            os.replace(name, self.root / "catalog.json")
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def view(self):
        data = self._read()
        return {"revision": data["revision"], "items": [
            {"id": ident, **data["items"].get(ident, {"mode": "default"})}
            for ident in sorted(ALLOWED)
        ]}

    def _validate_png(self, encoded):
        # Reuse the strict PNG parser without exposing the old five-sprite publisher.
        import base64
        import struct
        import zlib
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > 8 * 1024 * 1024 or not raw.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("invalid_png")
        if raw[12:16] != b"IHDR" or len(raw) < 45:
            raise ValueError("invalid_png_header")
        w, h = struct.unpack(">II", raw[16:24])
        if not (1 <= w <= 2048 and 1 <= h <= 2048):
            raise ValueError("invalid_dimensions")
        pos = 8
        ended = False
        while pos + 12 <= len(raw):
            size = struct.unpack(">I", raw[pos:pos+4])[0]
            if size > len(raw) or pos + size + 12 > len(raw):
                raise ValueError("invalid_chunk")
            end = pos + 8 + size
            if zlib.crc32(raw[pos+4:end]) & 0xffffffff != struct.unpack(">I", raw[end:end+4])[0]:
                raise ValueError("invalid_crc")
            typ = raw[pos+4:pos+8]
            pos = end + 4
            if typ == b"IEND":
                ended = True
                break
        if not ended or pos != len(raw):
            raise ValueError("invalid_png_end")
        return raw, w, h

    def upload(self, ident, encoded):
        if ident not in ALLOWED:
            raise ValueError("unknown_art_id")
        raw, w, h = self._validate_png(encoded)
        digest = hashlib.sha256(raw).hexdigest()
        path = self.root / "custom" / (digest + ".png")
        if not path.exists():
            AssetPublisher._atomic(path, raw)
        data = self._read()
        item = data["items"].setdefault(ident, {})
        item["custom_sha256"] = digest
        item["custom_width"] = w
        item["custom_height"] = h
        item["mode"] = "custom"
        data["revision"] += 1
        self._save(data)
        return {"id": ident, "revision": data["revision"], **item}

    def set_mode(self, ident, mode):
        if ident not in ALLOWED or mode not in ("default", "custom"):
            raise ValueError("invalid_selection")
        data = self._read()
        item = data["items"].setdefault(ident, {})
        if mode == "custom" and not item.get("custom_sha256"):
            raise ValueError("custom_missing")
        item["mode"] = mode
        data["revision"] += 1
        self._save(data)
        return {"id": ident, "revision": data["revision"], **item}