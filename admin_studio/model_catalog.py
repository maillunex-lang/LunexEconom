"""Private World Studio GLB catalog. It does not publish unsigned models to players."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import tempfile

MAX_GLB = 8 * 1024 * 1024
MODEL_SPECS = {
    "house_panel_1x1.glb": ("house", 1, 1),
    "house_brick_1x1.glb": ("house", 1, 1),
    "house_modern_1x1.glb": ("house", 1, 1),
    "house_1x2.glb": ("house", 1, 2),
    "house_1x3.glb": ("house", 1, 3),
    "shop_2x2.glb": ("shop", 2, 2),
    "warehouse_3x3.glb": ("warehouse", 3, 3),
    "school_3x2.glb": ("school", 3, 2),
    "hospital_3x3.glb": ("hospital", 3, 3),
    "park_2x2.glb": ("park", 2, 2),
    "road_straight_1x1.glb": ("road_straight", 1, 1),
    "road_cross_1x1.glb": ("road_cross", 1, 1),
    "bridge_1x1.glb": ("bridge", 1, 1),
}


def validate_glb(data):
    if not isinstance(data, bytes) or not 20 <= len(data) <= MAX_GLB:
        raise ValueError("invalid_glb_size")
    if data[:4] != b"glTF" or struct.unpack_from("<II", data, 4) != (2, len(data)):
        raise ValueError("invalid_glb_header")
    offset = 12
    chunks = []
    while offset < len(data):
        if offset + 8 > len(data):
            raise ValueError("truncated_glb_chunk")
        length, kind = struct.unpack_from("<II", data, offset)
        offset += 8
        if length % 4 or offset + length > len(data):
            raise ValueError("invalid_glb_chunk")
        chunks.append((kind, data[offset:offset + length]))
        offset += length
    if len(chunks) not in (1, 2) or chunks[0][0] != 0x4E4F534A:
        raise ValueError("invalid_glb_chunks")
    if len(chunks) == 2 and chunks[1][0] != 0x004E4942:
        raise ValueError("invalid_glb_binary")
    try:
        doc = json.loads(chunks[0][1].rstrip(b" \t\r\n\x00").decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid_glb_json") from exc
    if not isinstance(doc, dict) or doc.get("asset", {}).get("version") != "2.0":
        raise ValueError("invalid_gltf_version")
    if doc.get("images") or doc.get("textures") or doc.get("extensionsRequired"):
        raise ValueError("external_textures_or_extensions_forbidden")
    if len(doc.get("materials", [])) > 1 or len(doc.get("nodes", [])) > 512:
        raise ValueError("model_complexity")
    buffers = doc.get("buffers", [])
    if len(buffers) > 1 or any("uri" in item for item in buffers):
        raise ValueError("external_buffers_forbidden")
    binary_len = len(chunks[1][1]) if len(chunks) == 2 else 0
    if buffers and (not binary_len or int(buffers[0].get("byteLength", 0)) > binary_len):
        raise ValueError("invalid_binary_length")
    if any(int(v.get("byteOffset", 0)) + int(v.get("byteLength", 0)) > binary_len
           for v in doc.get("bufferViews", [])):
        raise ValueError("invalid_bufferview")
    meshes = doc.get("meshes", [])
    if not meshes or not isinstance(meshes, list):
        raise ValueError("no_meshes")
    accessors = doc.get("accessors", [])
    tris = 0
    for mesh in meshes:
        for primitive in mesh.get("primitives", []):
            if primitive.get("mode", 4) != 4:
                raise ValueError("triangles_only")
            accessor = primitive.get("indices")
            if type(accessor) is not int or not 0 <= accessor < len(accessors):
                raise ValueError("missing_indices")
            count = int(accessors[accessor].get("count", 0))
            if count <= 0 or count % 3:
                raise ValueError("invalid_triangle_indices")
            tris += count // 3
            if tris > 3000:
                raise ValueError("triangle_limit")
    return {"triangles": tris, "materials": len(doc.get("materials", [])),
            "meshes": len(meshes)}


class ModelCatalog:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        (self.root / ".versions").mkdir(mode=0o700, exist_ok=True)

    @staticmethod
    def _atomic(path, content):
        fd, name = tempfile.mkstemp(prefix=".model-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as target:
                target.write(content)
                target.flush()
                os.fsync(target.fileno())
            os.chmod(name, 0o600)
            os.replace(name, path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def manifest(self):
        files = []
        for name, (kind, w, h) in MODEL_SPECS.items():
            file = self.root / name
            if not file.is_file():
                continue
            content = file.read_bytes()
            details = validate_glb(content)
            files.append({"name": name, "kind": kind, "width": w, "height": h,
                          "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest(),
                          **details})
        return {"schema": 1, "files": files}

    def upload(self, name, encoded):
        if type(name) is not str or name not in MODEL_SPECS:
            raise ValueError("unknown_model_name")
        if type(encoded) is not str or len(encoded) > ((MAX_GLB + 2) // 3 * 4):
            raise ValueError("invalid_glb_size")
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise ValueError("invalid_base64") from exc
        details = validate_glb(data)
        sha = hashlib.sha256(data).hexdigest()
        path = self.root / name
        if path.is_file():
            old = path.read_bytes()
            if hashlib.sha256(old).hexdigest() == sha:
                return {"name": name, "sha256": sha, "unchanged": True, **details}
            archived = self.root / ".versions" / (name + "." + hashlib.sha256(old).hexdigest())
            if not archived.exists():
                self._atomic(archived, old)
        self._atomic(path, data)
        self._atomic(self.root / "manifest.json",
                     json.dumps(self.manifest(), ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        return {"name": name, "sha256": sha, "unchanged": False, **details}
