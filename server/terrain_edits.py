"""Server-side terrain override storage, isolated from procedural terrain.

Call ensure once at startup. Database queries are chunk-scoped, never per tile.
"""
import time

CHUNK = 12
KINDS = frozenset(("grass", "tree", "water", "clear"))
_cache = {}

def ensure(db):
    db.execute("CREATE TABLE IF NOT EXISTS terrain_edits (x INTEGER NOT NULL, y INTEGER NOT NULL, kind TEXT NOT NULL, editor TEXT NOT NULL, created BIGINT NOT NULL, manual INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(x,y))")

def chunk(db, ph, cx, cy):
    key = (db, int(cx), int(cy))
    # Global invalidation occurs on every successful write.
    if key not in _cache:
        x, y = int(cx) * CHUNK, int(cy) * CHUNK
        rows = db.execute("SELECT x,y,kind,manual FROM terrain_edits WHERE x >= " + ph + " AND x < " + ph + " AND y >= " + ph + " AND y < " + ph, (x, x + CHUNK, y, y + CHUNK)).fetchall()
        if len(_cache) >= 128:
            _cache.clear()
        _cache[key] = {(int(a), int(b)): {"kind": k, "manual": bool(m)} for a,b,k,m in rows}
    return dict(_cache[key])

def invalidate():
    _cache.clear()

def is_manual(db, ph, x, y):
    return (int(x), int(y)) in chunk(db, ph, int(x)//CHUNK, int(y)//CHUNK)

def apply(db, ph, cells, kind, editor="developer"):
    if kind not in KINDS:
        raise ValueError("invalid_kind")
    if not 1 <= len(cells) <= 25:
        raise ValueError("invalid_brush_size")
    unique = set()
    for x,y in cells:
        if type(x) is not int or type(y) is not int or abs(x) > 1000 or abs(y) > 1000:
            raise ValueError("invalid_coordinates")
        unique.add((x,y))
    if len(unique) != len(cells):
        raise ValueError("duplicate_cell")
    now = int(time.time())
    for x,y in unique:
        db.execute("INSERT INTO terrain_edits(x,y,kind,editor,created,manual) VALUES(" + ",".join([ph]*6) + ") ON CONFLICT(x,y) DO UPDATE SET kind=excluded.kind,editor=excluded.editor,created=excluded.created,manual=1", (x,y,kind,editor,now,1))
    db.commit()
    invalidate()
    return len(unique)