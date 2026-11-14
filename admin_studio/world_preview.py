"""Read-only live chunk preview with fixed upstream, strict bounds and no mutations."""
import json
from urllib.request import Request, urlopen

CHUNK = 12
MAX_COORD = 10000
MAX_BODY = 128 * 1024

class Preview:
    def __init__(self, upstream="http://127.0.0.1:18767"):
        self.upstream = upstream.rstrip("/")

    def chunk(self, cx, cy):
        if type(cx) is not int or type(cy) is not int or abs(cx) > MAX_COORD or abs(cy) > MAX_COORD:
            raise ValueError("invalid_chunk")
        # URL is fixed by operator config; user input is numeric only.
        req = Request(self.upstream + "/chunk?cx=" + str(cx) + "&cy=" + str(cy),
                      headers={"Accept": "application/json"})
        with urlopen(req, timeout=3) as response:
            if response.status != 200:
                raise ValueError("upstream_error")
            body = response.read(MAX_BODY + 1)
            if len(body) > MAX_BODY:
                raise ValueError("upstream_too_large")
        data = json.loads(body)
        if not isinstance(data, dict) or not isinstance(data.get("cells"), list):
            raise ValueError("invalid_upstream")
        cells = []
        for item in data["cells"]:
            if not isinstance(item, dict):
                continue
            x, y = item.get("x"), item.get("y")
            if type(x) is not int or type(y) is not int:
                continue
            if not (cx * CHUNK <= x < (cx + 1) * CHUNK and cy * CHUNK <= y < (cy + 1) * CHUNK):
                continue
            cells.append({"x": x, "y": y, "kind": str(item.get("kind", ""))[:40],
                          "object_id": str(item.get("object_id", ""))[:64]})
        return {"cx": cx, "cy": cy, "version": data.get("version", 0),
                "cells": cells, "source": "read_only_upstream"}

    def collisions(self, city, cx, cy):
        snapshot = self.chunk(cx, cy)
        occupied = {(cell["x"], cell["y"]) for cell in snapshot["cells"]}
        conflicts = [b for b in city["buildings"] if any(
            (x, y) in occupied for x in range(b["x"], b["x"] + {"school":3,"hospital":3,"park":2}[b["kind"]])
            for y in range(b["y"], b["y"] + {"school":2,"hospital":3,"park":2}[b["kind"]])
            if x // CHUNK == cx and y // CHUNK == cy)]
        return {"chunk": snapshot, "conflicts": conflicts,
                "note": "Preview only. No guarantee against concurrent changes; authoritative server must revalidate."}
