"""LunexEconom isolated multiplayer API (alpha). No financial simulation until server rules exist."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
import json
import os
import sqlite3
import threading
import time
import uuid
import auth
import sqlite_util
import roads as road_rules
import economy
import production
import taxes
import city
import npc
import clock
import contracts
import stats
import social
if os.environ.get('LUNEX_DB_ENGINE') == 'postgres':
    import postgres_world
    import postgres_db

DB = os.environ.get("LUNEX_WORLD_DB", "/home/gamedev/projects/LunexEconom-server/world.sqlite3")
CHUNK = 12
MAX_COORD = 10000
KINDS = {"farm":(2,2), "mine":(2,3), "factory":(3,2), "warehouse":(3,3), "shop":(2,2), "school":(3,2), "hospital":(3,3), "park":(2,2)}
LOCK = threading.RLock()

def connect():
    db = sqlite_util.open_db(DB)
    try:
        _prepare(db)
    except BaseException:
        db.close()
        raise
    return db

def _prepare(db):
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=10000")
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("CREATE TABLE IF NOT EXISTS buildings(id TEXT PRIMARY KEY,owner TEXT NOT NULL,kind TEXT NOT NULL,x INTEGER NOT NULL,y INTEGER NOT NULL,created INTEGER NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS cells(x INTEGER NOT NULL,y INTEGER NOT NULL,object_id TEXT NOT NULL REFERENCES buildings(id),PRIMARY KEY(x,y))")
    db.execute("CREATE TABLE IF NOT EXISTS chunks(cx INTEGER NOT NULL,cy INTEGER NOT NULL,version INTEGER NOT NULL,PRIMARY KEY(cx,cy))")
    db.execute("CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,cx INTEGER NOT NULL,cy INTEGER NOT NULL,version INTEGER NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS roads(x INTEGER NOT NULL,y INTEGER NOT NULL,owner TEXT NOT NULL,created INTEGER NOT NULL,PRIMARY KEY(x,y))")
    db.execute("CREATE TABLE IF NOT EXISTS commands(owner TEXT NOT NULL,request_id TEXT NOT NULL,response TEXT NOT NULL,PRIMARY KEY(owner,request_id))")
    for statement in economy.SCHEMA + clock.SCHEMA + social.SCHEMA:
        db.execute(statement)
    db.commit()


def build(owner, payload):
    kind=payload.get("kind")
    x=payload.get("x")
    y=payload.get("y")
    request_id=payload.get("request_id")
    if kind not in KINDS or type(x) is not int or type(y) is not int or abs(x)>MAX_COORD or abs(y)>MAX_COORD:
        return 400,{"error":"invalid_build"}
    if (kind in economy.SOCIAL_KINDS)!=(owner==economy.CITY):
        return 403,{"error":"social_only_for_city" if kind in economy.SOCIAL_KINDS else "city_builds_social_only"}
    try:
        uuid.UUID(request_id)
    except (ValueError, TypeError, AttributeError):
        return 400,{"error":"invalid_request_id"}
    w,h=KINDS[kind]
    footprint=[(xx,yy) for xx in range(x,x+w) for yy in range(y,y+h)]
    if any(abs(xx)>MAX_COORD or abs(yy)>MAX_COORD for xx,yy in footprint):
        return 400,{"error":"outside_world"}
    with LOCK, connect() as db:
        db.execute("BEGIN IMMEDIATE")
        prev=db.execute("SELECT response FROM commands WHERE owner=? AND request_id=?",(owner,request_id)).fetchone()
        if prev:
            return 200,json.loads(prev[0])
        if any(db.execute("SELECT 1 FROM cells WHERE x=? AND y=?",(xx,yy)).fetchone() for xx,yy in footprint):
            return 409,{"error":"occupied"}
        x0,x1,y0,y1=road_rules.search_box(footprint)
        dynamic={(rx,ry) for rx,ry in db.execute("SELECT x,y FROM roads WHERE x BETWEEN ? AND ? AND y BETWEEN ? AND ?",(x0,x1,y0,y1))}
        occupied={(cx_,cy_) for cx_,cy_ in db.execute("SELECT x,y FROM cells WHERE x BETWEEN ? AND ? AND y BETWEEN ? AND ?",(x0,x1,y0,y1))}
        error,path=road_rules.plan_access(footprint,dynamic,occupied,MAX_COORD)
        if error:
            return 409,{"error":error}
        new_roads=[c for c in path if not road_rules.is_base_road(*c) and c not in dynamic]
        object_id=uuid.uuid4().hex
        now=int(time.time())
        clk=clock.state(db,"?",now)
        production.advance(db,"?",clk,now)
        paid,cost,balance=economy.charge_build(db,"?",owner,kind,len(new_roads),now)
        if not paid:
            return 402,{"error":"insufficient_funds","cost":cost,"balance":balance}
        db.execute("INSERT INTO buildings VALUES(?,?,?,?,?,?)",(object_id,owner,kind,x,y,now))
        production.register_building(db,"?",owner,object_id,kind,clk)
        db.executemany("INSERT INTO cells VALUES(?,?,?)",[(xx,yy,object_id) for xx,yy in footprint])
        db.executemany("INSERT INTO roads VALUES(?,?,?,?)",[(rx,ry,owner,now) for rx,ry in new_roads])
        events=[]
        for kind_name,cells in (("building_created",footprint),("road_changed",new_roads)):
            grouped={}
            for xx,yy in cells:
                grouped.setdefault((xx//CHUNK,yy//CHUNK),[]).append([xx,yy])
            for (cx,cy),coords in sorted(grouped.items()):
                db.execute("INSERT INTO chunks VALUES(?,?,1) ON CONFLICT(cx,cy) DO UPDATE SET version=version+1",(cx,cy))
                version=db.execute("SELECT version FROM chunks WHERE cx=? AND cy=?",(cx,cy)).fetchone()[0]
                data={"object_id":object_id,"owner":owner,"cells":coords}
                if kind_name=="building_created":data["building_kind"]=kind
                payload=json.dumps(data)
                seq=db.execute("INSERT INTO events(cx,cy,version,kind,payload) VALUES(?,?,?,?,?)",(cx,cy,version,kind_name,payload)).lastrowid
                events.append({"seq":seq,"cx":cx,"cy":cy,"version":version,"kind":kind_name,**data})
        result={"ok":True,"object_id":object_id,"road_cells":len(new_roads),"cost":cost,"balance":balance,"events":events}
        db.execute("INSERT INTO commands VALUES(?,?,?)",(owner,request_id,json.dumps(result)))
        db.commit()
        return 201,result

def clock_state():
    with LOCK, connect() as db:
        db.execute("BEGIN IMMEDIATE")
        result=clock.state(db,"?",int(time.time()))
        db.commit()
    return result

def sell(owner,payload):
    object_id=payload.get("object_id")
    request_id=payload.get("request_id")
    if type(object_id) is not str or not 1<=len(object_id)<=64:return 400,{"error":"invalid_request"}
    try:uuid.UUID(request_id)
    except (ValueError,TypeError,AttributeError):return 400,{"error":"invalid_request_id"}
    with LOCK, connect() as db:
        db.execute("BEGIN IMMEDIATE")
        prev=db.execute("SELECT response FROM commands WHERE owner=? AND request_id=?",(owner,request_id)).fetchone()
        if prev:return 200,json.loads(prev[0])
        now=int(time.time())
        production.advance(db,"?",clock.state(db,"?",now),now)
        status,result=production.sell_building(db,"?",owner,object_id,now)
        if status==201:
            db.execute("INSERT INTO commands VALUES(?,?,?)",(owner,request_id,json.dumps(result)))
        db.commit()
        return status,result

def loan(owner,payload):
    request_id=payload.get("request_id")
    try:uuid.UUID(request_id)
    except (ValueError,TypeError,AttributeError):return 400,{"error":"invalid_request_id"}
    with LOCK, connect() as db:
        db.execute("BEGIN IMMEDIATE")
        prev=db.execute("SELECT response FROM commands WHERE owner=? AND request_id=?",(owner,request_id)).fetchone()
        if prev:return 200,json.loads(prev[0])
        now=int(time.time())
        production.advance(db,"?",clock.state(db,"?",now),now)
        status,result=production.loan_command(db,"?",owner,payload,now)
        if status==201:
            db.execute("INSERT INTO commands VALUES(?,?,?)",(owner,request_id,json.dumps(result)))
        db.commit()
        return status,result

def city_state(owner=None):
    with LOCK, connect() as db:
        db.execute("BEGIN IMMEDIATE")
        now=int(time.time())
        clk=clock.state(db,"?",now)
        production.advance(db,"?",clk,now)
        result=production.city_view(db,"?",clk,owner)
        db.commit()
    return 200,result

def city_candidacy(owner,payload):
    with LOCK, connect() as db:
        db.execute("BEGIN IMMEDIATE")
        now=int(time.time())
        clk=clock.state(db,"?",now)
        production.advance(db,"?",clk,now)
        city.ensure_candidates(db,"?",clk["month_index"])
        status,result=city.register_candidate(db,"?",owner,payload.get("profit_tax"),payload.get("property_tax"),payload.get("slogan"),clk["month_index"],now)
        db.commit()
    return status,result

def city_vote(owner,payload):
    with LOCK, connect() as db:
        db.execute("BEGIN IMMEDIATE")
        now=int(time.time())
        clk=clock.state(db,"?",now)
        production.advance(db,"?",clk,now)
        status,result=city.cast_vote(db,"?",owner,payload.get("candidate"),clk["month_index"])
        db.commit()
    return status,result

def city_taxes(owner,payload):
    with LOCK, connect() as db:
        db.execute("BEGIN IMMEDIATE")
        now=int(time.time())
        clk=clock.state(db,"?",now)
        production.advance(db,"?",clk,now)
        status,result=city.set_taxes(db,"?",owner,payload.get("profit_tax"),payload.get("property_tax"),clk["month_index"])
        db.commit()
    return status,result

def city_build(owner,payload):
    """The mayor orders a social building; it is paid from the city budget through the normal build path."""
    with LOCK, connect() as db:
        db.execute("BEGIN IMMEDIATE")
        now=int(time.time())
        clk=clock.state(db,"?",now)
        allowed=city.is_mayor(db,"?",owner,clk["month_index"])
        db.commit()
    if not allowed:return 403,{"error":"not_mayor"}
    if payload.get("kind") not in economy.SOCIAL_KINDS:return 400,{"error":"invalid_build"}
    return build(economy.CITY,payload)

def market_state():
    with LOCK, connect() as db:
        db.execute("BEGIN IMMEDIATE")
        now=int(time.time())
        clk=clock.state(db,"?",now)
        production.advance(db,"?",clk,now)
        quotes=production.quote(db,"?",clk)
        labor=production.labor_view(db,"?",clk)
        import retail
        result={"ok":True,"month_index":clk["month_index"],"products":quotes,"labor":labor,"taxes":taxes.view(db,"?"),"competitors":production.competitors(db,"?"),"retail":retail.snapshot(db,"?",clk,quotes,labor.get("scale",1))}
        db.commit()
    return 200,result

NPC_CONNECT,NPC_PH=connect,"?"

def npc_tick():
    """Let NPC competitors act for completed months (cheap no-op when nothing is pending)."""
    try:
        acted = npc.tick(NPC_CONNECT,NPC_PH,clock_state,lambda:market_state()[1],lambda owner:wallet(owner)[1],build,lambda:city_state()[1])
    except Exception as exc:   # NPC trouble must never break player requests
        print("npc tick failed:",repr(exc))
        acted = 0
    _social_tick()
    return acted


def _social_tick():
    """Distribute alliance dividends after the monthly step. Failures stay off the player path."""
    try:
        ph = NPC_PH
        if ph == "%s":
            with NPC_CONNECT() as db:
                db.execute("SELECT pg_advisory_xact_lock(20261114)")
                now = int(time.time())
                clk = clock.state(db, ph, now)
                production.advance(db, ph, clk, now)
                social.distribute_pending(db, ph, clk, now)
            return
        with LOCK, NPC_CONNECT() as db:
            db.execute("BEGIN IMMEDIATE")
            now = int(time.time())
            clk = clock.state(db, ph, now)
            production.advance(db, ph, clk, now)
            social.distribute_pending(db, ph, clk, now)
            db.commit()
    except Exception as exc:
        print("social tick failed:", repr(exc))

def wallet(owner):
    with LOCK, connect() as db:
        db.execute("BEGIN IMMEDIATE")
        now=int(time.time())
        result=production.wallet(db,"?",owner,clock.state(db,"?",now),now)
        db.commit()
    return 200,result

def _contract_command(owner, payload, fn):
    request_id=payload.get("request_id")
    try:uuid.UUID(request_id)
    except (ValueError,TypeError,AttributeError):return 400,{"error":"invalid_request_id"}
    with LOCK, connect() as db:
        db.execute("BEGIN IMMEDIATE")
        prev=db.execute("SELECT response FROM commands WHERE owner=? AND request_id=?",(owner,request_id)).fetchone()
        if prev:return 200,json.loads(prev[0])
        now=int(time.time())
        clk=clock.state(db,"?",now)
        production.advance(db,"?",clk,now)
        status,result=fn(db,"?",owner,payload,clk["month_index"],now)
        if status==201:
            db.execute("INSERT INTO commands VALUES(?,?,?)",(owner,request_id,json.dumps(result)))
        db.commit()
        return status,result

def contracts_state(owner):
    with LOCK, connect() as db:
        db.execute("BEGIN IMMEDIATE")
        now=int(time.time())
        clk=clock.state(db,"?",now)
        production.advance(db,"?",clk,now)
        result=contracts.view(db,"?",owner,clk["month_index"])
        db.commit()
    return 200,result

def contracts_offer(owner,payload):
    return _contract_command(owner,payload,contracts.offer)

def contracts_accept(owner,payload):
    return _contract_command(owner,payload,contracts.accept)

def contracts_cancel(owner,payload):
    return _contract_command(owner,payload,contracts.cancel)

def events(after):
    if type(after) is not int or after<0:return 400,{"error":"invalid_cursor"}
    with connect() as db:
        rows=db.execute("SELECT seq,cx,cy,version,kind,payload FROM events WHERE seq>? ORDER BY seq LIMIT 100",(after,)).fetchall()
        latest=db.execute("SELECT COALESCE(MAX(seq),0) FROM events").fetchone()[0]
    items=[road_rules.event_item(s,cx,cy,v,kind,payload) for s,cx,cy,v,kind,payload in rows]
    return 200,{"events":items,"cursor":items[-1]["seq"] if items else after,"latest":latest,"has_more":bool(items and items[-1]["seq"]<latest)}

def chunk(cx,cy):
    if type(cx) is not int or type(cy) is not int or abs(cx)>1000 or abs(cy)>1000:
        return 400,{"error":"invalid_chunk"}
    with connect() as db:
        row=db.execute("SELECT version FROM chunks WHERE cx=? AND cy=?",(cx,cy)).fetchone()
        cells=db.execute("""SELECT c.x,c.y,b.kind,b.id,b.owner FROM cells c JOIN buildings b ON c.object_id=b.id
            WHERE c.x>=? AND c.x<? AND c.y>=? AND c.y<? ORDER BY c.x,c.y""",(cx*CHUNK,(cx+1)*CHUNK,cy*CHUNK,(cy+1)*CHUNK)).fetchall()
        rds=db.execute("SELECT x,y,owner FROM roads WHERE x>=? AND x<? AND y>=? AND y<? ORDER BY x,y",(cx*CHUNK,(cx+1)*CHUNK,cy*CHUNK,(cy+1)*CHUNK)).fetchall()
    items=[{"x":x,"y":y,"kind":"building_created","building_kind":kind,"object_id":oid,"owner":owner} for x,y,kind,oid,owner in cells]
    items+=[{"x":x,"y":y,"kind":"road_changed","object_id":"","owner":owner} for x,y,owner in rds]
    return 200,{"cx":cx,"cy":cy,"version":row[0] if row else 0,"cells":items}

def health_details():
    """Additive diagnostics. Preserve legacy /health keys and status code."""
    details = {"ok": True, "service": "lunexeconom-game", "version": "0.2.0"}
    # The updater records the deployed revision independently of service environment.
    # Never expose the file path or an invalid revision in the public health API.
    sha_file = os.environ.get("LUNEX_DEPLOYED_SHA_FILE", "/var/lib/lunexeconom-server-update/deployed-sha")
    try:
        with open(sha_file, "r", encoding="ascii") as deployed:
            commit = deployed.read(128).strip()
    except (OSError, UnicodeError, ValueError):
        commit = ""
    details["commit"] = commit[:12] if len(commit) == 40 and all(c in "0123456789abcdefABCDEF" for c in commit) else None
    engine = os.environ.get("LUNEX_DB_ENGINE", "sqlite")
    try:
        if engine == "postgres":
            with postgres_db.connect() as db:
                db.execute("SELECT 1").fetchone()
        else:
            with sqlite_util.open_db(DB) as db:
                db.execute("SELECT 1").fetchone()
        details["database"] = {"engine": engine, "status": "ok"}
    except Exception:
        # No connection strings, filesystem paths or credentials in health responses.
        details["database"] = {"engine": engine, "status": "unavailable"}
    return details

def stats_leaderboard(owner, by="networth"):
    # An actual read-only SQLite connection: no wallet initialization or world tick.
    with sqlite_util.open_db(DB) as db:
        db.execute("PRAGMA query_only=ON")
        return stats.leaderboard(db, "?", owner, by)


def stats_feed(owner, after=0):
    with sqlite_util.open_db(DB) as db:
        db.execute("PRAGMA query_only=ON")
        return stats.feed(db, "?", owner, after)


def soc_post(owner, path, payload, client):
    with LOCK, connect() as db:
        db.execute("BEGIN IMMEDIATE")
        now = int(time.time())
        clk = clock.state(db, "?", now)
        production.advance(db, "?", clk, now)
        social.distribute_pending(db, "?", clk, now)
        status, result = social.perform_post(db, "?", owner, path, payload, client, now, clk)
        db.commit()
        return status, result


def soc_get(owner, path, query):
    args = {}
    for key, values in query.items():
        if len(values) != 1:
            return 400, {"error": "invalid_query"}
        args[key] = values[0]
    if path in social.READ_ONLY:
        with LOCK, connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT epoch,month_seconds,base_index FROM world_clock WHERE id=1").fetchone()
            if row is not None:
                args["month"] = str(clock.month_index((int(row[0]), int(row[1]), int(row[2])), int(time.time())))
            status, result = social.perform_get(db, "?", owner, path, args, None)
            db.commit()
            return status, result
    with LOCK, connect() as db:
        db.execute("BEGIN IMMEDIATE")
        now = int(time.time())
        clk = clock.state(db, "?", now)
        production.advance(db, "?", clk, now)
        social.distribute_pending(db, "?", clk, now)
        status, result = social.perform_get(db, "?", owner, path, args, clk)
        db.commit()
        return status, result


ECONOMY_POST={"/sell":"sell","/loan":"loan","/city/taxes":"city_taxes","/city/build":"city_build","/city/candidacy":"city_candidacy","/city/vote":"city_vote","/contracts/offer":"contracts_offer","/contracts/accept":"contracts_accept","/contracts/cancel":"contracts_cancel"}

class Handler(BaseHTTPRequestHandler):
    def _send_geo(self, data):
        # Public immutable reference metadata, safe for clients and CDNs.
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "public, max-age=3600")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send(self,status,data):
        raw=json.dumps(data,ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Content-Length",str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)
    def _identity(self):
        bearer=self.headers.get("Authorization","")
        if not bearer.startswith("Bearer "):return None
        status,profile=auth.profile(bearer[7:])
        return profile["username"] if status==200 and profile["username"].lower() not in economy.RESERVED_OWNERS else None
    def _client(self):
        return self.headers.get("X-Real-IP",self.client_address[0])[:64] if self.client_address[0] in ("127.0.0.1","::1") else self.client_address[0]
    def _economy_post(self):
        """Economy commands (/sell, /loan); returns True when the request was handled."""
        path=urlsplit(self.path).path
        if path not in ECONOMY_POST:return False
        try:
            size=int(self.headers.get("Content-Length","0"))
            payload=json.loads(self.rfile.read(size)) if 2<=size<=4096 else None
        except (ValueError,UnicodeError,json.JSONDecodeError):payload=None
        if not isinstance(payload,dict):
            self._send(400,{"error":"invalid_body"});return True
        owner=self._identity()
        if not owner:
            self._send(401,{"error":"unauthorized"});return True
        npc_tick()
        self._send(*globals()[ECONOMY_POST[path]](owner,payload))
        return True
    def _soc_post(self):
        path = urlsplit(self.path).path
        if path not in social.POST:
            return False
        try:
            size = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(size)) if 2 <= size <= 4096 else None
        except (ValueError, UnicodeError, json.JSONDecodeError):
            payload = None
        if not isinstance(payload, dict):
            self._send(400, {"error": "invalid_body"})
            return True
        owner = self._identity()
        if not owner:
            self._send(401, {"error": "unauthorized"})
            return True
        npc_tick()
        self._send(*soc_post(owner, path, payload, self._client()))
        return True
    def do_GET(self):
        url=urlsplit(self.path)
        if url.path in ("/geo/regions", "/geo/cities", "/geo/routes"):
            import geo
            if url.path == "/geo/regions":
                return self._send_geo({"regions": geo.regions()})
            if url.path == "/geo/cities":
                return self._send_geo({"cities": geo.cities()})
            return self._send_geo({"routes": geo.routes()})
        if url.path in social.GET:
            owner = self._identity()
            if not owner:
                return self._send(401, {"error": "unauthorized"})
            if url.path not in social.READ_ONLY:
                npc_tick()
            return self._send(*soc_get(owner, url.path, parse_qs(url.query, keep_blank_values=True)))
        if url.path in ("/market","/wallet","/world","/city","/contracts"):npc_tick()
        if url.path=="/contracts":
            owner=self._identity()
            if not owner:return self._send(401,{"error":"unauthorized"})
            return self._send(*contracts_state(owner))
        if url.path=="/city":return self._send(*city_state(self._identity()))
        if url.path=="/health":return self._send(200,health_details())
        if url.path in ("/leaderboard", "/feed"):
            owner = self._identity()
            if not owner:return self._send(401, {"error":"unauthorized"})
            query = parse_qs(url.query, keep_blank_values=True)
            if url.path == "/leaderboard":
                modes = query.get("by", ["networth"])
                return self._send(*stats_leaderboard(owner, modes[0] if len(modes) == 1 else "invalid"))
            values = query.get("after", ["0"])
            if len(values) != 1 or not values[0].isascii() or not values[0].isdigit() or len(values[0]) > 10:
                return self._send(400, {"error":"invalid_cursor"})
            return self._send(*stats_feed(owner, int(values[0])))
        if url.path=="/world":
            now_clock=clock_state()
            return self._send(200,{"world_id":"bashkiria-main","month_seconds":now_clock["month_seconds"],"building_types":KINDS,"economy":economy.terms(),"clock":now_clock})
        if url.path=="/auth/me":
            status,data=auth.profile(self.headers.get("Authorization","")[7:] if self.headers.get("Authorization","").startswith("Bearer ") else "")
            return self._send(status,data)
        if url.path=="/market":return self._send(*market_state())
        if url.path=="/wallet":
            owner=self._identity()
            if not owner:return self._send(401,{"error":"unauthorized"})
            return self._send(*wallet(owner))
        if url.path in ("/events","/chunk"):
            if not self._identity():return self._send(401,{"error":"unauthorized"})
            try:
                q=parse_qs(url.query)
                result=events(int(q.get("after",["0"])[0])) if url.path=="/events" else chunk(int(q["cx"][0]),int(q["cy"][0]))
            except (ValueError,KeyError,IndexError):result=(400,{"error":"invalid_query"})
            return self._send(*result)
        return self._send(404,{"error":"not_found"})
    def do_POST(self):
        if self._soc_post():return
        if self._economy_post():return
        path=urlsplit(self.path).path
        if path not in ("/auth/register","/auth/login","/auth/logout","/auth/verify/request","/auth/verify/confirm","/auth/password/request","/auth/password/reset","/auth/rotate","/auth/logout-all","/build"):
            return self._send(404,{"error":"not_found"})
        try:
            size=int(self.headers.get("Content-Length","0"))
            if size<2 or size>4096:return self._send(400,{"error":"invalid_body"})
            payload=json.loads(self.rfile.read(size))
            if not isinstance(payload,dict):return self._send(400,{"error":"invalid_body"})
        except (ValueError,UnicodeError,json.JSONDecodeError):
            return self._send(400,{"error":"invalid_body"})
        if path=="/auth/register":return self._send(*auth.register(payload,self._client()))
        if path=="/auth/login":return self._send(*auth.login(payload,self._client()))
        if path=="/auth/logout":
            bearer=self.headers.get("Authorization","")
            return self._send(*auth.logout(bearer[7:] if bearer.startswith("Bearer ") else ""))
        if path=="/auth/verify/request":return self._send(*auth.request_verification(payload,self._client()))
        if path=="/auth/verify/confirm":return self._send(*auth.confirm_email(payload,self._client()))
        if path=="/auth/password/request":return self._send(*auth.request_password_reset(payload,self._client()))
        if path=="/auth/password/reset":return self._send(*auth.reset_password(payload,self._client()))
        if path in ("/auth/rotate","/auth/logout-all"):
            bearer=self.headers.get("Authorization","")
            token=bearer[7:] if bearer.startswith("Bearer ") else ""
            return self._send(*(auth.rotate_token(token) if path=="/auth/rotate" else auth.logout_all(token)))
        owner=self._identity()
        if not owner:return self._send(401,{"error":"unauthorized"})
        npc_tick()
        return self._send(*build(owner,payload))

if os.environ.get("LUNEX_DB_ENGINE") == "postgres":
    build = postgres_world.build
    events = postgres_world.events
    chunk = postgres_world.chunk
    wallet = postgres_world.wallet
    clock_state = postgres_world.clock_state
    market_state = postgres_world.market_state
    sell = postgres_world.sell
    city_state = postgres_world.city_state
    city_taxes = postgres_world.city_taxes
    city_build = postgres_world.city_build
    city_candidacy = postgres_world.city_candidacy
    city_vote = postgres_world.city_vote
    loan = postgres_world.loan
    contracts_state = postgres_world.contracts_state
    contracts_offer = postgres_world.contracts_offer
    contracts_accept = postgres_world.contracts_accept
    contracts_cancel = postgres_world.contracts_cancel
    NPC_CONNECT,NPC_PH = postgres_db.connect,"%s"
    stats_leaderboard = postgres_world.stats_leaderboard
    stats_feed = postgres_world.stats_feed
    soc_post = postgres_world.soc_post
    soc_get = postgres_world.soc_get

if __name__=="__main__":
    if os.environ.get("LUNEX_DB_ENGINE") == "postgres":
        if os.environ.get("LUNEX_AUTO_MIGRATE") == "1":
            import migrate
            migrate.up()
        postgres_db.init()
    else:
        connect().close()
    ThreadingHTTPServer(("127.0.0.1",int(os.environ.get("LUNEX_PORT","18767"))),Handler).serve_forever()
