"""Place a commercial building inside the caller's transaction.

Map rules are not reimplemented: the footprint and the access road come from
``roads.plan_access`` / ``roads.is_base_road``, and the charge comes from
``economy.charge_build``. The INSERT loop lives here only because
``game_server.build`` and ``postgres_world.build`` open their own transaction
and cannot be nested under the world lock (a second PostgreSQL connection would
deadlock on ``pg_advisory_xact_lock``). See docs/ALLIANCES.md.
"""
import json
import uuid

import economy
import production
import roads as road_rules


KINDS = {"farm": (2, 2), "mine": (2, 3), "factory": (3, 2), "warehouse": (3, 3)}
CHUNK = 12
MAX_COORD = 10000


def _q(sql, ph):
    return sql.replace("%s", ph)


def footprint_for(kind, x, y):
    if kind not in KINDS or type(x) is not int or type(y) is not int or abs(x) > MAX_COORD or abs(y) > MAX_COORD:
        return None
    w, h = KINDS[kind]
    cells = [(xx, yy) for xx in range(x, x + w) for yy in range(y, y + h)]
    if any(abs(xx) > MAX_COORD or abs(yy) > MAX_COORD for xx, yy in cells):
        return None
    return cells


def plan(db, ph, kind, x, y):
    """Read-only access plan. Returns ``(error, info)``. ``info`` has cost and new road cells."""
    footprint = footprint_for(kind, x, y)
    if footprint is None:
        return "invalid_build", None
    x0, x1, y0, y1 = road_rules.search_box(footprint)
    dynamic = {(rx, ry) for rx, ry in db.execute(
        _q("SELECT x,y FROM roads WHERE x BETWEEN %s AND %s AND y BETWEEN %s AND %s", ph), (x0, x1, y0, y1))}
    occupied = {(cx, cy) for cx, cy in db.execute(
        _q("SELECT x,y FROM cells WHERE x BETWEEN %s AND %s AND y BETWEEN %s AND %s", ph), (x0, x1, y0, y1))}
    if any(db.execute(_q("SELECT 1 FROM cells WHERE x=%s AND y=%s", ph), (xx, yy)).fetchone() for xx, yy in footprint):
        return "occupied", None
    import zoning
    if zoning.check(db, ph, kind, footprint):
        return "wrong_zone", None
    error, path = road_rules.plan_access(footprint, dynamic, occupied, MAX_COORD)
    if error:
        return error, None
    new_roads = [c for c in path if not road_rules.is_base_road(*c) and c not in dynamic]
    return None, {"footprint": footprint, "new_roads": new_roads, "cost": economy.build_cost(kind, len(new_roads))}


def _event(db, ph, cx, cy, version, kind, payload):
    sql = "INSERT INTO events(cx,cy,version,kind,payload) VALUES(%s,%s,%s,%s,%s)"
    params = (cx, cy, version, kind, payload)
    if ph == "%s":
        return int(db.execute(_q(sql, ph) + " RETURNING seq", params).fetchone()[0])
    return int(db.execute(_q(sql, ph), params).lastrowid)


def place(db, ph, owner, kind, x, y, planned, now, clk):
    """Charge ``owner`` and place the building. Caller holds the world transaction.

    The owner's wallet row must already exist when a free starting capital would
    be wrong (alliance companies). ``economy.charge_build`` grants capital only
    when the wallet row is inserted by that call.
    """
    footprint = planned["footprint"]
    new_roads = planned["new_roads"]
    paid, cost, balance = economy.charge_build(db, ph, owner, kind, len(new_roads), now)
    if not paid:
        return 402, {"error": "insufficient_funds", "cost": cost, "balance": balance}
    object_id = uuid.uuid4().hex
    db.execute(_q("INSERT INTO buildings(id,owner,kind,x,y,created) VALUES(%s,%s,%s,%s,%s,%s)", ph),
               (object_id, owner, kind, x, y, now))
    production.register_building(db, ph, owner, object_id, kind, clk)
    for xx, yy in footprint:
        db.execute(_q("INSERT INTO cells(x,y,object_id) VALUES(%s,%s,%s)", ph), (xx, yy, object_id))
    for rx, ry in new_roads:
        db.execute(_q("INSERT INTO roads(x,y,owner,created) VALUES(%s,%s,%s,%s)", ph), (rx, ry, owner, now))
    events = []
    for kind_name, cells in (("building_created", footprint), ("road_changed", new_roads)):
        grouped = {}
        for xx, yy in cells:
            grouped.setdefault((xx // CHUNK, yy // CHUNK), []).append([xx, yy])
        for (cx, cy), coords in sorted(grouped.items()):
            db.execute(_q("INSERT INTO chunks(cx,cy,version) VALUES(%s,%s,1) ON CONFLICT(cx,cy) DO UPDATE SET version=chunks.version+1", ph),
                       (cx, cy))
            version = int(db.execute(_q("SELECT version FROM chunks WHERE cx=%s AND cy=%s", ph), (cx, cy)).fetchone()[0])
            data = {"object_id": object_id, "owner": owner, "cells": coords}
            if kind_name == "building_created":
                data["building_kind"] = kind
            seq = _event(db, ph, cx, cy, version, kind_name, json.dumps(data, ensure_ascii=False))
            events.append({"seq": seq, "cx": cx, "cy": cy, "version": version, "kind": kind_name, **data})
    return 201, {"ok": True, "object_id": object_id, "road_cells": len(new_roads), "cost": cost,
                 "balance": economy.balance(db, ph, owner), "events": events}
