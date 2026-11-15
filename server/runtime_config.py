"""Typed runtime configuration with immutable snapshots and month boundaries.

Only values discovered from balance.DEFAULTS and explicit supported runtime flags
can be edited. Database values override process startup defaults, without touching
the environment or the constants copied into legacy economy modules.
"""
import json
import math
import os
import threading
import time

import balance

CACHE_TTL = 2.0
_lock = threading.RLock()
_cache = {}
_current = threading.local()
EXTRA_DEFAULTS = {
    "LAND_ENABLED": False,
    "CONSTRUCTION_PROJECTS_ENABLED": False,
    "MAINTENANCE_MODE": False,
    "CLIENT_FEATURE_HQ": True,
    "CLIENT_FEATURE_MAP": True,
    "CLIENT_FEATURE_MARKET": True,
    "CLIENT_FEATURE_CONTRACTS": True,
}
MONTH_GROUPS = {"labour", "migration", "taxes", "credit", "retail", "owner_spend",
                "transport", "zones", "quality", "population", "housing", "banks",
                "inflation", "construction"}
FLAGS = {"HOUSEHOLDS_ENABLED", "BANKS_ENABLED", "INFLATION_ENABLED", "TAX_EXTRAS_ENABLED",
         "NPC_NEW_KINDS", "LAND_ENABLED", "CONSTRUCTION_PROJECTS_ENABLED", "TAXES_ENABLED",
         "RETAIL_ENABLED", "RESIDENT_SPEND_TO_MARKET", "OWNER_SPEND_ENABLED"}
CLIENT_FLAGS = {name for name in EXTRA_DEFAULTS if name.startswith("CLIENT_FEATURE_")}
SENSITIVE = FLAGS | {"MAINTENANCE_MODE"}
# Safe bounded values are derived from the type and meaning; unsafe/unknown
# economic constants are not advertised until they have a live consumer.
LIVE_BALANCE = {
    "HOUSEHOLDS_ENABLED", "BANKS_ENABLED", "INFLATION_ENABLED", "TAX_EXTRAS_ENABLED",
    "NPC_NEW_KINDS", "RESIDENT_SPEND_TO_MARKET",
    "BASE_WAGE", "POPULATION_SCALE", "HH_SAVINGS_PPM",
    "HH_MIGRATION_PPM", "HH_PARTICIPATION_PPM", "HH_DEMAND_NUDGE_PPM",
    "HH_SKILL_PPM", "HH_HOUSING_STRESS", "HH_RECESSION",
    "BANK_BASE_RATE_YEAR", "BANK_RATE_MIN_YEAR", "BANK_RATE_MAX_YEAR",
    "INFLATION_MIN_YEAR", "INFLATION_MAX_YEAR", "INFLATION_PRICE_WEIGHT",
    "INFLATION_MONEY_WEIGHT", "LAND_TAX", "PAYROLL_TAX", "SECTOR_FEE",
    "TRUCK_CAPACITY", "TRUCK_PRICE", "TRUCK_UPKEEP", "TRUCK_COST_PER_KM",
    "RESEARCH_COST", "RESEARCH_MONTHS", "QUALITY_PRICE_STEP",
}
PERCENT_HINTS = ("TAX", "RATE", "SHARE", "WEIGHT", "LTV", "ELASTICITY",
                 "GROWTH", "MIGRATION", "INFLATION", "PARTICIPATION", "NUDGE")
def registry():
    groups = {key: group for group, names in balance.GROUPS.items() for key in names}
    defaults = {key: balance.DEFAULTS[key] for key in LIVE_BALANCE}
    defaults.update(EXTRA_DEFAULTS)
    result = {}
    for key, default in sorted(defaults.items()):
        group = groups.get(key, "client" if key.startswith("CLIENT_") else "features")
        if type(default) is bool:
            lo, hi, kind = None, None, "bool"
        elif type(default) is int:
            kind = "int"
            lo = 0
            hi = 1 if key == "NPC_NEW_KINDS" or key in ("HH_HOUSING_STRESS", "HH_RECESSION") else max(100, abs(default) * 10)
            if key.endswith("_PPM"):
                hi = 1000
            if key == "BASE_WAGE": lo, hi = 100, 100000
            if key == "POPULATION_SCALE": lo, hi = 1, 10000
        else:
            kind, lo, hi = "float", 0, 1 if any(s in key for s in PERCENT_HINTS) else max(1.0, abs(default) * 10)
        month = key not in CLIENT_FLAGS and key != "MAINTENANCE_MODE"
        result[key] = {
            "type": kind, "minimum": lo, "maximum": hi,
            "default": default, "group": group,
            "danger": "high" if key in SENSITIVE or month else "low",
            "apply_at": "next_month" if month else "now",
            "description": key.replace("_", " ").capitalize(),
        }
    return result

def ensure(db, ph):
    db.execute("""CREATE TABLE IF NOT EXISTS runtime_config_values(
       key TEXT PRIMARY KEY, value TEXT NOT NULL, apply_month BIGINT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS runtime_config_revisions(
       revision INTEGER PRIMARY KEY, at BIGINT NOT NULL, actor TEXT NOT NULL,
       comment TEXT NOT NULL, snapshot TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS runtime_config_state(
       id INTEGER PRIMARY KEY, revision INTEGER NOT NULL)""")
    db.execute("INSERT INTO runtime_config_state(id,revision) VALUES(1,0) ON CONFLICT(id) DO NOTHING")
    db.execute("""CREATE TABLE IF NOT EXISTS runtime_client(
       id INTEGER PRIMARY KEY, texts TEXT NOT NULL, min_version INTEGER NOT NULL,
       recommended_version INTEGER NOT NULL, patch_url TEXT NOT NULL)""")
    db.execute("INSERT INTO runtime_client(id,texts,min_version,recommended_version,patch_url) VALUES(1,'{}',0,0,'https://rikagro.ru/lunexeconom/admin/patch/manifest.json') ON CONFLICT(id) DO NOTHING")

def _validate(name, value):
    spec = registry().get(name)
    if spec is None:
        raise ValueError("unknown_parameter")
    kind = spec["type"]
    if kind == "bool":
        if type(value) is not bool: raise ValueError("invalid_type")
    elif kind == "int":
        if type(value) is not int: raise ValueError("invalid_type")
    else:
        if type(value) not in (float, int) or not math.isfinite(value): raise ValueError("invalid_type")
        value = float(value)
    lo, hi = spec["minimum"], spec["maximum"]
    if lo is not None and not lo <= value <= hi: raise ValueError("out_of_range")
    return value

def _initial(name):
    if name in EXTRA_DEFAULTS:
        default = EXTRA_DEFAULTS[name]
        raw = os.environ.get("LUNEX_RUNTIME_" + name)
        if raw is None:
            return default
        if type(default) is bool:
            return raw.strip().lower() in ("1", "true", "yes", "on")
        return default
    return balance.PARAMS[name]

def _rows(db):
    return {k: (json.loads(value), int(month))
            for k, value, month in db.execute("SELECT key,value,apply_month FROM runtime_config_values").fetchall()}

def _rev(db):
    return int(db.execute("SELECT revision FROM runtime_config_state WHERE id=1").fetchone()[0])

def current_month(db, now=None):
    row = db.execute("SELECT epoch,month_seconds,base_index FROM world_clock WHERE id=1").fetchone()
    if row is None: return 0
    timestamp = int(time.time()) if now is None else int(now)
    return int(row[2]) + max(0, timestamp - int(row[0])) // max(1, int(row[1]))

def values(db, month=None):
    month = current_month(db) if month is None else month
    rows = _rows(db)
    return {key: v for key, (v, apply) in rows.items() if apply <= month}

def get(name, base=None):
    active = getattr(_current, "values", None)
    if active is not None and name in active:
        return active[name]
    with _lock:
        cached = _cache.get(name)
        if cached and cached[0] >= time.monotonic():
            return cached[1]
    if base is not None: return base
    return _initial(name)

def synchronize(db, month=None):
    """Read once per processing context; values are immutable for the whole step."""
    selected = values(db, month)
    _current.values = selected
    return selected

def release():
    _current.values = None

def invalidate():
    with _lock: _cache.clear()

def snapshot(db):
    revision = _rev(db)
    rows = _rows(db)
    return {"revision": revision, "values": {key: {
        "value": value, "apply_month": apply} for key, (value, apply) in rows.items()}}

def describe(db, now=None):
    snap = snapshot(db)
    definitions = registry()
    month = current_month(db, now)
    return {"revision": snap["revision"], "month": month,
            "parameters": [{"key": key, **spec,
                "value": snap["values"].get(key, {}).get("value", _initial(key)),
                "effective": snap["values"].get(key, {}).get("apply_month", 0) <= month,
                "apply_month": snap["values"].get(key, {}).get("apply_month", 0)}
                for key, spec in definitions.items()]}

def revisions(db, limit=100):
    limit = max(1, min(int(limit), 100))
    # A constant validated LIMIT works with sqlite_util wrappers and psycopg.
    return [{"revision": int(r), "at": int(at), "actor": a, "comment": c, "snapshot": json.loads(s)}
            for r, at, a, c, s in db.execute(
                "SELECT revision,at,actor,comment,snapshot FROM runtime_config_revisions ORDER BY revision DESC LIMIT " + str(limit)).fetchall()]

def change(db, ph, changes, actor, ip, now, comment="", confirmed=False, expected_revision=None):
    if not isinstance(changes, dict) or not changes or len(changes) > 40:
        raise ValueError("invalid_changes")
    parsed = {name: _validate(name, value) for name, value in changes.items()}
    if any(registry()[name]["danger"] == "high" for name in parsed) and confirmed is not True:
        raise ValueError("confirmation_required")
    if type(comment) is not str or len(comment) > 200 or any(ord(c) < 32 for c in comment):
        raise ValueError("invalid_comment")
    before = snapshot(db)
    if expected_revision is not None and (type(expected_revision) is not int or expected_revision != before["revision"]):
        raise ValueError("revision_conflict")
    month = current_month(db, now)
    entries = {key: dict(value) for key, value in before["values"].items()}
    for name, value in parsed.items():
        entries[name] = {"value": value,
                         "apply_month": month + 1 if registry()[name]["apply_at"] == "next_month" else 0}
    return _write(db, ph, before, entries, actor, ip, now, comment or "Изменение настроек")

def _write(db, ph, before, entries, actor, ip, now, comment):
    for key in entries:
        _validate(key, entries[key]["value"])
    revision = before["revision"] + 1
    db.execute("DELETE FROM runtime_config_values")
    for key, item in sorted(entries.items()):
        db.execute("INSERT INTO runtime_config_values(key,value,apply_month) VALUES(%s,%s,%s)".replace("%s", ph),
                   (key, json.dumps(item["value"], ensure_ascii=False), int(item["apply_month"])))
    db.execute("UPDATE runtime_config_state SET revision=%s WHERE id=1".replace("%s", ph), (revision,))
    after = {"revision": revision, "values": entries}
    db.execute("INSERT INTO runtime_config_revisions(revision,at,actor,comment,snapshot) VALUES(%s,%s,%s,%s,%s)".replace("%s", ph),
               (revision, now, str(actor)[:64], comment, json.dumps(after, ensure_ascii=False, sort_keys=True)))
    import admin_api
    # The audit log has a 300-character limit. Store a concise difference, never secrets.
    changes = {k: {"was": before["values"].get(k), "now": entries.get(k)}
               for k in set(before["values"]) | set(entries) if before["values"].get(k) != entries.get(k)}
    admin_api.audit(db, ph, actor, "runtime_config", str(revision),
                    json.dumps(changes, ensure_ascii=False)[:300], ip, now)
    invalidate()
    return after

def rollback(db, ph, target, actor, ip, now, confirmed=False, expected_revision=None):
    if confirmed is not True: raise ValueError("confirmation_required")
    before = snapshot(db)
    if expected_revision is not None and expected_revision != before["revision"]:
        raise ValueError("revision_conflict")
    row = db.execute("SELECT snapshot FROM runtime_config_revisions WHERE revision=%s".replace("%s", ph), (target,)).fetchone()
    if row is None: raise ValueError("revision_not_found")
    old = json.loads(row[0])["values"]
    # Reissue a historical snapshot, but never reactivate values during the
    # running game month. Old pending schedules get moved to the next boundary.
    month = current_month(db, now)
    entries = {key: {"value": item["value"],
                     "apply_month": month + 1 if registry()[key]["apply_at"] == "next_month" else 0}
               for key, item in old.items()}
    return _write(db, ph, before, entries, actor, ip, now, "Откат к ревизии " + str(target))

def client_settings(db):
    row = db.execute("SELECT texts,min_version,recommended_version,patch_url FROM runtime_client WHERE id=1").fetchone()
    return {"texts": json.loads(row[0]), "min_version": int(row[1]),
            "recommended_version": int(row[2]), "patch_url": row[3]}

def client_update(db, ph, payload, actor, ip, now, confirmed=False, expected_revision=None):
    if confirmed is not True: raise ValueError("confirmation_required")
    if not isinstance(payload, dict) or not payload: raise ValueError("invalid_changes")
    before = snapshot(db)
    if expected_revision is not None and (type(expected_revision) is not int or expected_revision != before["revision"]):
        raise ValueError("revision_conflict")
    old = client_settings(db)
    new = dict(old)
    for key in payload:
        if key not in new: raise ValueError("unknown_parameter")
    new.update(payload)
    if not isinstance(new["texts"], dict) or len(new["texts"]) > 100: raise ValueError("invalid_texts")
    for key, val in new["texts"].items():
        if not isinstance(key, str) or not isinstance(val, str) or len(key) > 64 or len(val) > 512 or any(c in val for c in "<>"): raise ValueError("invalid_texts")
    if type(new["min_version"]) is not int or type(new["recommended_version"]) is not int or not 0 <= new["min_version"] <= new["recommended_version"] <= 10**9:
        raise ValueError("invalid_versions")
    if new["patch_url"] != "https://rikagro.ru/lunexeconom/admin/patch/manifest.json": raise ValueError("invalid_patch_url")
    db.execute("UPDATE runtime_client SET texts=%s,min_version=%s,recommended_version=%s,patch_url=%s WHERE id=1".replace("%s", ph),
               (json.dumps(new["texts"], ensure_ascii=False), new["min_version"], new["recommended_version"], new["patch_url"]))
    result = _write(db, ph, before, before["values"], actor, ip, now, "Клиентская конфигурация")
    import admin_api
    admin_api.audit(db, ph, actor, "runtime_client", "config",
                    json.dumps({"was": old, "now": new}, ensure_ascii=False)[:300], ip, now)
    return {"revision": result["revision"], **new}
