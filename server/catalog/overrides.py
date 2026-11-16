"""Persistent, immutable admin catalog revision snapshots and runtime refresh.

No JSON source is edited: all overrides are bound to one immutable revision.
Only the single current revision is activated per request/tick.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from threading import RLock

from jsonschema import Draft202012Validator

from . import Catalog, CatalogError, ROOT, NAMES, canonical, load_all, verify

_LOCK = RLock()
_MAX_INT = 10**12
_ALLOWED = {
    "buildings": {
        "build_cost": (0, 10**10), "upkeep_month": (0, 10**9),
        "jobs": (0, 10000), "storage_capacity": (0, 10**9),
        "build_days": (1, 3650),
    },
    "products": {"reference_price": (0, 10**9), "volume": (1, 10**9)},
    "recipes": {},
}
_M1 = (("field", None, "grain"), ("mill", "grain", "flour"),
       ("bakery", "flour", "bread"))
_STARTING_CAPITAL = 300000


def _field(entity, item, field):
    """Return a legal leaf and explicit bounds, never create recipe keys."""
    if entity not in NAMES or not isinstance(field, str):
        raise ValueError("invalid_entity_or_field")
    if entity == "recipes":
        parts = field.split(".")
        if len(parts) != 2 or parts[0] not in ("inputs", "outputs"):
            raise ValueError("field_not_editable")
        if parts[1] not in item[parts[0]]:
            raise ValueError("recipe_structure_locked")
        return item[parts[0]], parts[1], (1, 10**8)
    if field not in _ALLOWED[entity] or field not in item:
        raise ValueError("field_not_editable")
    return item, field, _ALLOWED[entity][field]


def validate_changes(changes, existing):
    if not isinstance(changes, list) or not 1 <= len(changes) <= 100:
        raise ValueError("invalid_changes_count")
    items = {name: {v["id"]: v for v in existing[name]} for name in NAMES}
    result, seen = [], set()
    for change in changes:
        if not isinstance(change, dict) or set(change) != {"entity", "id", "field", "value"}:
            raise ValueError("invalid_change_shape")
        entity, ident, field = change["entity"], change["id"], change["field"]
        if not isinstance(entity, str) or not isinstance(ident, str):
            raise ValueError("invalid_entity_or_id")
        if entity not in items or ident not in items[entity]:
            raise ValueError("unknown_catalog_entry")
        key = (entity, ident, field)
        if key in seen:
            raise ValueError("duplicate_change")
        seen.add(key)
        value = change["value"]
        container, leaf, (lower, upper) = _field(entity, items[entity][ident], field)
        if type(value) is not int or not lower <= value <= upper:
            raise ValueError("out_of_range")
        result.append({"entity": entity, "id": ident, "field": field, "value": value})
    return result


def apply_values(base, records):
    data = deepcopy(base)
    idx = {kind: {x["id"]: x for x in data[kind]} for kind in NAMES}
    for item in records:
        container, leaf, _ = _field(item["entity"], idx[item["entity"]][item["id"]], item["field"])
        container[leaf] = item["value"]
    return data


def check(data):
    schema = json.loads((ROOT / "schema.json").read_text(encoding="utf-8"))
    for kind in NAMES:
        errors = list(Draft202012Validator(schema["$defs"][kind]).iter_errors(data[kind]))
        if errors:
            raise CatalogError("schema: " + sorted(errors, key=lambda e: str(e.path))[0].message)
    verify(data)
    builds = {x["id"]: x for x in data["buildings"]}
    recipes = data["recipes"]
    total = builds["grocery_store"]["build_cost"]
    days = builds["grocery_store"]["build_days"]
    for building, input_id, output_id in _M1:
        total += builds[building]["build_cost"]
        days += builds[building]["build_days"]
        if not any(r["building"] == building and output_id in r["outputs"] and
                   (input_id is None or input_id in r["inputs"]) for r in recipes):
            raise CatalogError("bread_chain_incomplete")
    if total > _STARTING_CAPITAL or days >= 10:
        raise CatalogError("bread_m1_over_budget_or_days")
    stages = []
    for building, source, output in _M1:
        matched = [r for r in recipes if r["building"] == building and output in r["outputs"]
                   and (source is None or source in r["inputs"])]
        stages.append(max(matched,key=lambda r: r["outputs"][output]))
    # Conservative integer stock-flow check, one recipe run per day and stage.
    # No production using inputs that are not yet in the previous-stage stock.
    stock={"grain":0,"flour":0,"bread":0}
    for _ in range(10-days):
        for recipe in stages:
            if all(stock.get(p,0)>=amount for p,amount in recipe["inputs"].items()):
                for p,amount in recipe["inputs"].items():
                    stock[p]-=amount
                for p,amount in recipe["outputs"].items():
                    stock[p]=stock.get(p,0)+amount
        if stock["bread"]>=1:
            break
    else:
        raise CatalogError("bread_m1_cannot_produce_in_10_days")


def read_revision(conn):
    row = conn.execute("SELECT COALESCE(MAX(revision),0) FROM catalog_revisions").fetchone()
    return int(row[0])


def read_records(conn, revision=None):
    revision = read_revision(conn) if revision is None else revision
    if revision == 0:
        return []
    rows = conn.execute("""SELECT entity,entity_id,field,value
        FROM catalog_overrides WHERE revision=%s AND active=true
        ORDER BY entity,entity_id,field""", (revision,)).fetchall()
    return [{"entity": e, "id": i, "field": f, "value": int(v)} for e, i, f, v in rows]


def normalized(data):
    """One Catalog shape, including its exact public SHA and ETag."""
    result = object.__new__(Catalog)
    result.data = data
    result.version = hashlib.sha256(canonical(data)).hexdigest()
    result.etag = '"' + result.version + '"'
    result.index = {kind: {item["id"]: item for item in data[kind]} for kind in NAMES}
    result.payload = {**data, "version": result.version, "balance": "draft"}
    return result


def refresh_registry(registry, conn):
    """Load committed overrides before serving requests or a daily/monthly tick.

    The in-memory instance is updated in place because public routes close over it.
    Only completed DB transactions may be observed by other connections.
    """
    if not hasattr(registry, "catalog"):
        return
    if conn.execute("SELECT to_regclass('catalog_revisions')").fetchone()[0] is None:
        return
    revision = read_revision(conn)
    if getattr(registry, "_catalog_revision", None) == revision:
        return
    with _LOCK:
        if getattr(registry, "_catalog_revision", None) == revision:
            return
        data = apply_values(load_all(), read_records(conn, revision))
        check(data)
        snapshot = normalized(data)
        registry.catalog.__dict__ = snapshot.__dict__
        import server.catalog as catalog_module
        catalog_module._ACTIVE_RUNTIME = registry.catalog
        registry._catalog_revision = revision
        # A legacy module has its own optional cache; all other readers call core.catalog().
        from server.enterprises import core
        core._CATALOG = registry.catalog


def preview_data(conn, changes):
    current = read_records(conn)
    # Overwrite rather than append a duplicate of the same tuple.
    values = {(x["entity"], x["id"], x["field"]): x for x in current}
    for item in changes:
        values[(item["entity"], item["id"], item["field"])] = item
    combined = list(values.values())
    data = apply_values(load_all(), combined)
    check(data)
    return data, combined


def estimate(data, building_id):
    """Integer-only approximate one-day production margin and payback."""
    b = next(x for x in data["buildings"] if x["id"] == building_id)
    products = {p["id"]: p for p in data["products"]}
    candidates = [r for r in data["recipes"] if r["building"] == building_id]
    # One recipe per building per day, not a sum of mutually exclusive recipes.
    recipe = max(candidates, key=lambda r: sum(q * products[p]["reference_price"]
                 for p, q in r["outputs"].items()), default=None)
    revenue = sum(q * products[p]["reference_price"] for p, q in recipe["outputs"].items()) if recipe else 0
    supplies = sum(q * products[p]["reference_price"] for p, q in recipe["inputs"].items()) if recipe else 0
    salary = ((recipe["workers"] if recipe else b["jobs"]) * 100 + 29) // 30  # monthly wage / 30
    upkeep = (b["upkeep_month"] + 29) // 30
    margin = revenue - supplies - salary - upkeep
    days = (b["build_cost"] + margin - 1) // margin if margin > 0 else None
    return {"building": building_id, "build_cost": b["build_cost"],
            "daily_revenue": revenue, "daily_inputs": supplies, "daily_wages": salary,
            "daily_upkeep": upkeep, "daily_profit": margin,
            "payback_days": days}
