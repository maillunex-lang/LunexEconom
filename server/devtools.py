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
    return bool(owner) and accounts_admin.is_developer(owner, db)

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
    row = db.execute("SELECT id,inverse_json FROM dev_actions WHERE actor=" + ph + " AND action='terrain' AND undone=0 ORDER BY created DESC,id DESC LIMIT 1", (owner,)).fetchone()
    if not row:
        return 409, {"error": "nothing_to_undo"}
    action_id, inverse = row
    snapshot = json.loads(inverse)
    if len(snapshot) > 25:
        return 409, {"error": "invalid_history"}
    for coordinate, state in snapshot.items():
        x, y = map(int, coordinate.split(","))
        if state is None:
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