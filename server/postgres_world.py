"""PostgreSQL-backed world operations. Transactions serialize conflicting footprints."""
import json
import time
import uuid
import psycopg
import postgres_db
import roads as road_rules
import zoning
import economy
import building_dimensions
import production
import taxes
import city
import clock
import contracts

CHUNK = 12
MAX_COORD = 10000
KINDS = {"farm":(2,2),"mine":(2,3),"factory":(3,2),"warehouse":(3,3),"shop":(2,2),"school":(3,2),"hospital":(3,3),"park":(2,2)}

def build(owner,payload):
    kind=payload.get("kind")
    x=payload.get("x")
    y=payload.get("y")
    request_id=payload.get("request_id")
    if kind not in KINDS or type(x) is not int or type(y) is not int or abs(x)>MAX_COORD or abs(y)>MAX_COORD:
        return 400,{"error":"invalid_build"}
    if (kind in economy.SOCIAL_KINDS)!=(owner==economy.CITY):
        return 403,{"error":"social_only_for_city" if kind in economy.SOCIAL_KINDS else "city_builds_social_only"}
    try:uuid.UUID(request_id)
    except (ValueError,TypeError,AttributeError):return 400,{"error":"invalid_request_id"}
    if payload.get("size") is not None:
        return 409,{"error":"building_size_economy_pending"}
    try:
        w,h=building_dimensions.footprint(kind,payload.get("size"))
    except ValueError:
        return 400,{"error":"invalid_building_size"}
    footprint=[(xx,yy) for xx in range(x,x+w) for yy in range(y,y+h)]
    if any(abs(xx)>MAX_COORD or abs(yy)>MAX_COORD for xx,yy in footprint):
        return 400,{"error":"outside_world"}
    with postgres_db.connect() as db:
        # One world lock guarantees idempotency and conflict checks across worker processes.
        db.execute("SELECT pg_advisory_xact_lock(20261114)")
        prev=db.execute("SELECT response FROM commands WHERE owner=%s AND request_id=%s",(owner,request_id)).fetchone()
        if prev:return 200,json.loads(prev[0])
        if db.execute("SELECT 1 FROM cells WHERE (x,y) IN ("+",".join(["(%s,%s)"]*len(footprint))+") LIMIT 1",
                      [v for cell in footprint for v in cell]).fetchone():
            return 409,{"error":"occupied"}
        wrong=zoning.check(db,"%s",kind,footprint)
        if wrong:
            return 409,zoning.error_body(wrong,kind)
        x0,x1,y0,y1=road_rules.search_box(footprint)
        dynamic={(rx,ry) for rx,ry in db.execute("SELECT x,y FROM roads WHERE x BETWEEN %s AND %s AND y BETWEEN %s AND %s",(x0,x1,y0,y1)).fetchall()}
        occupied={(a_,b_) for a_,b_ in db.execute("SELECT x,y FROM cells WHERE x BETWEEN %s AND %s AND y BETWEEN %s AND %s",(x0,x1,y0,y1)).fetchall()}
        error,path=road_rules.plan_access(footprint,dynamic,occupied,MAX_COORD)
        if error:return 409,{"error":error}
        new_roads=[c for c in path if not road_rules.is_base_road(*c) and c not in dynamic]
        oid=uuid.uuid4().hex
        now=int(time.time())
        clk=clock.state(db,"%s",now)
        production.advance(db,"%s",clk,now)
        paid,cost,balance=economy.charge_build(db,"%s",owner,kind,len(new_roads),now,payload.get("size"))
        if not paid:return 402,{"error":"insufficient_funds","cost":cost,"balance":balance}
        db.execute("INSERT INTO buildings(id,owner,kind,x,y,created) VALUES(%s,%s,%s,%s,%s,%s)",(oid,owner,kind,x,y,now))
        production.register_building(db,"%s",owner,oid,kind,clk)
        if payload.get("size") is not None:
            db.execute("INSERT INTO building_dimensions(object_id,width,height) VALUES(%s,%s,%s)",(oid,w,h))
        with db.cursor() as cursor:
            cursor.executemany("INSERT INTO cells(x,y,object_id) VALUES(%s,%s,%s)",[(xx,yy,oid) for xx,yy in footprint])
            if new_roads:
                cursor.executemany("INSERT INTO roads(x,y,owner,created) VALUES(%s,%s,%s,%s)",[(rx,ry,owner,now) for rx,ry in new_roads])
        events=[]
        for kind_name,cells in (("building_created",footprint),("road_changed",new_roads)):
            grouped={}
            for xx,yy in cells:grouped.setdefault((xx//CHUNK,yy//CHUNK),[]).append([xx,yy])
            for (cx,cy),coords in sorted(grouped.items()):
                version=db.execute("""INSERT INTO chunks(cx,cy,version) VALUES(%s,%s,1)
                   ON CONFLICT(cx,cy) DO UPDATE SET version=chunks.version+1 RETURNING version""",(cx,cy)).fetchone()[0]
                data={"object_id":oid,"owner":owner,"cells":coords}
                if kind_name=="building_created":data["building_kind"]=kind
                seq=db.execute("""INSERT INTO events(cx,cy,version,kind,payload)
                    VALUES(%s,%s,%s,%s,%s) RETURNING seq""",(cx,cy,version,kind_name,json.dumps(data))).fetchone()[0]
                events.append({"seq":seq,"cx":cx,"cy":cy,"version":version,"kind":kind_name,**data})
        result={"ok":True,"object_id":oid,"road_cells":len(new_roads),"cost":cost,"balance":balance,"events":events}
        db.execute("INSERT INTO commands(owner,request_id,response) VALUES(%s,%s,%s)",(owner,request_id,json.dumps(result)))
        return 201,result

def clock_state():
    with postgres_db.connect() as db:
        db.execute("SELECT pg_advisory_xact_lock(20261114)")
        return clock.state(db,"%s",int(time.time()))

def sell(owner,payload):
    object_id=payload.get("object_id")
    request_id=payload.get("request_id")
    if type(object_id) is not str or not 1<=len(object_id)<=64:return 400,{"error":"invalid_request"}
    try:uuid.UUID(request_id)
    except (ValueError,TypeError,AttributeError):return 400,{"error":"invalid_request_id"}
    with postgres_db.connect() as db:
        db.execute("SELECT pg_advisory_xact_lock(20261114)")
        prev=db.execute("SELECT response FROM commands WHERE owner=%s AND request_id=%s",(owner,request_id)).fetchone()
        if prev:return 200,json.loads(prev[0])
        now=int(time.time())
        production.advance(db,"%s",clock.state(db,"%s",now),now)
        status,result=production.sell_building(db,"%s",owner,object_id,now)
        if status==201:
            db.execute("INSERT INTO commands(owner,request_id,response) VALUES(%s,%s,%s)",(owner,request_id,json.dumps(result)))
        return status,result

def loan(owner,payload):
    request_id=payload.get("request_id")
    try:uuid.UUID(request_id)
    except (ValueError,TypeError,AttributeError):return 400,{"error":"invalid_request_id"}
    with postgres_db.connect() as db:
        db.execute("SELECT pg_advisory_xact_lock(20261114)")
        prev=db.execute("SELECT response FROM commands WHERE owner=%s AND request_id=%s",(owner,request_id)).fetchone()
        if prev:return 200,json.loads(prev[0])
        now=int(time.time())
        production.advance(db,"%s",clock.state(db,"%s",now),now)
        status,result=production.loan_command(db,"%s",owner,payload,now)
        if status==201:
            db.execute("INSERT INTO commands(owner,request_id,response) VALUES(%s,%s,%s)",(owner,request_id,json.dumps(result)))
        return status,result

def city_state(owner=None):
    with postgres_db.connect() as db:
        db.execute("SELECT pg_advisory_xact_lock(20261114)")
        now=int(time.time())
        clk=clock.state(db,"%s",now)
        production.advance(db,"%s",clk,now)
        return 200,production.city_view(db,"%s",clk,owner)

def city_candidacy(owner,payload):
    with postgres_db.connect() as db:
        db.execute("SELECT pg_advisory_xact_lock(20261114)")
        now=int(time.time())
        clk=clock.state(db,"%s",now)
        production.advance(db,"%s",clk,now)
        city.ensure_candidates(db,"%s",clk["month_index"])
        return city.register_candidate(db,"%s",owner,payload.get("profit_tax"),payload.get("property_tax"),payload.get("slogan"),clk["month_index"],now)

def city_vote(owner,payload):
    with postgres_db.connect() as db:
        db.execute("SELECT pg_advisory_xact_lock(20261114)")
        now=int(time.time())
        clk=clock.state(db,"%s",now)
        production.advance(db,"%s",clk,now)
        return city.cast_vote(db,"%s",owner,payload.get("candidate"),clk["month_index"])

def city_taxes(owner,payload):
    with postgres_db.connect() as db:
        db.execute("SELECT pg_advisory_xact_lock(20261114)")
        now=int(time.time())
        clk=clock.state(db,"%s",now)
        production.advance(db,"%s",clk,now)
        return city.set_taxes(db,"%s",owner,payload.get("profit_tax"),payload.get("property_tax"),clk["month_index"])

def city_build(owner,payload):
    with postgres_db.connect() as db:
        db.execute("SELECT pg_advisory_xact_lock(20261114)")
        clk=clock.state(db,"%s",int(time.time()))
        allowed=city.is_mayor(db,"%s",owner,clk["month_index"])
    if not allowed:return 403,{"error":"not_mayor"}
    if payload.get("kind") not in economy.SOCIAL_KINDS:return 400,{"error":"invalid_build"}
    return build(economy.CITY,payload)

def market_state():
    with postgres_db.connect() as db:
        db.execute("SELECT pg_advisory_xact_lock(20261114)")
        now=int(time.time())
        clk=clock.state(db,"%s",now)
        production.advance(db,"%s",clk,now)
        quotes=production.quote(db,"%s",clk)
        labor=production.labor_view(db,"%s",clk)
        import retail
        return 200,{"ok":True,"month_index":clk["month_index"],"products":quotes,"labor":labor,"taxes":taxes.view(db,"%s"),"competitors":production.competitors(db,"%s"),"retail":retail.snapshot(db,"%s",clk,quotes,labor.get("scale",1))}

def wallet(owner):
    with postgres_db.connect() as db:
        db.execute("SELECT pg_advisory_xact_lock(20261114)")
        now=int(time.time())
        return 200,production.wallet(db,"%s",owner,clock.state(db,"%s",now),now)

def _contract_command(owner, payload, fn):
    request_id=payload.get("request_id")
    try:uuid.UUID(request_id)
    except (ValueError,TypeError,AttributeError):return 400,{"error":"invalid_request_id"}
    with postgres_db.connect() as db:
        db.execute("SELECT pg_advisory_xact_lock(20261114)")
        prev=db.execute("SELECT response FROM commands WHERE owner=%s AND request_id=%s",(owner,request_id)).fetchone()
        if prev:return 200,json.loads(prev[0])
        now=int(time.time())
        clk=clock.state(db,"%s",now)
        production.advance(db,"%s",clk,now)
        status,result=fn(db,"%s",owner,payload,clk["month_index"],now)
        if status==201:
            db.execute("INSERT INTO commands(owner,request_id,response) VALUES(%s,%s,%s)",(owner,request_id,json.dumps(result)))
        return status,result

def contracts_state(owner):
    with postgres_db.connect() as db:
        db.execute("SELECT pg_advisory_xact_lock(20261114)")
        now=int(time.time())
        clk=clock.state(db,"%s",now)
        production.advance(db,"%s",clk,now)
        return 200,contracts.view(db,"%s",owner,clk["month_index"])

def contracts_offer(owner,payload):
    return _contract_command(owner,payload,contracts.offer)

def contracts_accept(owner,payload):
    return _contract_command(owner,payload,contracts.accept)

def contracts_cancel(owner,payload):
    return _contract_command(owner,payload,contracts.cancel)

def events(after):
    if type(after) is not int or after<0:return 400,{"error":"invalid_cursor"}
    with postgres_db.connect() as db:
        rows=db.execute("SELECT seq,cx,cy,version,kind,payload FROM events WHERE seq>%s ORDER BY seq LIMIT 100",(after,)).fetchall()
        latest=db.execute("SELECT COALESCE(MAX(seq),0) FROM events").fetchone()[0]
    items=[road_rules.event_item(s,cx,cy,v,kind,payload) for s,cx,cy,v,kind,payload in rows]
    return 200,{"events":items,"cursor":items[-1]["seq"] if items else after,"latest":latest,"has_more":bool(items and items[-1]["seq"]<latest)}

def chunk(cx,cy):
    if type(cx) is not int or type(cy) is not int or abs(cx)>1000 or abs(cy)>1000:
        return 400,{"error":"invalid_chunk"}
    with postgres_db.connect() as db:
        row=db.execute("SELECT version FROM chunks WHERE cx=%s AND cy=%s",(cx,cy)).fetchone()
        cells=db.execute("""SELECT c.x,c.y,b.kind,b.id,b.owner FROM cells c JOIN buildings b ON c.object_id=b.id
          WHERE c.x>=%s AND c.x<%s AND c.y>=%s AND c.y<%s ORDER BY c.x,c.y""",
          (cx*CHUNK,(cx+1)*CHUNK,cy*CHUNK,(cy+1)*CHUNK)).fetchall()
        rds=db.execute("SELECT x,y,owner FROM roads WHERE x>=%s AND x<%s AND y>=%s AND y<%s ORDER BY x,y",(cx*CHUNK,(cx+1)*CHUNK,cy*CHUNK,(cy+1)*CHUNK)).fetchall()
    items=[{"x":x,"y":y,"kind":"building_created","building_kind":kind,"object_id":oid,"owner":owner} for x,y,kind,oid,owner in cells]
    items+=[{"x":x,"y":y,"kind":"road_changed","object_id":"","owner":owner} for x,y,owner in rds]
    return 200,{"cx":cx,"cy":cy,"version":row[0] if row else 0,"cells":items}


# Read-only company statistics. Never acquire the world mutation lock or advance time.
def stats_leaderboard(owner, by="networth"):
    import stats
    with postgres_db.connect() as db:
        db.execute("SET TRANSACTION READ ONLY")
        return stats.leaderboard(db, "%s", owner, by)


def stats_feed(owner, after=0):
    import stats
    with postgres_db.connect() as db:
        db.execute("SET TRANSACTION READ ONLY")
        return stats.feed(db, "%s", owner, after)


def soc_post(owner, path, payload, client):
    import social
    with postgres_db.connect() as db:
        db.execute("SELECT pg_advisory_xact_lock(20261114)")
        now = int(time.time())
        clk = clock.state(db, "%s", now)
        production.advance(db, "%s", clk, now)
        social.distribute_pending(db, "%s", clk, now)
        return social.perform_post(db, "%s", owner, path, payload, client, now, clk)


def soc_get(owner, path, query):
    import clock as game_clock
    import social
    args = {}
    for key, values in query.items():
        if len(values) != 1:
            return 400, {"error": "invalid_query"}
        args[key] = values[0]
    with postgres_db.connect() as db:
        if path in social.READ_ONLY:
            db.execute("SET TRANSACTION READ ONLY")
            row = db.execute("SELECT epoch,month_seconds,base_index FROM world_clock WHERE id=1").fetchone()
            if row is not None:
                args["month"] = str(game_clock.month_index((int(row[0]), int(row[1]), int(row[2])), int(time.time())))
            return social.perform_get(db, "%s", owner, path, args, None)
        db.execute("SELECT pg_advisory_xact_lock(20261114)")
        now = int(time.time())
        clk = clock.state(db, "%s", now)
        production.advance(db, "%s", clk, now)
        social.distribute_pending(db, "%s", clk, now)
        return social.perform_get(db, "%s", owner, path, args, clk)


def admin_request(method, path, args, payload, ctx):
    import admin_api
    import auth
    with postgres_db.connect() as db:
        if method == "POST":
            db.execute("SELECT pg_advisory_xact_lock(20261114)")
        else:
            db.execute("SET TRANSACTION READ ONLY")
        return admin_api.handle(db, "%s", method, path, args, payload, ctx, int(time.time()), auth)


def announcement_state():
    import admin_api
    with postgres_db.connect() as db:
        db.execute("SET TRANSACTION READ ONLY")
        return admin_api.announcement(db, "%s")
