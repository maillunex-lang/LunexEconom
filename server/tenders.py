"""EX-04 municipal construction procurement: small direct orders and ranked tenders.
No municipal cash is debited until a project is actually placed.
"""
import uuid

import city
import city_catalog
import clock
import contractors
import construction_projects
import economy
import geo
import land

SMALL_ORDER_LIMIT = 200_000   # game roubles, catalogue estimate
MAX_TENDER_MONTHS = 12

def _q(sql, ph):
    return sql.replace("%s", ph)

def ensure(db,ph):
    db.execute("""CREATE TABLE IF NOT EXISTS tenders (
       id TEXT PRIMARY KEY, city_id TEXT NOT NULL, object_key TEXT NOT NULL,
       x INTEGER NOT NULL, y INTEGER NOT NULL, budget BIGINT NOT NULL,
       created_month BIGINT NOT NULL, closes_month BIGINT NOT NULL,
       status TEXT NOT NULL, winner TEXT, project_id TEXT,
       winning_price BIGINT, winning_months INTEGER, failure_reason TEXT)""")
    db.execute("""CREATE TABLE IF NOT EXISTS tender_bids (
       tender_id TEXT NOT NULL REFERENCES tenders(id),contractor_id TEXT NOT NULL
       REFERENCES contractors(id), bidder TEXT NOT NULL, price BIGINT NOT NULL,
       months INTEGER NOT NULL, created_month BIGINT NOT NULL,
       PRIMARY KEY(tender_id,contractor_id))""")

def _record(row):
    names=("id","city_id","object_key","x","y","budget","created_month",
           "closes_month","status","winner","project_id","winning_price","winning_months","failure_reason")
    return dict(zip(names,row))

def view(db,ph,owner=None):
    out=[_record(r) for r in db.execute(
        "SELECT * FROM tenders ORDER BY created_month DESC,id DESC LIMIT 100").fetchall()]
    return 200,{"enabled":construction_projects.enabled(),"tenders":out}

def _candidate(db,ph,t):
    bids=db.execute(_q("""SELECT contractor_id,bidder,price,months FROM tender_bids
          WHERE tender_id=%s ORDER BY price ASC,months ASC,contractor_id ASC""",ph),
          (t["id"],)).fetchall()
    return next((bid for bid in bids if contractors.available(db,ph,bid[0])),None)

def _award(db,ph,t,now):
    if t["status"] not in ("open","pending_funding"):return False
    if t["budget"]<SMALL_ORDER_LIMIT:
        available=[r for r in contractors.view(db,ph)[1]["contractors"] if r["id"].startswith("npc:") and r["active"] and r["busy"]<r["capacity"]]
        chosen=available[0] if available else None
        # A direct small purchase goes to the first available NPC contractor at the public estimate.
        bid=(chosen["id"],chosen["owner"],t["budget"],city_catalog.get(t["object_key"])["build_months"]) if chosen else None
    else:
        bid=_candidate(db,ph,t)
    if not bid:
        if t["status"]=="open":
            db.execute(_q("UPDATE tenders SET status='no_bids',failure_reason='no_available_contractors' WHERE id=%s",ph),(t["id"],))
        return False
    cid,bidder,amount,months=bid
    payload={"object_id":t["object_key"],"x":t["x"],"y":t["y"],
             "city_id":t["city_id"],"contractor_id":cid,
             "request_id":str(uuid.uuid5(uuid.NAMESPACE_URL,"lunexeconom:tender:"+t["id"]))}
    status,body=construction_projects.create(db,ph,economy.CITY,payload,now,
                                            tender_price=amount,tender_months=months)
    if status==402:
        db.execute(_q("UPDATE tenders SET status='pending_funding',failure_reason='insufficient_funds' WHERE id=%s",ph),(t["id"],))
        return False
    if status!=201 and status!=200:
        # Preserve a safe diagnostic for the mayor; do not charge for failed placement.
        db.execute(_q("UPDATE tenders SET status='placement_failed',failure_reason=%s WHERE id=%s",ph),
                   (body.get("error","placement_failed"),t["id"]))
        return False
    db.execute(_q("""UPDATE tenders SET status='awarded',winner=%s,project_id=%s,
                    winning_price=%s,winning_months=%s WHERE id=%s""",ph),
               (cid,body["project_id"],amount,months,t["id"]))
    return True

def create(db,ph,owner,payload,now):
    rid,replay=land._command(db,ph,owner,payload)
    if replay:return replay
    month=clock.state(db,ph,now)["month_index"]
    if not city.is_mayor(db,ph,owner,month):return 403,{"error":"not_mayor"}
    if not land.enabled() or not construction_projects.enabled():
        return 409,{"error":"land_and_projects_required"}
    key,x,y=payload.get("object_id"),payload.get("x"),payload.get("y")
    duration=payload.get("months",2)
    if type(key) is not str or not land._valid_point(x) or not land._valid_point(y) or type(duration) is not int or not 1<=duration<=MAX_TENDER_MONTHS:
        return 400,{"error":"invalid_tender"}
    item=city_catalog.get(key)
    if not item or item["category"]=="housing":
        return 400,{"error":"not_public_catalog_object"}
    city_id=construction_projects._location(x,y)
    if payload.get("city_id",city_id)!=city_id:return 409,{"error":"city_mismatch"}
    cost=city_catalog.cost_in(key,city_id)
    if not cost:return 400,{"error":"invalid_cost"}
    tid=uuid.uuid4().hex
    state="open"
    db.execute(_q("""INSERT INTO tenders
       (id,city_id,object_key,x,y,budget,created_month,closes_month,status)
       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",ph),
       (tid,city_id,key,x,y,cost,month,month+duration,state))
    # NPC firms participate under the same deadline and capacity constraints as players.
    # Their offers are deterministic regional estimates rather than cash subsidies.
    if cost>=SMALL_ORDER_LIMIT:
        for contractor in contractors.view(db,ph)[1]["contractors"]:
            if not contractor["id"].startswith("npc:") or not contractor["active"] or contractor["busy"]>=contractor["capacity"]:
                continue
            premium=(1000-contractor["quality_permille"])//4
            offer=max(1,cost*(1000-premium)//1000)
            months=item["build_months"]+(1000-contractor["quality_permille"])//100
            db.execute(_q("""INSERT INTO tender_bids
              (tender_id,contractor_id,bidder,price,months,created_month)
              VALUES(%s,%s,%s,%s,%s,%s)""",ph),
              (tid,contractor["id"],contractor["owner"],offer,months,month))
    result={"ok":True,"tender_id":tid,"budget":cost,"closes_month":month+duration,
            "procedure":"direct" if cost<SMALL_ORDER_LIMIT else "competitive"}
    land._remember(db,ph,owner,rid,result)
    if cost<SMALL_ORDER_LIMIT:
        t=_record(db.execute(_q("SELECT * FROM tenders WHERE id=%s",ph),(tid,)).fetchone())
        _award(db,ph,t,now)
    return 201,result

def bid(db,ph,owner,payload,now):
    rid,replay=land._command(db,ph,owner,payload)
    if replay:return replay
    tid,cid=payload.get("tender_id"),payload.get("contractor_id")
    amount,months=payload.get("price"),payload.get("months")
    if type(tid) is not str or type(cid) is not str or type(amount) is not int or type(months) is not int or amount<=0 or not 1<=months<=MAX_TENDER_MONTHS:
        return 400,{"error":"invalid_bid"}
    trow=db.execute(_q("SELECT * FROM tenders WHERE id=%s",ph),(tid,)).fetchone()
    if not trow:return 404,{"error":"not_found"}
    t=_record(trow)
    month=clock.state(db,ph,now)["month_index"]
    if t["status"]!="open" or month>=t["closes_month"]:
        return 409,{"error":"tender_closed"}
    if amount>t["budget"]:return 409,{"error":"over_budget","budget":t["budget"]}
    if city.is_mayor(db,ph,owner,month):return 403,{"error":"conflict_of_interest"}
    contractor=contractors.available(db,ph,cid)
    if not contractor or contractor["owner"]!=owner:
        return 403,{"error":"not_available_contractor"}
    existing=db.execute(_q("SELECT price FROM tender_bids WHERE tender_id=%s AND contractor_id=%s",ph),(tid,cid)).fetchone()
    if existing and amount>=existing[0]:
        return 409,{"error":"offer_must_improve"}
    db.execute(_q("""INSERT INTO tender_bids(tender_id,contractor_id,bidder,price,months,created_month)
         VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(tender_id,contractor_id)
         DO UPDATE SET price=excluded.price,months=excluded.months,created_month=excluded.created_month""",ph),
         (tid,cid,owner,amount,months,month))
    result={"ok":True,"tender_id":tid,"contractor_id":cid,"price":amount,"months":months}
    land._remember(db,ph,owner,rid,result)
    return 201,result

def monthly(db,ph,month,now):
    if not construction_projects.enabled():return {"awarded":0}
    rows=db.execute(_q("""SELECT * FROM tenders WHERE
      (status='open' AND closes_month<=%s) OR status='pending_funding'
      ORDER BY id""",ph),(month,)).fetchall()
    awarded=0
    for row in rows:
        if _award(db,ph,_record(row),now):awarded+=1
    db.execute("""UPDATE tenders SET status='complete'
          WHERE status='awarded' AND project_id IN
          (SELECT id FROM construction_projects WHERE status='complete')""")
    return {"awarded":awarded}
