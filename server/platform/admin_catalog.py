"""A3 authenticated catalog editor, safe preview, append-only revisions."""
from __future__ import annotations

import hashlib
import json
import re

from server.catalog import load_all, canonical
from server.catalog.overrides import (preview_data, read_records, read_revision, normalized,
                                      estimate, validate_changes, check, apply_values)
from . import admin
from .admin_server import guard

_WRITE = {"owner", "admin"}
_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.:-]{7,127}\Z")


def _current(ctx):
    records = read_records(ctx["conn"])
    return apply_values(load_all(), records), records


def catalog(body, ctx):
    actor, err = guard(ctx)
    if err:
        return err
    base = load_all()
    current, records = _current(ctx)
    overridden = {(v["entity"], v["id"], v["field"]) for v in records}
    result = {}
    for kind in ("products", "buildings", "recipes"):
        base_index = {x["id"]: x for x in base[kind]}
        result[kind] = []
        for item in current[kind]:
            fields = sorted(f for e, i, f in overridden if e == kind and i == item["id"])
            result[kind].append({"id": item["id"], "balance": "draft",
                "base": base_index[item["id"]], "effective": item,
                "overridden": bool(fields), "overridden_fields": fields})
    state = normalized(current)
    return 200, {"revision": read_revision(ctx["conn"]), "sha": state.version,
                 "items": result, "editable": {
                     "buildings": ["build_cost", "upkeep_month", "jobs", "storage_capacity", "build_days"],
                     "products": ["reference_price", "volume"],
                     "recipes": ["inputs.<существующий_товар>", "outputs.<существующий_товар>"]}}


def _preview(ctx, changes):
    current, current_records = _current(ctx)
    validated = validate_changes(changes, current)
    after, combined = preview_data(ctx["conn"], validated)
    impacted = set()
    for entry in validated:
        if entry["entity"] == "buildings":
            impacted.add(entry["id"])
        elif entry["entity"] == "recipes":
            impacted.update(r["building"] for r in after["recipes"] if r["id"] == entry["id"])
        else:
            product = entry["id"]
            impacted.update(r["building"] for r in after["recipes"]
                           if product in r["inputs"] or product in r["outputs"])
    before = [estimate(current, name) for name in sorted(impacted)]
    after_values = [estimate(after, name) for name in sorted(impacted)]
    return {"ok": True, "revision": read_revision(ctx["conn"]),
            "before_sha": normalized(current).version,
            "after_sha": normalized(after).version,
            "impacts": [{"building": item["building"], "before": item,
                         "after": after_values[i]} for i, item in enumerate(before)],
            "m1": {"possible": True, "max_days": 10, "starting_capital": 300000},
            "changes": validated}, combined


def preview(body, ctx):
    actor, err = guard(ctx)
    if err:
        return err
    try:
        result, _ = _preview(ctx, body.get("changes"))
    except (ValueError, KeyError, TypeError) as exc:
        return 400, {"error": str(exc), "message": "Предпросмотр отклонён: проверьте границы и хлебную цепочку М1."}
    return 200, result


def _request(body):
    req = body.get("request_id")
    if not isinstance(req, str) or not _ID.fullmatch(req):
        raise ValueError("invalid_request_id")
    return req


def _signature(kind, body):
    return hashlib.sha256(canonical({"operation": kind, **body})).hexdigest()


def _persist(ctx, actor, records, request_id, reason, signature, action, target):
    conn = ctx["conn"]
    # Data is canonicalized and validated before saving. Audit and snapshot share the transaction.
    base = load_all()
    base_index = {kind: {x["id"]: x for x in base[kind]}
                  for kind in ("products", "buildings", "recipes")}
    minimal = []
    for item in records:
        src = base_index[item["entity"]][item["id"]]
        if item["entity"] == "recipes":
            part, product = item["field"].split(".")
            original = src[part][product]
        else:
            original = src[item["field"]]
        if original != item["value"]:
            minimal.append(item)
    check(apply_values(base, minimal))
    old_revision = read_revision(conn)
    new_revision = conn.execute("""INSERT INTO catalog_revisions(request_id,request_hash,reason,created_by)
        VALUES(%s,%s,%s,%s) RETURNING revision""",
        (request_id, signature, reason, actor["username"])).fetchone()[0]
    for item in minimal:
        conn.execute("""INSERT INTO catalog_overrides
            (revision,entity,entity_id,field,value,created_by,active)
            VALUES(%s,%s,%s,%s,%s,%s,true)""",
            (new_revision,item["entity"],item["id"],item["field"],item["value"],actor["username"]))
    admin._audit(ctx, actor, action,
                 {"request_id": request_id, "reason": reason,
                  "previous_revision": old_revision, "new_revision": new_revision},
                 old={"revision": old_revision, "overrides": read_records(conn,old_revision)},
                 new={"revision": new_revision, "overrides": minimal})
    return {"ok": True, "revision": new_revision, "sha": normalized(apply_values(base, minimal)).version,
            "previous_revision": old_revision, "overrides_count": len(minimal)}


def _duplicate(conn, req, signature):
    row = conn.execute("SELECT revision,request_hash FROM catalog_revisions WHERE request_id=%s", (req,)).fetchone()
    if not row:
        return None
    if row[1] != signature:
        return 409, {"error": "request_id_conflict"}
    return 200, {"ok": True, "revision": row[0], "idempotent": True}


def apply(body, ctx):
    actor, err = guard(ctx, _WRITE)
    if err:
        return err
    try:
        req = _request(body)
        reason = body.get("reason")
        if not isinstance(reason, str) or not 3 <= len(reason.strip()) <= 500:
            raise ValueError("reason_required")
        # request_id, including an identical retry, serializes with other editors.
        conn = ctx["conn"]
        conn.execute("SELECT pg_advisory_xact_lock(2026111603)")
        signature = _signature("apply", {"changes": body.get("changes"), "reason": reason})
        duplicate = _duplicate(conn, req, signature)
        if duplicate:
            return duplicate
        result, records = _preview(ctx, body.get("changes"))
        if not result["ok"]:
            return 400, {"error": "preview_failed"}
        saved = _persist(ctx, actor, records, req, reason.strip(), signature, "catalog.apply", "catalog")
        return 200, saved
    except (ValueError, KeyError, TypeError) as exc:
        return 400, {"error": str(exc), "message": "Изменение не прошло проверку безопасности каталога."}


def rollback(body, ctx):
    actor, err = guard(ctx, _WRITE)
    if err:
        return err
    try:
        req = _request(body)
        value = body.get("revision")
        if type(value) is not int or not 0 <= value <= 2**63-1:
            raise ValueError("invalid_revision")
        conn = ctx["conn"]
        conn.execute("SELECT pg_advisory_xact_lock(2026111603)")
        reason = body.get("reason", "Откат каталога")
        if not isinstance(reason, str) or not 3 <= len(reason) <= 500:
            raise ValueError("reason_required")
        signature = _signature("rollback", {"revision": value, "reason": reason})
        duplicate = _duplicate(conn, req, signature)
        if duplicate:
            return duplicate
        if value and not conn.execute("SELECT 1 FROM catalog_revisions WHERE revision=%s", (value,)).fetchone():
            return 404, {"error": "revision_not_found"}
        previous = read_records(conn, value)
        return 200, _persist(ctx, actor, previous, req, reason, signature, "catalog.rollback", value)
    except (ValueError, KeyError, TypeError) as exc:
        return 400, {"error": str(exc), "message": "Невозможно откатить указанную ревизию."}


def revisions(body, ctx):
    actor, err = guard(ctx)
    if err:
        return err
    rows = ctx["conn"].execute("""SELECT revision,created_by,reason,created_at,
        (SELECT count(*) FROM catalog_overrides o WHERE o.revision=r.revision)
        FROM catalog_revisions r ORDER BY revision DESC LIMIT 100""").fetchall()
    return 200, {"current": read_revision(ctx["conn"]), "items": [
        {"revision": int(r[0]), "actor": r[1], "reason": r[2],
         "at": r[3].isoformat(), "overrides_count": r[4]} for r in rows]}
