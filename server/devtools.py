"""Developer-only API primitives. Never trust client-supplied role or owner."""
import json
import time
import uuid
import accounts_admin
import admin_api
import terrain_edits

def ensure(db, ph, postgres=False):
    terrain_edits.ensure(db)
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
    existing=db.execute("SELECT actor,action,payload_json FROM dev_actions WHERE id="+ph,(request_id,)).fetchone()
    if existing:
        old_actor, old_action, old_json = existing
        return (200,{"request_id":request_id,"replayed":True}) if old_actor == owner and old_action == "terrain" and json.loads(old_json)==payload else (409,{"error":"request_id_conflict"})
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
    row = db.execute("SELECT id,action,inverse_json,payload_json FROM dev_actions WHERE actor=" + ph + " AND action IN ('terrain','roads','move','demolish','create') AND undone=0 ORDER BY created DESC,id DESC LIMIT 1", (owner,)).fetchone()
    if not row:
        return 409, {"error": "nothing_to_undo"}
    action_id, action_kind, inverse, original_payload = row
    original = json.loads(original_payload)
    snapshot = json.loads(inverse)
    if action_kind == "create":
        oid = snapshot["object_id"]
        row = db.execute("SELECT owner,kind FROM buildings WHERE id=" + ph, (oid,)).fetchone()
        if row is None or row[1] != original["kind"]:
            return 409, {"error": "undo_conflict"}
        # Do not delete a building whose ownership or economic registrations
        # have changed since the operator created it.
        import economy
        developer_gift = original.get('developer_override') is True
        if row[0] != (snapshot.get('owner') if developer_gift else economy.CITY):
            return 409, {"error": "undo_conflict"}
        original_anchor = db.execute("SELECT x,y FROM buildings WHERE id=" + ph, (oid,)).fetchone()
        if original_anchor != (original["x"], original["y"]):
            return 409, {"error": "undo_conflict"}
        if db.execute("SELECT 1 FROM building_ops WHERE object_id=" + ph, (oid,)).fetchone() and not developer_gift:
            return 409, {"error": "building_operational"}
        if developer_gift:
            # Only undo a gifted enterprise when it has not accumulated cash,
            # inventory, contracts or production history since creation.
            oid_owner=snapshot['owner']
            if db.execute('SELECT 1 FROM company_reports WHERE owner='+ph+' LIMIT 1',(oid_owner,)).fetchone():
                return 409,{'error':'economic_history_exists'}
            if db.execute('SELECT 1 FROM trade_contracts WHERE (supplier='+ph+' OR buyer='+ph+") AND status='active' LIMIT 1",(oid_owner,oid_owner)).fetchone():
                return 409,{'error':'active_contracts'}
            if db.execute('SELECT 1 FROM inventory WHERE owner='+ph+' AND qty>0 LIMIT 1',(oid_owner,)).fetchone():
                return 409,{'error':'inventory_present'}
            for rx,ry in snapshot.get('roads',[]):
                # Reject undo if other buildings now depend on gifted access roads.
                import dev_road_connectivity
                # Temporarily hide the very building being reverted from the
                # connectivity check. Otherwise its own access counts as lost.
                own_cells=db.execute('SELECT x,y FROM cells WHERE object_id='+ph,(oid,)).fetchall()
                db.execute('DELETE FROM cells WHERE object_id='+ph,(oid,))
                try:
                    issue=dev_road_connectivity.validate_removal(db,ph,[tuple(c) for c in snapshot['roads']])
                finally:
                    for xx,yy in own_cells:
                        db.execute('INSERT INTO cells(x,y,object_id) VALUES('+','.join([ph]*3)+')',(xx,yy,oid))
                if issue:return 409,{'error':issue}
                break
        import production
        production._remove_building(db, ph, oid, row[0])
        if developer_gift:
            db.execute('DELETE FROM enterprise_settings WHERE object_id='+ph,(oid,))
            for rx,ry in snapshot.get('roads',[]):
                db.execute('DELETE FROM roads WHERE x='+ph+' AND y='+ph,(rx,ry))
            publish_terrain_events(db,ph,[tuple(c) for c in snapshot.get('roads',[])])
        db.execute("UPDATE dev_actions SET undone=1 WHERE id=" + ph, (action_id,))
        db.execute("INSERT INTO dev_actions(id,actor,action,payload_json,inverse_json,created,undone) VALUES(" + ",".join([ph]*7) + ")", (request_id, owner, "undo", json.dumps(payload), inverse, action_time, 0))
        admin_api.audit(db, ph, owner, "dev_undo_create", oid, "removed", ip, now)
        db.commit()
        return 200, {"request_id": request_id, "undone": action_id, "removed": oid}
    if action_kind == "demolish":
        building = snapshot["building"]
        oid = original["object_id"]
        if db.execute("SELECT 1 FROM buildings WHERE id=" + ph, (oid,)).fetchone():
            return 409, {"error": "undo_conflict"}
        for x, y in snapshot["cells"]:
            if db.execute("SELECT 1 FROM cells WHERE x=" + ph + " AND y=" + ph, (x, y)).fetchone():
                return 409, {"error": "undo_conflict", "cell": [x, y]}
            if db.execute("SELECT 1 FROM roads WHERE x=" + ph + " AND y=" + ph, (x, y)).fetchone():
                return 409, {"error": "road_overlap", "cell": [x, y]}
        for link in snapshot["dependent"]["building_deposits"]:
            if db.execute("SELECT 1 FROM building_deposits WHERE deposit_id=" + ph, (link[1],)).fetchone():
                return 409, {"error": "deposit_claimed"}
        db.execute("INSERT INTO buildings(id,owner,kind,x,y,created) VALUES(" + ",".join([ph]*6) + ")", (oid, *building))
        for table in ("building_ops", "building_dimensions", "building_specializations", "building_deposits"):
            for record in snapshot["dependent"][table]:
                db.execute("INSERT INTO " + table + " VALUES(" + ",".join([ph]*len(record)) + ")", record)
        for x, y in snapshot["cells"]:
            db.execute("INSERT INTO cells(x,y,object_id) VALUES(" + ",".join([ph]*3) + ")", (x, y, oid))
        if snapshot.get('operational_override'):
            stage=snapshot.get('construction_stage')
            if stage:
                db.execute('INSERT INTO construction_stages(object_id,stage,next_at) VALUES('+','.join([ph]*3)+')',(oid,stage[0],stage[1]))
            setting=snapshot.get('settings')
            if setting:db.execute('INSERT INTO enterprise_settings VALUES('+','.join([ph]*len(setting))+')',tuple(setting))
        groups = {}
        for x, y in snapshot["cells"]:
            groups.setdefault((x // 12, y // 12), []).append([x, y])
        for (cx, cy), cells in groups.items():
            db.execute("INSERT INTO chunks(cx,cy,version) VALUES(" + ",".join([ph]*3) + ") ON CONFLICT(cx,cy) DO UPDATE SET version=chunks.version+1", (cx, cy, 1))
            version = db.execute("SELECT version FROM chunks WHERE cx=" + ph + " AND cy=" + ph, (cx, cy)).fetchone()[0]
            event = {"object_id": oid, "owner": building[0], "building_kind": building[1], "cells": cells}
            db.execute("INSERT INTO events(cx,cy,version,kind,payload) VALUES(" + ",".join([ph]*5) + ")", (cx, cy, version, "building_created", json.dumps(event)))
        db.execute("UPDATE dev_actions SET undone=1 WHERE id=" + ph, (action_id,))
        db.execute("INSERT INTO dev_actions(id,actor,action,payload_json,inverse_json,created,undone) VALUES(" + ",".join([ph]*7) + ")", (request_id, owner, "undo", json.dumps(payload), inverse, action_time, 0))
        admin_api.audit(db, ph, owner, "dev_undo_demolish", oid, "restored", ip, now)
        db.commit()
        return 200, {"request_id": request_id, "undone": action_id, "restored": oid}
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
    # A later operation on any affected cell makes an older undo unsafe,
    # even when the visible kind and editor happen to match.
    affected = set(snapshot)
    later = db.execute("SELECT action,payload_json FROM dev_actions WHERE created>" + ph + " AND action IN ('terrain','roads') AND undone=0", (db.execute("SELECT created FROM dev_actions WHERE id=" + ph, (action_id,)).fetchone()[0],)).fetchall()
    for later_kind, later_json in later:
        other = json.loads(later_json)
        if any(f"{x},{y}" in affected for x,y in other.get("cells", [])):
            return 409, {"error": "undo_conflict_newer_action"}
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
    if action_kind == "roads":
        import dev_road_connectivity
        deletions = [tuple(map(int, coordinate.split(","))) for coordinate, state in snapshot.items() if state is None]
        conflict = dev_road_connectivity.validate_removal(db, ph, deletions)
        if conflict:
            return 409, {"error": conflict}
        for coordinate, state in snapshot.items():
            if state is None:
                continue
            x, y = map(int, coordinate.split(","))
            if db.execute("SELECT 1 FROM cells WHERE x=" + ph + " AND y=" + ph, (x, y)).fetchone():
                return 409, {"error": "occupied", "cell": [x, y]}
            import roads
            if roads.is_water(x, y) or db.execute("SELECT kind FROM terrain_edits WHERE x=" + ph + " AND y=" + ph, (x, y)).fetchone() == ("water",):
                return 409, {"error": "water", "cell": [x, y]}
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
    if operation == "remove":
        import dev_road_connectivity
        conflict = dev_road_connectivity.validate_removal(db, ph, coords)
        if conflict:
            return 409, {"error": conflict}
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
    # Preserve the same zoning restrictions used by ordinary construction.
    import zoning
    if zoning.check(db, ph, kind, new_cells):
        return 409, {"error": "invalid_destination_zone"}
    import dev_road_connectivity
    access_error = dev_road_connectivity.validate_building_move(db, ph, oid, old_cells, new_cells)
    if access_error:
        return 409, {"error": access_error}
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

def building_demolish(db, ph, actor, payload, ip):
    """Developer demolition without sale proceeds or ledger mutations.

    Refuses economically active buildings and deposit-linked extraction
    sites. Uses the same map/event cleanup as regular sales, without payment.
    """
    if not require_developer(actor, db):
        return 403, {"error": "forbidden"}
    if not isinstance(payload, dict):
        return 400, {"error": "invalid_body"}
    try:
        request_id = str(uuid.UUID(payload.get("request_id")))
    except (ValueError, TypeError, AttributeError):
        return 400, {"error": "invalid_request_id"}
    oid = payload.get("object_id")
    if not isinstance(oid, str) or not 1 <= len(oid) <= 100:
        return 400, {"error": "invalid_object_id"}
    previous = db.execute("SELECT actor,action,payload_json FROM dev_actions WHERE id=" + ph, (request_id,)).fetchone()
    if previous:
        return (200, {"request_id": request_id, "replayed": True}) if previous == (actor, "demolish", json.dumps(payload, ensure_ascii=False)) else (409, {"error": "request_id_conflict"})
    row = db.execute("SELECT owner,kind,x,y,created FROM buildings WHERE id=" + ph, (oid,)).fetchone()
    if not row:
        return 404, {"error": "building_not_found"}
    cells = db.execute("SELECT x,y FROM cells WHERE object_id=" + ph, (oid,)).fetchall()
    if not cells or len(cells) > 25:
        return 409, {"error": "invalid_footprint"}
    # A real enterprise can be closed only with explicit developer override,
    # and only if removing it cannot erase liabilities, goods or contract rights.
    explicit=payload.get('developer_override') is True
    operational=db.execute("SELECT 1 FROM building_ops WHERE object_id=" + ph, (oid,)).fetchone() is not None
    deposit_link=db.execute("SELECT 1 FROM building_deposits WHERE object_id=" + ph, (oid,)).fetchone() is not None
    if operational and not explicit:return 409,{'error':'active_economic_building'}
    if deposit_link and not explicit:return 409,{'error':'deposit_bound'}
    if explicit:
        owner=row[0]
        if operational:
            if db.execute('SELECT 1 FROM inventory WHERE owner='+ph+' AND qty>0 LIMIT 1',(owner,)).fetchone():
                return 409,{'error':'inventory_present'}
            if db.execute('SELECT 1 FROM trade_contracts WHERE (supplier='+ph+' OR buyer='+ph+") AND status='active' LIMIT 1",(owner,owner)).fetchone():
                return 409,{'error':'active_contracts'}
            if db.execute('SELECT 1 FROM trade_debts WHERE (debtor='+ph+' OR creditor='+ph+') AND amount>0 LIMIT 1',(owner,owner)).fetchone():
                return 409,{'error':'trade_debts'}
            if db.execute('SELECT 1 FROM company_status WHERE owner='+ph+' AND (wages_owed>0 OR input_owed>0 OR maint_owed>0) LIMIT 1',(owner,)).fetchone():
                return 409,{'error':'unpaid_liabilities'}
            if db.execute('SELECT 1 FROM company_tax_state WHERE owner='+ph+' AND tax_owed>0 LIMIT 1',(owner,)).fetchone():
                return 409,{'error':'unpaid_taxes'}
            if db.execute('SELECT 1 FROM loans WHERE owner='+ph+' AND balance>0 LIMIT 1',(owner,)).fetchone():
                return 409,{'error':'outstanding_loan'}
            if db.execute('SELECT 1 FROM soc_orders WHERE owner='+ph+" AND status='open' LIMIT 1",(owner,)).fetchone():
                return 409,{'error':'open_exchange_orders'}
    action_time = time.time_ns()
    recent = db.execute("SELECT COUNT(*) FROM dev_actions WHERE actor=" + ph + " AND created>=" + ph, (actor, action_time - 60_000_000_000)).fetchone()[0]
    if recent >= 30:
        return 429, {"error": "rate_limited"}
    # Keep a complete reversible snapshot of the building's direct records.
    dependent = {}
    for table, columns in (
        ("building_ops", "object_id,owner,kind,start_month,start_permille"),
        ("building_dimensions", "object_id,width,height,equipment_level"),
        ("building_specializations", "object_id,specialization"),
        ("building_deposits", "object_id,deposit_id,resource"),
    ):
        dependent[table] = db.execute("SELECT " + columns + " FROM " + table + " WHERE object_id=" + ph, (oid,)).fetchall()
    snapshot = {"building": list(row), "cells": [list(c) for c in cells], "dependent": {k: [list(r) for r in v] for k,v in dependent.items()}}
    if explicit:
        snapshot['operational_override']=True
        snapshot['construction_stage']=db.execute('SELECT stage,next_at FROM construction_stages WHERE object_id='+ph,(oid,)).fetchone()
        snapshot['settings']=db.execute('SELECT object_id,owner,name,price,price_rule,min_stock,buy_limit,managers FROM enterprise_settings WHERE object_id='+ph,(oid,)).fetchone()
    import production
    production._remove_building(db, ph, oid, row[0])
    if explicit:db.execute('DELETE FROM enterprise_settings WHERE object_id='+ph,(oid,))
    db.execute("INSERT INTO dev_actions(id,actor,action,payload_json,inverse_json,created,undone) VALUES(" + ",".join([ph]*7) + ")", (request_id, actor, "demolish", json.dumps(payload, ensure_ascii=False), json.dumps(snapshot), action_time, 0))
    admin_api.audit(db, ph, actor, "dev_demolish", oid, "no_ledger_payment", ip, int(time.time()))
    db.commit()
    return 200, {"request_id": request_id, "object_id": oid, "removed": len(cells)}

def create_player_asset(db, ph, actor, payload, ip):
    """Explicit developer gift. No purchase / tax / profit, tracked and reversible."""
    import building_dimensions, city_catalog, economy, roads, zoning, terrain_rules, production, clock, deposits
    if not require_developer(actor, db): return 403, {'error':'forbidden'}
    if not isinstance(payload,dict) or payload.get('developer_override') is not True: return 403,{'error':'developer_override_required'}
    request_id=payload.get('request_id')
    try: request_id=str(uuid.UUID(request_id))
    except (ValueError, TypeError, AttributeError):return 400,{'error':'invalid_request_id'}
    kind,owner,x,y=payload.get('kind'),payload.get('owner'),payload.get('x'),payload.get('y')
    if type(owner) is not str or not owner or len(owner)>64 or owner in ('city',) or owner.startswith(('system:','town:','player:')):
        return 400,{'error':'invalid_owner'}
    if type(x) is not int or type(y) is not int or abs(x)>1000 or abs(y)>1000:return 400,{'error':'invalid_coordinates'}
    catalog=city_catalog.get(kind)
    if kind in economy.BUILD_COST:
        w,h=building_dimensions.footprint(kind)
        zone_kind=kind
        operational=True
    elif catalog and catalog['category']=='housing':
        w,h=catalog['w'],catalog['h']
        zone_kind='house'
        operational=False
    else:return 400,{'error':'unsupported_kind'}
    if x+w-1>1000 or y+h-1>1000:return 400,{'error':'outside_world'}
    existing=db.execute('SELECT actor,action,payload_json FROM dev_actions WHERE id='+ph,(request_id,)).fetchone()
    if existing:
        return (200,{'request_id':request_id,'replayed':True}) if existing==(actor,'create',json.dumps(payload,ensure_ascii=False)) else (409,{'error':'request_id_conflict'})
    cells=[(xx,yy) for xx in range(x,x+w) for yy in range(y,y+h)]
    if any(roads.is_base_road(*c) for c in cells):return 409,{'error':'base_road_overlap'}
    for a,b in cells:
        if db.execute('SELECT 1 FROM cells WHERE x='+ph+' AND y='+ph,(a,b)).fetchone():return 409,{'error':'occupied'}
        if db.execute('SELECT 1 FROM roads WHERE x='+ph+' AND y='+ph,(a,b)).fetchone():return 409,{'error':'road_overlap'}
    if zoning.check(db,ph,zone_kind,cells):return 409,{'error':'invalid_zone'}
    box=roads.search_box(cells)
    edits=terrain_rules.preload(db,ph,box)
    if any(terrain_rules.is_water(a,b,edits) for a,b in cells):return 409,{'error':'water'}
    x0,x1,y0,y1=box
    dyn={(a,b) for a,b in db.execute('SELECT x,y FROM roads WHERE x BETWEEN '+ph+' AND '+ph+' AND y BETWEEN '+ph+' AND '+ph,(x0,x1,y0,y1))}
    occupied={(a,b) for a,b in db.execute('SELECT x,y FROM cells WHERE x BETWEEN '+ph+' AND '+ph+' AND y BETWEEN '+ph+' AND '+ph,(x0,x1,y0,y1))}
    err,path=roads.plan_access(cells,dyn,occupied,1000,edits)
    if err:return 409,{'error':err}
    new_roads=[c for c in path if not roads.is_base_road(*c) and c not in dyn]
    deposits.ensure(db,ph)
    decision=deposits.gate(db,ph,kind,cells) if operational else None
    if decision and decision.get('error'):return 409,decision
    now=int(time.time());oid=uuid.uuid4().hex
    db.execute('INSERT INTO buildings(id,owner,kind,x,y,created) VALUES('+','.join([ph]*6)+')',(oid,owner,kind,x,y,now))
    for a,b in cells:db.execute('INSERT INTO cells(x,y,object_id) VALUES('+','.join([ph]*3)+')',(a,b,oid))
    for a,b in new_roads:db.execute('INSERT INTO roads(x,y,owner,created) VALUES('+','.join([ph]*4)+')',(a,b,actor,now))
    if operational:
        # Explicit commissioned asset: no construction charge, production begins next month.
        clk=clock.state(db,ph,now)
        production.register_building(db,ph,owner,oid,kind,clk)
        if decision and decision.get('deposit_id'):deposits.link(db,ph,oid,decision['deposit_id'],decision['resource'])
    for kind_name, group in (('building_created',cells),('road_changed',new_roads)):
        if not group:continue
        chunks={}
        for a,b in group:chunks.setdefault((a//12,b//12),[]).append([a,b])
        for (cx,cy),coords in chunks.items():
            db.execute('INSERT INTO chunks(cx,cy,version) VALUES('+','.join([ph]*3)+') ON CONFLICT(cx,cy) DO UPDATE SET version=chunks.version+1',(cx,cy,1))
            ver=db.execute('SELECT version FROM chunks WHERE cx='+ph+' AND cy='+ph,(cx,cy)).fetchone()[0]
            event={'object_id':oid,'owner':owner,'building_kind':kind,'cells':coords}
            db.execute('INSERT INTO events(cx,cy,version,kind,payload) VALUES('+','.join([ph]*5)+')',(cx,cy,ver,kind_name,json.dumps(event)))
    previous={'object_id':oid,'owner':owner,'roads':new_roads,'operational':operational}
    action_time=time.time_ns()
    db.execute('INSERT INTO dev_actions(id,actor,action,payload_json,inverse_json,created,undone) VALUES('+','.join([ph]*7)+')',
               (request_id,actor,'create',json.dumps(payload,ensure_ascii=False),json.dumps(previous),action_time,0))
    admin_api.audit(db,ph,actor,'dev_create_player',oid,'owner='+owner+' no_cash_post',ip,now)
    db.commit()
    return 200,{'request_id':request_id,'object_id':oid,'created':len(cells),'road_cells':len(new_roads),'owner':owner}

def building_create(db, ph, actor, payload, ip):
    """Create city social building or explicitly developer-gifted player asset."""
    if isinstance(payload,dict) and payload.get('developer_override') is True:
        return create_player_asset(db,ph,actor,payload,ip)
    if not require_developer(actor, db):
        return 403, {"error": "forbidden"}
    if not isinstance(payload, dict):
        return 400, {"error": "invalid_body"}
    try:
        request_id = str(uuid.UUID(payload.get("request_id")))
    except (ValueError, TypeError, AttributeError):
        return 400, {"error": "invalid_request_id"}
    kind, x, y = payload.get("kind"), payload.get("x"), payload.get("y")
    if type(x) is not int or type(y) is not int or abs(x) > 1000 or abs(y) > 1000:
        return 400, {"error": "invalid_coordinates"}
    import building_dimensions
    import economy
    import roads
    import zoning
    try:
        width, height = building_dimensions.footprint(kind)
    except (ValueError, TypeError):
        return 400, {"error": "unknown_building_kind"}
    if payload.get("owner", economy.CITY) != economy.CITY:
        return 403, {"error": "city_only"}
    if kind not in economy.SOCIAL_KINDS:
        return 409, {"error": "economic_building_requires_normal_construction"}
    if x + width - 1 > 1000 or y + height - 1 > 1000:
        return 400, {"error": "outside_world"}
    previous = db.execute("SELECT actor,action,payload_json FROM dev_actions WHERE id=" + ph, (request_id,)).fetchone()
    if previous:
        return (200, {"request_id": request_id, "replayed": True}) if previous == (actor, "create", json.dumps(payload, ensure_ascii=False)) else (409, {"error": "request_id_conflict"})
    cells = [(xx, yy) for xx in range(x, x + width) for yy in range(y, y + height)]
    for xx, yy in cells:
        if roads.is_water(xx, yy) or roads.is_base_road(xx, yy):
            return 409, {"error": "blocked_terrain"}
        if db.execute("SELECT 1 FROM cells WHERE x=" + ph + " AND y=" + ph, (xx, yy)).fetchone():
            return 409, {"error": "occupied"}
        if db.execute("SELECT 1 FROM roads WHERE x=" + ph + " AND y=" + ph, (xx, yy)).fetchone():
            return 409, {"error": "road_overlap"}
        if db.execute("SELECT kind FROM terrain_edits WHERE x=" + ph + " AND y=" + ph, (xx, yy)).fetchone() == ("water",):
            return 409, {"error": "water"}
    if zoning.check(db, ph, kind, cells):
        return 409, {"error": "invalid_zone"}
    action_time = time.time_ns()
    count = db.execute("SELECT COUNT(*) FROM dev_actions WHERE actor=" + ph + " AND created>=" + ph, (actor, action_time - 60_000_000_000)).fetchone()[0]
    if count >= 30:
        return 429, {"error": "rate_limited"}
    oid = uuid.uuid4().hex
    now = int(time.time())
    db.execute("INSERT INTO buildings(id,owner,kind,x,y,created) VALUES(" + ",".join([ph]*6) + ")", (oid, economy.CITY, kind, x, y, now))
    for xx, yy in cells:
        db.execute("INSERT INTO cells(x,y,object_id) VALUES(" + ",".join([ph]*3) + ")", (xx, yy, oid))
    grouped = {}
    for xx, yy in cells:
        grouped.setdefault((xx // 12, yy // 12), []).append([xx, yy])
    for (cx, cy), coords in grouped.items():
        db.execute("INSERT INTO chunks(cx,cy,version) VALUES(" + ",".join([ph]*3) + ") ON CONFLICT(cx,cy) DO UPDATE SET version=chunks.version+1", (cx, cy, 1))
        version = db.execute("SELECT version FROM chunks WHERE cx=" + ph + " AND cy=" + ph, (cx, cy)).fetchone()[0]
        event = {"object_id": oid, "owner": economy.CITY, "building_kind": kind, "cells": coords}
        db.execute("INSERT INTO events(cx,cy,version,kind,payload) VALUES(" + ",".join([ph]*5) + ")", (cx, cy, version, "building_created", json.dumps(event)))
    db.execute("INSERT INTO dev_actions(id,actor,action,payload_json,inverse_json,created,undone) VALUES(" + ",".join([ph]*7) + ")", (request_id, actor, "create", json.dumps(payload, ensure_ascii=False), json.dumps({"object_id": oid}), action_time, 0))
    admin_api.audit(db, ph, actor, "dev_create", oid, "city_owned_no_ledger_payment", ip, now)
    db.commit()
    return 200, {"request_id": request_id, "object_id": oid, "created": len(cells)}