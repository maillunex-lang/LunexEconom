#!/usr/bin/env python3
"""Offline glTF 2.0 GLB validator; never executes asset content."""
import argparse
import json
import math
import re
import struct
from pathlib import Path

DIMENSIONS = re.compile(r"_(\d+)x(\d+)\.glb$")
COMPONENT_BYTES = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
TYPE_WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def validate(path, footprint=None):
    path = Path(path)
    errors = []
    try:
        raw = path.read_bytes()
        if len(raw) < 20 or raw[:4] != b"glTF":
            return ["not a GLB"]
        magic, version, length = struct.unpack_from("<4sII", raw)
        if version != 2 or length != len(raw):
            return ["invalid GLB version or length"]
        offset = 12
        chunks = []
        while offset < len(raw):
            if offset + 8 > len(raw):
                return ["truncated chunk header"]
            size, kind = struct.unpack_from("<I4s", raw, offset)
            offset += 8
            if size % 4 or offset + size > len(raw):
                return ["invalid chunk size"]
            chunks.append((kind, raw[offset:offset + size]))
            offset += size
        if not chunks or chunks[0][0] != b"JSON":
            return ["missing JSON chunk"]
        doc = json.loads(chunks[0][1].decode("utf-8").rstrip(" \t\r\n\0"))
        if doc.get("asset", {}).get("version") != "2.0":
            errors.append("asset version is not 2.0")
        if len(chunks) > 2 or any(k != b"BIN\0" for k, _ in chunks[1:]):
            errors.append("unexpected GLB chunks")
        binary = chunks[1][1] if len(chunks) > 1 else b""
        buffers = doc.get("buffers", [])
        if len(buffers) != 1 or any(b.get("uri") for b in buffers):
            errors.append("external or multiple buffers")
        if buffers and buffers[0].get("byteLength", 0) > len(binary):
            errors.append("binary buffer truncated")
        if doc.get("images") or doc.get("textures"):
            errors.append("images or textures are not allowed")
        if len(doc.get("materials", [])) != 1:
            errors.append("expected exactly one material")
        meshes = doc.get("meshes", [])
        if not meshes:
            errors.append("no meshes")
        accessors = doc.get("accessors", [])
        views = doc.get("bufferViews", [])

        def accessor_data(index):
            acc = accessors[index]
            view = views[acc["bufferView"]]
            count = acc["count"]
            n = TYPE_WIDTH[acc["type"]]
            comp = acc["componentType"]
            stride = view.get("byteStride", n * COMPONENT_BYTES[comp])
            start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
            end = start + (count - 1) * stride + n * COMPONENT_BYTES[comp]
            if count < 1 or end > view.get("byteOffset", 0) + view["byteLength"] or end > len(binary):
                raise ValueError("accessor out of bounds")
            return acc, view, start, stride

        triangles = 0
        bounds = []
        for mesh in meshes:
            for primitive in mesh.get("primitives", []):
                attrs = primitive.get("attributes", {})
                if primitive.get("mode", 4) != 4:
                    errors.append("primitive is not triangles")
                if primitive.get("material") != 0:
                    errors.append("primitive uses unexpected material")
                if "POSITION" not in attrs or "COLOR_0" not in attrs or "NORMAL" not in attrs:
                    errors.append("POSITION/COLOR_0/NORMAL missing")
                    continue
                pos = accessors[attrs["POSITION"]]
                count = pos.get("count", 0)
                if count == 0:
                    errors.append("empty mesh")
                    continue
                triangles += (accessors[primitive["indices"]]["count"] if "indices" in primitive else count) // 3
                if "indices" in primitive and accessors[primitive["indices"]]["count"] % 3:
                    errors.append("index count not divisible by three")
                if "indices" not in primitive and count % 3:
                    errors.append("vertex count not divisible by three")
                if pos.get("min") is not None and pos.get("max") is not None:
                    bounds.append((pos["min"], pos["max"]))
                else:
                    errors.append("POSITION min/max absent")
                norm, _, start, stride = accessor_data(attrs["NORMAL"])
                if norm["componentType"] != 5126 or norm["type"] != "VEC3":
                    errors.append("unsupported normal format")
                else:
                    for i in range(norm["count"]):
                        x, y, z = struct.unpack_from("<fff", binary, start + i * stride)
                        if not all(math.isfinite(v) for v in (x, y, z)) or x*x+y*y+z*z < 1e-12:
                            errors.append("zero or invalid normal")
                            break
                accessor_data(attrs["COLOR_0"])
                accessor_data(attrs["POSITION"])
        limit = 400 if path.name.startswith(("vehicle_", "pedestrian_")) else (6000 if path.stem.startswith(("quarter", "complex_modern", "block_12", "block_16")) else 3000)
        if triangles > limit:
            errors.append(f"triangle budget exceeded: {triangles}/{limit}")
        if triangles == 0:
            errors.append("no triangles")
        match = DIMENSIONS.search(path.name)
        size = footprint or ((int(match[1]), int(match[2])) if match else None)
        if bounds:
            low = [min(b[0][i] for b in bounds) for i in range(3)]
            high = [max(b[1][i] for b in bounds) for i in range(3)]
            if abs(low[1]) > 0.001:
                errors.append(f"minY is {low[1]:.3f}, expected 0")
            if size and (low[0] < -size[0]*1.05 or high[0] > size[0]*1.05 or low[2] < -size[1]*1.05 or high[2] > size[1]*1.05):
                errors.append("outside tile footprint")
        return errors
    except (OSError, ValueError, KeyError, IndexError, TypeError, struct.error, UnicodeError) as exc:
        return [f"malformed GLB: {exc}"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", nargs="?", default="client/world3d/models")
    args = parser.parse_args()
    files = sorted(Path(args.directory).glob("*.glb"))
    if not files:
        print("FAIL: no GLB files")
        return 1
    failures = 0
    for file in files:
        issues = validate(file)
        failures += bool(issues)
        print(f"{file.name:44} {'PASS' if not issues else 'FAIL'} {'; '.join(issues)}")
    print(f"Checked {len(files)} GLB, failed {failures}")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
