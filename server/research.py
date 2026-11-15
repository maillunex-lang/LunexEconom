"""Company research (quality, or thrift: less raw material). One track per company.

The project spends integer roubles up front and finishes after RESEARCH_MONTHS.
Until then production is unchanged. Ledger entries sum to zero (player vs system:research).
"""
import json
import uuid

import balance as balance_registry
import economy

TRACKS = ("quality", "thrift")
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS company_research("
    "id TEXT PRIMARY KEY, owner TEXT NOT NULL, track TEXT NOT NULL, cost BIGINT NOT NULL, "
    "start_month BIGINT NOT NULL, ready_month BIGINT NOT NULL, status TEXT NOT NULL)",
)


def _q(sql, ph):
    return sql.replace("%s", ph)


def advance(db, ph, month):
    """Mark projects whose waiting time is over. No-op when nobody is researching."""
    db.execute(_q("UPDATE company_research SET status='done' WHERE status='active' AND ready_month<=%s", ph), (month,))


def quality_owners(db, ph, month):
    """Companies whose quality research has already finished by ``month``."""
    rows = db.execute(_q(
        "SELECT owner FROM company_research WHERE track='quality' AND status='done' AND ready_month<=%s", ph),
        (month,)).fetchall()
    return {row[0] for row in rows}


def quality_bonus(db, ph, owner, month):
    row = db.execute(_q(
        "SELECT 1 FROM company_research WHERE owner=%s AND track='quality' AND status='done' AND ready_month<=%s", ph),
        (owner, month)).fetchone()
    return 1 if row else 0


def apply_input_relief(db, ph, companies, month):
    """Cut each input by RESEARCH_INPUT_RELIEF_PERMILLE when thrift research is done. Otherwise do nothing."""
    permille = int(balance_registry.get("RESEARCH_INPUT_RELIEF_PERMILLE"))
    if permille <= 0:
        return
    rows = db.execute(_q(
        "SELECT owner FROM company_research WHERE track='thrift' AND status='done' AND ready_month<=%s", ph),
        (month,)).fetchall()
    owners = {row[0] for row in rows}
    if not owners:
        return
    keep = 1000 - permille
    for owner in owners:
        company = companies.get(owner)
        if not company:
            continue
        company["needs"] = {}
        for reg in company["regional"].values():
            for product in list(reg["needs"]):
                reg["needs"][product] = reg["needs"][product] * keep // 1000
                company["needs"][product] = company["needs"].get(product, 0) + reg["needs"][product]


def start(db, ph, owner, payload, now, month):
    track = payload.get("track")
    request_id = payload.get("request_id")
    try:
        uuid.UUID(str(request_id))
    except (ValueError, TypeError, AttributeError):
        return 400, {"error": "invalid_request_id"}
    if track not in TRACKS:
        return 400, {"error": "invalid_track"}
    prev = db.execute(_q("SELECT response FROM commands WHERE owner=%s AND request_id=%s", ph), (owner, request_id)).fetchone()
    if prev:
        return 200, json.loads(prev[0])
    busy = db.execute(_q("SELECT 1 FROM company_research WHERE owner=%s AND track=%s", ph), (owner, track)).fetchone()
    if busy:
        return 409, {"error": "research_exists", "track": track}
    cost = int(balance_registry.get("RESEARCH_COST"))
    months = int(balance_registry.get("RESEARCH_MONTHS"))
    current = economy.ensure_wallet(db, ph, owner, now)
    if current < cost:
        return 402, {"error": "insufficient_funds", "cost": cost, "balance": current}
    economy.post(db, ph, "research", "Исследование: %s" % track,
                 [(economy.player_account(owner), -cost), ("system:research", cost)], now)
    ready = int(month) + months
    project_id = uuid.uuid4().hex
    db.execute(_q(
        "INSERT INTO company_research(id,owner,track,cost,start_month,ready_month,status) VALUES(%s,%s,%s,%s,%s,%s,%s)", ph),
        (project_id, owner, track, cost, int(month), ready, "active"))
    result = {"ok": True, "id": project_id, "track": track, "cost": cost, "start_month": int(month),
              "ready_month": ready, "status": "active", "balance": current - cost}
    db.execute(_q("INSERT INTO commands(owner,request_id,response) VALUES(%s,%s,%s)", ph),
               (owner, request_id, json.dumps(result, ensure_ascii=False)))
    return 201, result


def view(db, ph, owner):
    rows = db.execute(_q(
        "SELECT id,track,cost,start_month,ready_month,status FROM company_research WHERE owner=%s ORDER BY start_month,id", ph),
        (owner,)).fetchall()
    return {"projects": [{"id": i, "track": t, "cost": int(c), "start_month": int(s), "ready_month": int(r), "status": st}
                         for i, t, c, s, r, st in rows]}
