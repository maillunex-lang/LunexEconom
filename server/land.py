"""EX-03: server-authoritative land parcels. All write methods require the caller's
world-locked transaction (SQLite BEGIN IMMEDIATE / PG advisory lock 20261114).
Never modify historical buildings unless LAND_ENABLED=1.
"""
import json
import os
import time
import uuid

import clock
import economy
import geo
import regional_prices
import zoning

PARCEL_SIZE = 6
CELL_AREA_M2 = 400     # game map: one 20 x 20 metre cell
# Fraction of the residential market m2 price, in permille, paid for land per m2.
ZONE_PRICE_PERMILLE = {"center": 40, "suburb": 18, "industrial": 12, "open": 5}
RENT_PERMILLE = 10       # 1% of assessed land value per game month
VACANT_TAX_PERMILLE = 1  # 0.1% per game month; exempt for public holdings
AUCTION_STEP_PERMILLE = 50
BUYBACK_PREMIUM_PERMILLE = 100

COLUMNS = ("id", "px", "py", "city_id", "zone", "owner", "status",
           "price_mode", "fixed_price", "tenant", "lease_from", "lease_until", "rent_month",
           "created")
SCHEMA = (
    """CREATE TABLE IF NOT EXISTS land_parcels (
       id TEXT PRIMARY KEY, px INTEGER NOT NULL, py INTEGER NOT NULL,
       city_id TEXT NOT NULL, zone TEXT NOT NULL, owner TEXT NOT NULL,
       status TEXT NOT NULL DEFAULT 'available', price_mode TEXT NOT NULL DEFAULT 'market',
       fixed_price BIGINT NOT NULL DEFAULT 0, tenant TEXT,
       lease_from BIGINT NOT NULL DEFAULT 0, lease_until BIGINT NOT NULL DEFAULT 0,
       rent_month BIGINT NOT NULL DEFAULT 0,
       created BIGINT NOT NULL, UNIQUE(px,py))""",
    """CREATE TABLE IF NOT EXISTS land_auctions (
       id TEXT PRIMARY KEY, parcel_id TEXT NOT NULL REFERENCES land_parcels(id),
       seller TEXT NOT NULL, opening_bid BIGINT NOT NULL, min_step BIGINT NOT NULL,
       closes_month BIGINT NOT NULL, current_bid BIGINT NOT NULL DEFAULT 0,
       bidder TEXT, status TEXT NOT NULL DEFAULT 'open',
       winner TEXT, closed_month BIGINT)""",
    """CREATE TABLE IF NOT EXISTS land_bids (
       auction_id TEXT NOT NULL REFERENCES land_auctions(id), bidder TEXT NOT NULL,
       amount BIGINT NOT NULL, month BIGINT NOT NULL,
       PRIMARY KEY(auction_id,bidder,amount))""",
    """CREATE TABLE IF NOT EXISTS land_rezones (
       id TEXT PRIMARY KEY, parcel_id TEXT NOT NULL REFERENCES land_parcels(id),
       applicant TEXT NOT NULL, desired TEXT NOT NULL, status TEXT NOT NULL,
       submitted_month BIGINT NOT NULL, decided_month BIGINT, decision_by TEXT)""",
    """CREATE TABLE IF NOT EXISTS land_legacy_buildings (
       object_id TEXT NOT NULL REFERENCES buildings(id) ON DELETE CASCADE,
       parcel_id TEXT NOT NULL REFERENCES land_parcels(id),
       PRIMARY KEY(object_id,parcel_id))""",
    """CREATE TABLE IF NOT EXISTS land_months (
       month_index BIGINT PRIMARY KEY, rent_charged BIGINT NOT NULL,
       tax_charged BIGINT NOT NULL, leases_ended BIGINT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS land_auctions_state ON land_auctions(parcel_id,status)",
    "CREATE INDEX IF NOT EXISTS land_parcels_owner ON land_parcels(owner)",
)

def enabled():
    return os.environ.get("LAND_ENABLED", "0").lower() in ("1", "true", "yes")

def _sql(statement, ph):
    return statement.replace("%s", ph)

def ensure(db, ph):
    for statement in SCHEMA:
        db.execute(statement)

def _id(px, py):
    return f"{px}:{py}"

def parcel_for_cell(x, y):
    return x // PARCEL_SIZE, y // PARCEL_SIZE

def _valid_point(value):
    return type(value) is int and -10000 <= value <= 10000

def _place(db, ph, px, py):
    x = px * PARCEL_SIZE + PARCEL_SIZE // 2
    y = py * PARCEL_SIZE + PARCEL_SIZE // 2
    near = min(geo.cities(), key=lambda c: (x-c["x"])**2+(y-c["y"])**2)
    levels = zoning.levels(db, ph)
    zone = zoning.zone_at(x, y, levels)
    inside = zone != "open"
    return near["id"], zone, ("municipal:" + near["id"]) if inside else "state"

def get_parcel(db, ph, px, py, create=True):
    if not _valid_point(px) or not _valid_point(py):
        return None
    pid = _id(px, py)
    row = db.execute(_sql("SELECT "+",".join(COLUMNS)+" FROM land_parcels WHERE id=%s", ph), (pid,)).fetchone()
    if row is None and create:
        city_id, zone, owner = _place(db, ph, px, py)
        db.execute(_sql("""INSERT INTO land_parcels
          (id,px,py,city_id,zone,owner,created) VALUES(%s,%s,%s,%s,%s,%s,%s)
          ON CONFLICT(id) DO NOTHING""", ph),
          (pid, px, py, city_id, zone, owner, int(time.time())))
        row = db.execute(_sql("SELECT "+",".join(COLUMNS)+" FROM land_parcels WHERE id=%s", ph), (pid,)).fetchone()
    return dict(zip(COLUMNS, row)) if row else None

def price(parcel):
    if parcel["price_mode"] == "fixed":
        return int(parcel["fixed_price"])
    per_m2 = regional_prices.market_price_m2(parcel["city_id"])
    rate = ZONE_PRICE_PERMILLE[parcel["zone"]]
    return max(1, (per_m2 * CELL_AREA_M2 * PARCEL_SIZE**2 * rate + 500) // 1000)

def seller_account(owner):
    if owner.startswith("municipal:"):
        return economy.player_account(economy.CITY)
    if owner == "state":
        return economy.TREASURY
    return economy.player_account(owner)

def payer_account(owner):
    return economy.player_account(owner)

def _wallet(db, ph, owner, now):
    economy.ensure_wallet(db, ph, owner, now)
    return max(0, economy.balance(db, ph, owner) or 0)

def _transfer(db, ph, owner, recipient, amount, kind, memo, now):
    if amount <= 0:
        return False
    if _wallet(db, ph, owner, now) < amount:
        return False
    src, dst = payer_account(owner), recipient
    if src == dst:
        return False
    economy.post(db, ph, kind, memo, [(src, -amount), (dst, amount)], now)
    return True

def _command(db, ph, owner, payload):
    try:
        request_id = str(uuid.UUID(payload.get("request_id")))
    except (ValueError, TypeError, AttributeError):
        return None, (400, {"error": "invalid_request_id"})
    row = db.execute(_sql("SELECT response FROM commands WHERE owner=%s AND request_id=%s", ph),
                     (owner, request_id)).fetchone()
    if row:
        return request_id, (200, json.loads(row[0]))
    return request_id, None

def _remember(db, ph, owner, rid, result):
    db.execute(_sql("INSERT INTO commands(owner,request_id,response) VALUES(%s,%s,%s)", ph),
               (owner, rid, json.dumps(result, ensure_ascii=False)))

def _month(db, ph, now):
    return clock.state(db, ph, now)["month_index"]

def _parcel_from_payload(db, ph, payload):
    px, py = payload.get("px"), payload.get("py")
    if not _valid_point(px) or not _valid_point(py):
        return None
    return get_parcel(db, ph, px, py)

def _auction_open(db, ph, pid):
    return db.execute(_sql("SELECT id FROM land_auctions WHERE parcel_id=%s AND status='open' LIMIT 1", ph),
                      (pid,)).fetchone() is not None

def allowed_to_build(db, ph, owner, footprint, now):
    if not enabled():
        return None
    month = _month(db, ph, now)
    for px, py in sorted({parcel_for_cell(x, y) for x, y in footprint}):
        parcel = get_parcel(db, ph, px, py)
        if parcel["status"] != "available" or _auction_open(db, ph, parcel["id"]):
            return {"error": "land_unavailable", "parcel_id": parcel["id"]}
        municipal_build = owner == economy.CITY and parcel["owner"] == "municipal:" + parcel["city_id"]
        if not municipal_build and parcel["owner"] != owner and not (parcel["tenant"] == owner and int(parcel["lease_until"]) > month):
            return {"error": "land_not_owned", "parcel_id": parcel["id"], "owner": parcel["owner"]}
    return None

def view_chunk(db, ph, cx, cy):
    if not _valid_point(cx) or not _valid_point(cy):
        return 400, {"error": "invalid_query"}
    out = []
    # Chunks are 12x12 cells. Their four parcels align at 6-cell boundaries.
    for py in range(cy*2, cy*2+2):
        for px in range(cx*2, cx*2+2):
            p = get_parcel(db, ph, px, py)
            out.append({**p, "price": price(p)})
    return 200, {"enabled": enabled(), "parcel_size": PARCEL_SIZE, "parcels": out}

def buy(db, ph, owner, payload, now):
    rid, prev = _command(db, ph, owner, payload)
    if prev: return prev
    parcel = _parcel_from_payload(db, ph, payload)
    if parcel is None: return 400, {"error": "invalid_parcel"}
    if parcel["status"] != "available" or _auction_open(db, ph, parcel["id"]):
        return 409, {"error": "auction_or_reservation"}
    seller = parcel["owner"]
    if seller == owner: return 409, {"error": "already_owned"}
    if seller not in ("state", "municipal:"+parcel["city_id"]):
        return 409, {"error": "not_public_sale"}
    if parcel["tenant"] and parcel["lease_until"] > _month(db, ph, now):
        return 409, {"error": "active_lease"}
    x0, y0 = parcel["px"]*PARCEL_SIZE, parcel["py"]*PARCEL_SIZE
    if db.execute(_sql("SELECT 1 FROM cells WHERE x BETWEEN %s AND %s AND y BETWEEN %s AND %s LIMIT 1",ph),
                  (x0,x0+PARCEL_SIZE-1,y0,y0+PARCEL_SIZE-1)).fetchone():
        return 409, {"error": "occupied_land"}
    amount = price(parcel)
    if payload.get("max_price") is not None and (type(payload["max_price"]) is not int or amount > payload["max_price"]):
        return 409, {"error": "price_changed", "price": amount}
    if not _transfer(db, ph, owner, seller_account(seller), amount, "land_buy", "Продажа участка "+parcel["id"], now):
        return 402, {"error": "insufficient_funds", "price": amount}
    db.execute(_sql("UPDATE land_parcels SET owner=%s WHERE id=%s AND owner=%s AND status='available'", ph),
               (owner, parcel["id"], seller))
    result = {"ok": True, "parcel_id": parcel["id"], "owner": owner, "price": amount}
    _remember(db, ph, owner, rid, result)
    return 201, result

def lease(db, ph, owner, payload, now):
    rid, prev = _command(db, ph, owner, payload)
    if prev: return prev
    p = _parcel_from_payload(db, ph, payload)
    months = payload.get("months")
    if p is None or type(months) is not int or not 1 <= months <= 120:
        return 400, {"error": "invalid_lease"}
    month = _month(db, ph, now)
    if p["status"] != "available" or _auction_open(db, ph, p["id"]) or p["tenant"] and p["lease_until"] > month:
        return 409, {"error": "land_unavailable"}
    if p["owner"] not in ("state", "municipal:"+p["city_id"]) or p["owner"] == owner:
        return 403, {"error": "not_for_lease"}
    fee = max(1, price(p) * RENT_PERMILLE // 1000)
    if not _transfer(db, ph, owner, seller_account(p["owner"]), fee, "land_rent",
                     "Аренда участка "+p["id"], now):
        return 402, {"error": "insufficient_funds", "rent_month": fee}
    db.execute(_sql("""UPDATE land_parcels SET tenant=%s, lease_from=%s, lease_until=%s, rent_month=%s WHERE id=%s""", ph),
               (owner, month, month + months, fee, p["id"]))
    db.execute(_sql("INSERT INTO land_lease_payments(parcel_id,month_index) VALUES(%s,%s)",ph),
               (p["id"],month))
    # First month was paid at signing, so monthly() starts charging next month.
    result = {"ok": True, "parcel_id": p["id"], "tenant": owner,
              "rent_month": fee, "lease_until": month + months}
    _remember(db, ph, owner, rid, result)
    return 201, result

def start_auction(db, ph, mayor, payload, now):
    rid, prev = _command(db, ph, mayor, payload)
    if prev: return prev
    import city
    month = _month(db, ph, now)
    if not city.is_mayor(db, ph, mayor, month):
        return 403, {"error": "not_mayor"}
    p = _parcel_from_payload(db, ph, payload)
    months = payload.get("months", 2)
    if p is None or type(months) is not int or not 1 <= months <= 12:
        return 400, {"error": "invalid_auction"}
    if not p["owner"].startswith("municipal:") or p["status"] != "available" or _auction_open(db, ph, p["id"]) or p["tenant"]:
        return 409, {"error": "not_auctionable"}
    # Never auction an occupied pre-existing parcel, even before owners migrated.
    x0, y0 = p["px"]*PARCEL_SIZE, p["py"]*PARCEL_SIZE
    if db.execute(_sql("SELECT 1 FROM cells WHERE x BETWEEN %s AND %s AND y BETWEEN %s AND %s LIMIT 1", ph),
                  (x0, x0+PARCEL_SIZE-1, y0, y0+PARCEL_SIZE-1)).fetchone():
        return 409, {"error": "occupied_land"}
    aid = uuid.uuid4().hex
    start = price(p)
    step = max(1, start*AUCTION_STEP_PERMILLE//1000)
    db.execute(_sql("""INSERT INTO land_auctions(id,parcel_id,seller,opening_bid,min_step,closes_month)
         VALUES(%s,%s,%s,%s,%s,%s)""", ph), (aid, p["id"], p["owner"], start, step, month+months))
    db.execute(_sql("UPDATE land_parcels SET status='auction' WHERE id=%s", ph), (p["id"],))
    result = {"ok": True, "auction_id": aid, "parcel_id": p["id"],
              "start": start, "min_step": step, "closes_month": month+months}
    _remember(db, ph, mayor, rid, result)
    return 201, result

def auctions(db, ph):
    rows = db.execute("""SELECT id,parcel_id,opening_bid,min_step,closes_month,current_bid,
        bidder,status,winner FROM land_auctions ORDER BY closes_month,id LIMIT 200""").fetchall()
    keys = ("id", "parcel_id", "opening_bid", "min_step", "closes_month",
            "current_bid", "bidder", "status", "winner")
    return 200, {"enabled": enabled(), "auctions": [dict(zip(keys, r)) for r in rows]}

def bid(db, ph, owner, payload, now):
    rid, prev = _command(db, ph, owner, payload)
    if prev: return prev
    auction_id, amount = payload.get("auction_id"), payload.get("amount")
    if not isinstance(auction_id, str) or type(amount) is not int or amount <= 0:
        return 400, {"error": "invalid_bid"}
    row = db.execute(_sql("""SELECT parcel_id,opening_bid,min_step,closes_month,current_bid,bidder,status
      FROM land_auctions WHERE id=%s""", ph), (auction_id,)).fetchone()
    if not row: return 404, {"error": "not_found"}
    pid, opening, step, closes, current, previous, state = row
    if state != "open" or _month(db, ph, now) >= closes:
        return 409, {"error": "auction_closed"}
    p = db.execute(_sql("SELECT owner FROM land_parcels WHERE id=%s", ph), (pid,)).fetchone()
    if not p or p[0] == owner:
        return 403, {"error": "seller_cannot_bid"}
    if p[0].startswith("municipal:"):
        import city
        if city.is_mayor(db,ph,owner,_month(db,ph,now)):
            return 403, {"error": "conflict_of_interest"}
    required = current+step if current else opening
    if amount < required:
        return 409, {"error": "bid_too_low", "minimum": required}
    debit = amount - (current if previous == owner else 0)
    if _wallet(db, ph, owner, now) < debit:
        return 402, {"error": "insufficient_funds"}
    escrow = "system:land_escrow"
    if previous == owner:
        economy.post(db, ph, "land_bid", "Повышение ставки "+auction_id,
                     [(payer_account(owner), -debit), (escrow, debit)], now)
    else:
        entries = [(payer_account(owner), -amount), (escrow, amount-current)]
        if previous:
            entries.append((payer_account(previous), current))
        economy.post(db, ph, "land_bid", "Обеспечение ставки "+auction_id, entries, now)
    db.execute(_sql("UPDATE land_auctions SET current_bid=%s,bidder=%s WHERE id=%s", ph),
               (amount, owner, auction_id))
    db.execute(_sql("INSERT INTO land_bids(auction_id,bidder,amount,month) VALUES(%s,%s,%s,%s)", ph),
               (auction_id, owner, amount, _month(db, ph, now)))
    result = {"ok": True, "auction_id": auction_id, "amount": amount, "bidder": owner}
    _remember(db, ph, owner, rid, result)
    return 201, result

def cancel_auction(db, ph, owner, payload, now):
    """Municipality may cancel before closing; outstanding escrow returns to bidder."""
    rid, replay = _command(db, ph, owner, payload)
    if replay: return replay
    import city
    month = _month(db, ph, now)
    if not city.is_mayor(db, ph, owner, month):
        return 403, {"error":"not_mayor"}
    aid=payload.get("auction_id")
    if type(aid) is not str: return 400, {"error":"invalid_auction"}
    row=db.execute(_sql("SELECT parcel_id,current_bid,bidder,status FROM land_auctions WHERE id=%s",ph),
                   (aid,)).fetchone()
    if not row: return 404, {"error":"not_found"}
    pid,amount,bidder,status=row
    if status!="open" or month>=db.execute(_sql("SELECT closes_month FROM land_auctions WHERE id=%s",ph),
                                           (aid,)).fetchone()[0]:
        return 409, {"error":"auction_closed"}
    if bidder and amount:
        economy.post(db,ph,"land_auction_refund","Отмена торгов "+aid,
                     [("system:land_escrow",-amount),(payer_account(bidder),amount)],now)
    db.execute(_sql("UPDATE land_auctions SET status='cancelled',closed_month=%s WHERE id=%s",ph),
               (month,aid))
    db.execute(_sql("UPDATE land_parcels SET status='available' WHERE id=%s",ph),(pid,))
    result={"ok":True,"auction_id":aid,"status":"cancelled","refunded":amount}
    _remember(db,ph,owner,rid,result)
    return 200,result

def close_due(db, ph, month, now):
    rows = db.execute(_sql("""SELECT id,parcel_id,seller,current_bid,bidder FROM land_auctions
       WHERE status='open' AND closes_month<=%s ORDER BY id""", ph), (month,)).fetchall()
    for aid, pid, seller, amount, bidder in rows:
        if bidder and amount:
            economy.post(db, ph, "land_auction", "Закрытие аукциона "+aid,
                         [("system:land_escrow", -amount), (seller_account(seller), amount)], now)
            db.execute(_sql("UPDATE land_parcels SET owner=%s,status='available' WHERE id=%s", ph), (bidder, pid))
        else:
            db.execute(_sql("UPDATE land_parcels SET status='available' WHERE id=%s", ph), (pid,))
        db.execute(_sql("UPDATE land_auctions SET status='closed',winner=%s,closed_month=%s WHERE id=%s", ph),
                   (bidder, month, aid))
    return len(rows)

def rezone(db, ph, owner, payload, now):
    rid, prev = _command(db, ph, owner, payload)
    if prev: return prev
    p = _parcel_from_payload(db, ph, payload)
    desired = payload.get("zone")
    if p is None or desired not in ZONE_PRICE_PERMILLE:
        return 400, {"error": "invalid_rezone"}
    if p["owner"] != owner and p["tenant"] != owner:
        return 403, {"error": "not_landholder"}
    if p["status"] != "available":
        return 409, {"error": "land_unavailable"}
    rid_rezone = uuid.uuid4().hex
    db.execute(_sql("""INSERT INTO land_rezones(id,parcel_id,applicant,desired,status,submitted_month)
                     VALUES(%s,%s,%s,%s,'pending',%s)""", ph),
               (rid_rezone, p["id"], owner, desired, _month(db, ph, now)))
    result = {"ok": True, "application_id": rid_rezone, "status": "pending"}
    _remember(db, ph, owner, rid, result)
    return 201, result

def decide_rezone(db, ph, owner, payload, now):
    rid, prev = _command(db, ph, owner, payload)
    if prev: return prev
    import city
    month = _month(db, ph, now)
    if not city.is_mayor(db, ph, owner, month):
        return 403, {"error": "not_mayor"}
    appid, allow = payload.get("application_id"), payload.get("approve")
    if type(appid) is not str or type(allow) is not bool:
        return 400, {"error": "invalid_decision"}
    row = db.execute(_sql("SELECT parcel_id,desired,status FROM land_rezones WHERE id=%s", ph), (appid,)).fetchone()
    if not row: return 404, {"error": "not_found"}
    if row[2] != "pending": return 409, {"error": "already_decided"}
    if allow:
        db.execute(_sql("UPDATE land_parcels SET zone=%s WHERE id=%s", ph), (row[1], row[0]))
    db.execute(_sql("UPDATE land_rezones SET status=%s,decided_month=%s,decision_by=%s WHERE id=%s", ph),
               ("approved" if allow else "rejected", month, owner, appid))
    result = {"ok": True, "application_id": appid, "status": "approved" if allow else "rejected"}
    _remember(db, ph, owner, rid, result)
    return 200, result

def set_fixed_price(db, ph, owner, payload, now):
    rid, prev = _command(db, ph, owner, payload)
    if prev: return prev
    import city
    if not city.is_mayor(db, ph, owner, _month(db, ph, now)):
        return 403, {"error": "not_mayor"}
    p = _parcel_from_payload(db, ph, payload)
    amount = payload.get("price")
    if p is None or type(amount) is not int or amount < 0 or amount > 10**11:
        return 400, {"error": "invalid_price"}
    if not p["owner"].startswith("municipal:") or p["status"] != "available":
        return 409, {"error": "not_public_sale"}
    db.execute(_sql("UPDATE land_parcels SET price_mode=%s,fixed_price=%s WHERE id=%s", ph),
               ("fixed" if amount else "market", amount, p["id"]))
    result = {"ok": True, "parcel_id": p["id"], "price": amount or price(p)}
    _remember(db, ph, owner, rid, result)
    return 200, result

def buyback(db, ph, mayor, payload, now):
    """Regulated city purchase requires the owner's consent recorded on the request."""
    rid, prev = _command(db, ph, mayor, payload)
    if prev: return prev
    import city
    if not city.is_mayor(db, ph, mayor, _month(db, ph, now)):
        return 403, {"error": "not_mayor"}
    p = _parcel_from_payload(db, ph, payload)
    if p is None:return 400, {"error":"invalid_parcel"}
    if p["owner"].startswith("municipal:") or p["owner"] == "state":
        return 409, {"error": "not_private_land"}
    row = db.execute(_sql("""SELECT owner,expires_month,approved_price FROM land_buyback_consents
                         WHERE parcel_id=%s""",ph),(p["id"],)).fetchone()
    if not row or row[0]!=p["owner"] or row[1]<_month(db,ph,now) or p["status"]!="available" or p["tenant"]:
        return 409, {"error": "buyback_requires_owner_authorization"}
    amount = int(row[2])
    if not _transfer(db, ph, economy.CITY, payer_account(p["owner"]), amount,
                     "land_buyback", "Регулируемый выкуп "+p["id"], now):
        return 402, {"error": "city_budget_insufficient"}
    db.execute(_sql("UPDATE land_parcels SET owner=%s WHERE id=%s", ph),
               ("municipal:"+p["city_id"], p["id"]))
    db.execute(_sql("DELETE FROM land_buyback_consents WHERE parcel_id=%s",ph),(p["id"],))
    result = {"ok": True, "parcel_id": p["id"], "price": amount}
    _remember(db, ph, mayor, rid, result)
    return 201, result

def consent_buyback(db, ph, owner, payload, now):
    """Only the authenticated landholder may issue this authorization."""
    rid, prev = _command(db,ph,owner,payload)
    if prev:return prev
    p = _parcel_from_payload(db,ph,payload)
    if not p:return 400,{"error":"invalid_parcel"}
    if p["owner"]!=owner or p["status"]!="available" or p["tenant"]:
        return 403,{"error":"not_private_owner"}
    amount=price(p)*(1000+BUYBACK_PREMIUM_PERMILLE)//1000
    expires=_month(db,ph,now)+3
    db.execute(_sql("""INSERT INTO land_buyback_consents(parcel_id,owner,expires_month,approved_price)
       VALUES(%s,%s,%s,%s) ON CONFLICT(parcel_id) DO UPDATE SET
       owner=excluded.owner,expires_month=excluded.expires_month,
       approved_price=excluded.approved_price""",ph),
       (p["id"],owner,expires,amount))
    result={"ok":True,"parcel_id":p["id"],"approved_price":amount,"expires_month":expires}
    _remember(db,ph,owner,rid,result)
    return 201,result

def migrate_existing(db, ph):
    """Non-destructive ownership assignment for original buildings. Mixed owners remain
    legacy:shared and retain their buildings; no contested plot is put on sale."""
    if not enabled(): return 0
    rows = db.execute("""SELECT b.id,b.owner,c.x,c.y FROM buildings b
        JOIN cells c ON c.object_id=b.id
        WHERE NOT EXISTS(SELECT 1 FROM land_legacy_buildings l WHERE l.object_id=b.id)
        ORDER BY b.id""").fetchall()
    touched = set()
    for oid, owner, x, y in rows:
        px, py = parcel_for_cell(x, y)
        p = get_parcel(db, ph, px, py)
        db.execute(_sql("INSERT INTO land_legacy_buildings(object_id,parcel_id) VALUES(%s,%s) ON CONFLICT DO NOTHING", ph),
                   (oid, p["id"]))
        touched.add(p["id"])
    for pid in sorted(touched):
        owners = {r[0] for r in db.execute(_sql("""SELECT DISTINCT b.owner FROM buildings b
            JOIN land_legacy_buildings l ON l.object_id=b.id WHERE l.parcel_id=%s""", ph), (pid,))}
        if not owners: continue
        current = db.execute(_sql("SELECT owner FROM land_parcels WHERE id=%s", ph), (pid,)).fetchone()[0]
        if current.startswith("municipal:") or current == "state" or current.startswith("legacy:"):
            new_owner = next(iter(owners)) if len(owners) == 1 else "legacy:shared"
            db.execute(_sql("UPDATE land_parcels SET owner=%s WHERE id=%s", ph), (new_owner, pid))
    return len(touched)

def monthly(db, ph, month, now):
    if not enabled(): return {"rent": 0, "tax": 0, "expired": 0}
    if db.execute(_sql("SELECT 1 FROM land_months WHERE month_index=%s", ph), (month,)).fetchone():
        return {"rent": 0, "tax": 0, "expired": 0}
    migrate_existing(db, ph)
    close_due(db, ph, month, now)
    rents = taxes = expired = 0
    for pid, proprietor, tenant, from_month, until, amount in db.execute(
            "SELECT id,owner,tenant,lease_from,lease_until,rent_month FROM land_parcels WHERE tenant IS NOT NULL ORDER BY id").fetchall():
        if month < from_month:
            continue
        if month >= until:
            db.execute(_sql("UPDATE land_parcels SET tenant=NULL,lease_until=0,rent_month=0 WHERE id=%s", ph), (pid,))
            expired += 1
            continue
        # A lease signed this very month was paid at signing. No double charge.
        # month 0 is a valid start month; track it in land_lease_payments.
        paid = db.execute(_sql("SELECT 1 FROM land_lease_payments WHERE parcel_id=%s AND month_index=%s", ph), (pid, month)).fetchone()
        if paid: continue
        if _transfer(db, ph, tenant, seller_account(proprietor), amount, "land_rent", "Помесячная аренда "+pid, now):
            rents += amount
            db.execute(_sql("INSERT INTO land_lease_payments(parcel_id,month_index) VALUES(%s,%s)", ph), (pid,month))
        else:
            db.execute(_sql("UPDATE land_parcels SET tenant=NULL,lease_until=0,rent_month=0 WHERE id=%s", ph), (pid,))
            expired += 1
    for p_tuple in db.execute("SELECT "+",".join(COLUMNS)+" FROM land_parcels ORDER BY id").fetchall():
        p = dict(zip(COLUMNS, p_tuple))
        proprietor = p["owner"]
        if proprietor in ("state","legacy:shared") or proprietor.startswith(("municipal:","legacy:","town:")):
            continue
        x0,y0=p["px"]*PARCEL_SIZE,p["py"]*PARCEL_SIZE
        occupied=db.execute(_sql("""SELECT 1 FROM cells WHERE x BETWEEN %s AND %s
                              AND y BETWEEN %s AND %s LIMIT 1""",ph),
                            (x0,x0+PARCEL_SIZE-1,y0,y0+PARCEL_SIZE-1)).fetchone()
        if occupied: continue
        due=max(1,price(p)*VACANT_TAX_PERMILLE//1000)
        existing=db.execute(_sql("SELECT amount FROM land_tax_arrears WHERE parcel_id=%s",ph),
                            (p["id"],)).fetchone()
        balance_due=due+(int(existing[0]) if existing else 0)
        paid=min(max(0,economy.balance(db,ph,proprietor) or 0),balance_due)
        if paid:
            economy.post(db,ph,"land_tax","Налог на пустующую землю "+p["id"],
                         [(payer_account(proprietor),-paid),(economy.player_account(economy.CITY),paid)],now)
            taxes+=paid
        db.execute(_sql("""INSERT INTO land_tax_arrears(parcel_id,amount) VALUES(%s,%s)
            ON CONFLICT(parcel_id) DO UPDATE SET amount=excluded.amount""",ph),
                   (p["id"],balance_due-paid))
    db.execute(_sql("INSERT INTO land_months(month_index,rent_charged,tax_charged,leases_ended) VALUES(%s,%s,%s,%s)", ph),
               (month,rents,taxes,expired))
    return {"rent": rents, "tax": taxes, "expired": expired}

# Table kept separate to preserve a single charge per month (including month of signing).
LEASE_SCHEMA = """CREATE TABLE IF NOT EXISTS land_lease_payments (
   parcel_id TEXT NOT NULL REFERENCES land_parcels(id),month_index BIGINT NOT NULL,
   PRIMARY KEY(parcel_id,month_index))"""
CONSENT_SCHEMA = """CREATE TABLE IF NOT EXISTS land_buyback_consents (
   parcel_id TEXT PRIMARY KEY REFERENCES land_parcels(id), owner TEXT NOT NULL,
   expires_month BIGINT NOT NULL, approved_price BIGINT NOT NULL)"""
ARREARS_SCHEMA = """CREATE TABLE IF NOT EXISTS land_tax_arrears (
   parcel_id TEXT PRIMARY KEY REFERENCES land_parcels(id), amount BIGINT NOT NULL)"""
SCHEMA = SCHEMA + (LEASE_SCHEMA,CONSENT_SCHEMA,ARREARS_SCHEMA)
