"""Developer-only API primitives. Never trust client-supplied role or owner."""
import json
import time
import uuid
import accounts_admin
import admin_api
import terrain_edits

def ensure(db, ph, postgres=False):
    terrain_edits.ensure(db)
    accounts_admin.ensure(db)
    db.execute("CREATE TABLE IF NOT EXISTS dev_actions (id TEXT PRIMARY KEY, actor TEXT NOT NULL, action TEXT NOT NULL, payload_json TEXT NOT NULL, inverse_json TEXT NOT NULL, created BIGINT NOT NULL, undone INTEGER NOT NULL DEFAULT 0)")
    db.commit()

def require_developer(owner, db):
    # Auth identities and world cells may live in separate SQLite databases.
    return bool(owner) and accounts_admin.is_developer(owner)

def terrain_chunk(db, ph, owner, cx, cy):
    if not owner:
        return 401, {"error": "unauthorized"}
    if type(cx) is not int or type(cy) is not int or abs(cx)>834 or abs(cy)>834:
        return 400, {"error": "invalid_query"}
    return 200, {"cx":cx,"cy":cy,"edits":[{"x":x,"y":y,**entry} for (x,y),entry in terrain_edits.chunk(db,ph,cx,cy).items()]}

def publish_terrain_events(db, ph, coords):
    """Publish per-chunk versioned events through the existing world event stream."""
    chunks = {}
    for x, y in coords:
        chunks.setdefault((x // 12, y // 12), []).append([x, y])
    for (cx, cy), cells in chunks.items():
        db.execute("INSERT INTO chunks(cx,cy,version) VALUES(" + ",".join([ph]*3) + ") ON CONFLICT(cx,cy) DO UPDATE SET version=chunks.version+1", (cx, cy, 1))
        version = db.execute("SELECT version FROM chunks WHERE cx=" + ph + " AND cy=" + ph, (cx, cy)).fetchone()[0]
        payload = json.dumps({"cells": cells, "kind": "terrain_changed"})
        db.execute("INSERT INTO events(cx,cy,version,kind,payload) VALUES(" + ",".join([ph]*5) + ")", (cx, cy, version, "terrain_changed", payload))


def terrain_set(db, ph, owner, payload, ip):
    if not require_developer(owner,db):
        return 403, {"error": "forbidden"}
    if not isinstance(payload,dict):
        return 400, {"error": "invalid_body"}
    request_id=payload.get("request_id")
    try:
        request_id=str(uuid.UUID(request_id))
    except (TypeError, ValueError, AttributeError):
        return 400, {"error":"invalid_request_id"}
    cells=payload.get("cells")
    kind=payload.get("kind")
    if not isinstance(cells,list) or not 1<=len(cells)<=25 or kind not in terrain_edits.KINDS:
        return 400, {"error":"invalid_brush"}
    coords=[]
    for cell in cells:
        if not isinstance(cell,(list,tuple)) or len(cell)!=2 or any(type(v) is not int or abs(v)>1000 for v in cell):
            return 400, {"error":"invalid_coordinates"}
        coords.append(tuple(cell))
    import roads
    if any(roads.is_base_road(x,y) for x,y in coords):
        return 409, {"error": "base_road_overlap"}
    if len(set(coords))!=len(coords):
        return 400, {"error":"duplicate_cell"}
    existing=db.execute("SELECT payload_json FROM dev_actions WHERE id="+ph,(request_id,)).fetchone()
    if existing:
        old=json.loads(existing[0])
        return (200,{"request_id":request_id,"replayed":True}) if old==payload else (409,{"error":"request_id_conflict"})
    now=int(time.time())
    action_time=time.time_ns()
    count=db.execute("SELECT COUNT(*) FROM dev_actions WHERE actor="+ph+" AND created>="+ph,(owner,action_time-60_000_000_000)).fetchone()[0]
    if count>=30:
        return 429,{"error":"rate_limited"}
    previous={}
    for x,y in coords:
        if db.execute("SELECT 1 FROM cells WHERE x="+ph+" AND y="+ph,(x,y)).fetchone():
            return 409, {"error": "occupied"}
        if db.execute("SELECT 1 FROM roads WHERE x="+ph+" AND y="+ph,(x,y)).fetchone():
            return 409, {"error": "road_overlap"}
    for x,y in coords:
        row=db.execute("SELECT kind,editor,created,manual FROM terrain_edits WHERE x="+ph+" AND y="+ph,(x,y)).fetchone()
        previous[f"{x},{y}"]=list(row) if row else None
    # Transaction ownership stays with caller; no commit before the audit record.
    for x,y in coords:
        db.execute("INSERT INTO terrain_edits(x,y,kind,editor,created,manual) VALUES("+",".join([ph]*6)+") ON CONFLICT(x,y) DO UPDATE SET kind=excluded.kind,editor=excluded.editor,created=excluded.created,manual=1",(x,y,kind,owner,now,1))
    db.execute("INSERT INTO dev_actions(id,actor,action,payload_json,inverse_json,created,undone) VALUES("+",".join([ph]*7)+")",(request_id,owner,"terrain",json.dumps(payload,ensure_ascii=False),json.dumps(previous),action_time,0))
    publish_terrain_events(db, ph, coords)
    admin_api.audit(db,ph,owner,"dev_terrain",str(coords[0]),f"cells={len(coords)} kind={kind}",ip,now)
    db.commit()
    terrain_edits.invalidate()
    return 200,{"request_id":request_id,"changed":len(coords)}
def undo(db, ph, owner, payload, ip):
    """Undo the most recent not-yet-undone terrain action of this actor."""
    if not require_developer(owner, db):
        return 403, {"error": "forbidden"}
    if not isinstance(payload, dict):
        return 400, {"error": "invalid_body"}
    try:
        request_id = str(uuid.UUID(payload.get("request_id")))
    except (ValueError, TypeError, AttributeError):
        return 400, {"error": "invalid_request_id"}
    previous = db.execute("SELECT action,actor FROM dev_actions WHERE id=" + ph, (request_id,)).fetchone()
    if previous:
        if previous == ("undo", owner):
            return 200, {"request_id": request_id, "replayed": True}
        return 409, {"error": "request_id_conflict"}
    now = int(time.time())
    action_time = time.time_ns()
    recent = db.execute("SELECT COUNT(*) FROM dev_actions WHERE actor=" + ph + " AND created>=" + ph, (owner, action_time - 60_000_000_000)).fetchone()[0]
    if recent >= 30:
        return 429, {"error": "rate_limited"}
    row = db.execute("SELECT id,action,inverse_json,payload_json FROM dev_actions WHERE actor=" + ph + " AND action IN ('terrain','roads','move') AND undone=0 ORDER BY created DESC,id DESC LIMIT 1", (owner,)).fetchone()
    if not row:
        return 409, {"error": "nothing_to_undo"}
    action_id, action_kind, inverse, original_payload = row
    original = json.loads(original_payload)
    snapshot = json.loads(inverse)
    if action_kind == "move":
        oid = snapshot.get("object_id")
        current = db.execute("SELECT x,y FROM buildings WHERE id=" + ph, (oid,)).fetchone()
        if current != (original["x"], original["y"]):
            return 409, {"error": "undo_conflict"}
        inverse_payload = {"request_id": request_id, "object_id": oid, "x": snapshot["x"], "y": snapshot["y"]}
        # Reuse the same validated move path, but record the reversal as an
        # undo and mark the original action undone atomically.
        result = building_move(db, ph, owner, inverse_payload, ip)
        if result[0] != 200:
            return result
        db.execute("UPDATE dev_actions SET action='undo' WHERE id=" + ph, (request_id,))
        db.execute("UPDATE dev_actions SET undone=1 WHERE id=" + ph, (action_id,))
        db.commit()
        return 200, {"request_id": request_id, "undone": action_id, "changed": result[1]["moved"]}
    if len(snapshot) > 25:
        return 409, {"error": "invalid_history"}
    # Reject stale undo: another operator may have modified the same cells.
    # A failed undo must not erase their newer work.
    for coordinate in snapshot:
        x, y = map(int, coordinate.split(","))
        if action_kind == "terrain":
            current = db.execute("SELECT kind,editor FROM terrain_edits WHERE x=" + ph + " AND y=" + ph, (x, y)).fetchone()
            if current != (original["kind"], owner):
                return 409, {"error": "undo_conflict", "cell": [x, y]}
        elif action_kind == "roads":
            current = db.execute("SELECT owner FROM roads WHERE x=" + ph + " AND y=" + ph, (x, y)).fetchone()
            old = snapshot[coordinate]
            if original["operation"] == "add" and (current is None or old is None and current[0] != owner):
                return 409, {"error": "undo_conflict", "cell": [x, y]}
            if original["operation"] == "remove" and current is not None:
                return 409, {"error": "undo_conflict", "cell": [x, y]}
    for coordinate, state in snapshot.items():
        x, y = map(int, coordinate.split(","))
        if action_kind == "roads":
            if state is None:
                db.execute("DELETE FROM roads WHERE x=" + ph + " AND y=" + ph, (x, y))
            else:
                db.execute("INSERT INTO roads(x,y,owner,created) VALUES(" + ",".join([ph]*4) + ") ON CONFLICT(x,y) DO UPDATE SET owner=excluded.owner,created=excluded.created", (x, y, *state))
        elif state is None:
            db.execute("DELETE FROM terrain_edits WHERE x=" + ph + " AND y=" + ph, (x, y))
        else:
            db.execute("INSERT INTO terrain_edits(x,y,kind,editor,created,manual) VALUES(" + ",".join([ph]*6) + ") ON CONFLICT(x,y) DO UPDATE SET kind=excluded.kind,editor=excluded.editor,created=excluded.created,manual=excluded.manual", (x, y, *state))
    db.execute("UPDATE dev_actions SET undone=1 WHERE id=" + ph + " AND actor=" + ph, (action_id, owner))
    db.execute("INSERT INTO dev_actions(id,actor,action,payload_json,inverse_json,created,undone) VALUES(" + ",".join([ph]*7) + ")", (request_id, owner, "undo", json.dumps(payload), inverse, action_time, 0))
    publish_terrain_events(db, ph, [tuple(map(int, c.split(","))) for c in snapshot])
    admin_api.audit(db, ph, owner, "dev_undo", action_id, f"cells={len(snapshot)}", ip, now)
    db.commit()
    terrain_edits.invalidate()
    return 200, {"request_id": request_id, "undone": action_id, "changed": len(snapshot)}
def roads_set(db, ph, owner, payload, ip):
    """Paint or remove dynamic roads without touching any economic balances."""
    if not require_developer(owner, db):
        return 403, {"error": "forbidden"}
    if not isinstance(payload, dict):
        return 400, {"error": "invalid_body"}
    try:
        request_id = str(uuid.UUID(payload.get("request_id")))
    except (TypeError, ValueError, AttributeError):
        return 400, {"error": "invalid_request_id"}
    cells = payload.get("cells")
    operation = payload.get("operation")
    if operation not in ("add", "remove") or not isinstance(cells, list) or not 1 <= len(cells) <= 25:
        return 400, {"error": "invalid_road_action"}
    coords = []
    for cell in cells:
        if not isinstance(cell, list) or len(cell) != 2 or any(type(v) is not int or abs(v) > 1000 for v in cell):
            return 400, {"error": "invalid_coordinates"}
        coords.append(tuple(cell))
    if len(set(coords)) != len(coords):
        return 400, {"error": "duplicate_cell"}
    previous = db.execute("SELECT action,actor,payload_json FROM dev_actions WHERE id=" + ph, (request_id,)).fetchone()
    if previous:
        return (200, {"request_id": request_id, "replayed": True}) if previous == ("roads", owner, json.dumps(payload, ensure_ascii=False)) else (409, {"error": "request_id_conflict"})
    now = int(time.time())
    action_time = time.time_ns()
    recent = db.execute("SELECT COUNT(*) FROM dev_actions WHERE actor=" + ph + " AND created>=" + ph, (owner, action_time - 60_000_000_000)).fetchone()[0]
    if recent >= 30:
        return 429, {"error": "rate_limited"}
    import roads
    old = {}
    for x, y in coords:
        if roads.is_base_road(x, y):
            return 409, {"error": "base_road"}
        if db.execute("SELECT 1 FROM cells WHERE x=" + ph + " AND y=" + ph, (x, y)).fetchone():
            return 409, {"error": "occupied"}
        if operation == "add" and (roads.is_water(x, y) or db.execute("SELECT kind FROM terrain_edits WHERE x=" + ph + " AND y=" + ph, (x, y)).fetchone() == ("water",)):
            return 409, {"error": "water"}
        row = db.execute("SELECT owner,created FROM roads WHERE x=" + ph + " AND y=" + ph, (x, y)).fetchone()
        old[f"{x},{y}"] = list(row) if row else None
    for x, y in coords:
        if operation == "add":
            db.execute("INSERT INTO roads(x,y,owner,created) VALUES(" + ",".join([ph]*4) + ") ON CONFLICT(x,y) DO NOTHING", (x, y, owner, now))
        else:
            db.execute("DELETE FROM roads WHERE x=" + ph + " AND y=" + ph, (x, y))
    db.execute("INSERT INTO dev_actions(id,actor,action,payload_json,inverse_json,created,undone) VALUES(" + ",".join([ph]*7) + ")", (request_id, owner, "roads", json.dumps(payload, ensure_ascii=False), json.dumps(old), action_time, 0))
    publish_terrain_events(db, ph, coords)
    admin_api.audit(db, ph, owner, "dev_roads", str(coords[0]), f"cells={len(coords)} operation={operation}", ip, now)
    db.commit()
    return 200, {"request_id": request_id, "changed": len(coords)}
def building_move(db, ph, owner, payload, ip):
    """Move an existing building's geometry without changing its economic owner."""
    if not require_developer(owner, db):
        return 403, {"error": "forbidden"}
    if not isinstance(payload, dict):
        return 400, {"error": "invalid_body"}
    try:
        request_id = str(uuid.UUID(payload.get("request_id")))
    except (TypeError, ValueError, AttributeError):
        return 400, {"error": "invalid_request_id"}
    oid, x, y = payload.get("object_id"), payload.get("x"), payload.get("y")
    if not isinstance(oid, str) or not 1 <= len(oid) <= 100 or type(x) is not int or type(y) is not int or abs(x) > 1000 or abs(y) > 1000:
        return 400, {"error": "invalid_move"}
    previous = db.execute("SELECT actor,action,payload_json FROM dev_actions WHERE id=" + ph, (request_id,)).fetchone()
    if previous:
        return (200, {"request_id": request_id, "replayed": True}) if previous == (owner, "move", json.dumps(payload, ensure_ascii=False)) else (409, {"error": "request_id_conflict"})
    now = int(time.time())
    action_time = time.time_ns()
    count = db.execute("SELECT COUNT(*) FROM dev_actions WHERE actor=" + ph + " AND created>=" + ph, (owner, action_time - 60_000_000_000)).fetchone()[0]
    if count >= 30:
        return 429, {"error": "rate_limited"}
    row = db.execute("SELECT owner,kind,x,y FROM buildings WHERE id=" + ph, (oid,)).fetchone()
    if not row:
        return 404, {"error": "building_not_found"}
    building_owner, kind, old_x, old_y = row
    if (x, y) == (old_x, old_y):
        return 409, {"error": "same_position"}
    # Deposits are georeferenced. Moving an extraction operation would violate
    # resource ownership; do not silently detach it.
    linked = db.execute("SELECT 1 FROM building_deposits WHERE object_id=" + ph, (oid,)).fetchone()
    if linked:
        return 409, {"error": "deposit_bound"}
    old_cells = [tuple(r) for r in db.execute("SELECT x,y FROM cells WHERE object_id=" + ph, (oid,)).fetchall()]
    if not old_cells or len(old_cells) > 25:
        return 409, {"error": "invalid_footprint"}
    new_cells = [(xx - old_x + x, yy - old_y + y) for xx, yy in old_cells]
    import roads
    for xx, yy in new_cells:
        if abs(xx) > 1000 or abs(yy) > 1000:
            return 409, {"error": "outside_world"}
        if roads.is_base_road(xx, yy) or roads.is_water(xx, yy):
            return 409, {"error": "blocked_terrain"}
        occupied = db.execute("SELECT object_id FROM cells WHERE x=" + ph + " AND y=" + ph, (xx, yy)).fetchone()
        if occupied and occupied[0] != oid:
            return 409, {"error": "occupied"}
        if db.execute("SELECT 1 FROM roads WHERE x=" + ph + " AND y=" + ph, (xx, yy)).fetchone():
            return 409, {"error": "road_overlap"}
        terrain = db.execute("SELECT kind FROM terrain_edits WHERE x=" + ph + " AND y=" + ph, (xx, yy)).fetchone()
        if terrain == ("water",):
            return 409, {"error": "water"}
    db.execute("DELETE FROM cells WHERE object_id=" + ph, (oid,))
    for xx, yy in new_cells:
        db.execute("INSERT INTO cells(x,y,object_id) VALUES(" + ",".join([ph]*3) + ")", (xx, yy, oid))
    db.execute("UPDATE buildings SET x=" + ph + ",y=" + ph + " WHERE id=" + ph, (x, y, oid))
    for kind_name, coords in (("building_removed", old_cells), ("building_created", new_cells)):
        chunks = {}
        for xx, yy in coords:
            chunks.setdefault((xx // 12, yy // 12), []).append([xx, yy])
        for (cx, cy), cells in chunks.items():
            db.execute("INSERT INTO chunks(cx,cy,version) VALUES(" + ",".join([ph]*3) + ") ON CONFLICT(cx,cy) DO UPDATE SET version=chunks.version+1", (cx, cy, 1))
            version = db.execute("SELECT version FROM chunks WHERE cx=" + ph + " AND cy=" + ph, (cx, cy)).fetchone()[0]
            event = {"cells": cells, "object_id": oid, "owner": building_owner, "building_kind": kind}
            db.execute("INSERT INTO events(cx,cy,version,kind,payload) VALUES(" + ",".join([ph]*5) + ")", (cx, cy, version, kind_name, json.dumps(event)))
    db.execute("INSERT INTO dev_actions(id,actor,action,payload_json,inverse_json,created,undone) VALUES(" + ",".join([ph]*7) + ")", (request_id, owner, "move", json.dumps(payload, ensure_ascii=False), json.dumps({"object_id": oid, "x": old_x, "y": old_y}), action_time, 0))
    admin_api.audit(db, ph, owner, "dev_move", oid, f"from={old_x},{old_y} to={x},{y}", ip, now)
    db.commit()
    return 200, {"request_id": request_id, "object_id": oid, "moved": len(new_cells)}