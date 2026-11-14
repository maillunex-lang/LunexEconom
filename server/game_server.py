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
import roads as road_rules
import economy
import production
import clock
if os.environ.get('LUNEX_DB_ENGINE') == 'postgres':
    import postgres_world
    import postgres_db

DB = os.environ.get("LUNEX_WORLD_DB", "/home/gamedev/projects/LunexEconom-server/world.sqlite3")
CHUNK = 12
MAX_COORD = 10000
KINDS = {"farm":(2,2), "mine":(2,3), "factory":(3,2), "warehouse":(3,3)}
LOCK = threading.RLock()

def connect():
    db = sqlite3.connect(DB, timeout=10)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=10000")
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("CREATE TABLE IF NOT EXISTS buildings(id TEXT PRIMARY KEY,owner TEXT NOT NULL,kind TEXT NOT NULL,x INTEGER NOT NULL,y INTEGER NOT NULL,created INTEGER NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS cells(x INTEGER NOT NULL,y INTEGER NOT NULL,object_id TEXT NOT NULL REFERENCES buildings(id),PRIMARY KEY(x,y))")
    db.execute("CREATE TABLE IF NOT EXISTS chunks(cx INTEGER NOT NULL,cy INTEGER NOT NULL,version INTEGER NOT NULL,PRIMARY KEY(cx,cy))")
    db.execute("CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,cx INTEGER NOT NULL,cy INTEGER NOT NULL,version INTEGER NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS roads(x INTEGER NOT NULL,y INTEGER NOT NULL,owner TEXT NOT NULL,created INTEGER NOT NULL,PRIMARY KEY(x,y))")
    db.execute("CREATE TABLE IF NOT EXISTS commands(owner TEXT NOT NULL,request_id TEXT NOT NULL,response TEXT NOT NULL,PRIMARY KEY(owner,request_id))")
    for statement in economy.SCHEMA + clock.SCHEMA:
        db.execute(statement)
    db.commit()
    return db

def build(owner, payload):
    kind=payload.get("kind")
    x=payload.get("x")
    y=payload.get("y")
    request_id=payload.get("request_id")
    if kind not in KINDS or type(x) is not int or type(y) is not int or abs(x)>MAX_COORD or abs(y)>MAX_COORD:
        return 400,{"error":"invalid_build"}
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

def market_state():
    with LOCK, connect() as db:
        db.execute("BEGIN IMMEDIATE")
        now=int(time.time())
        clk=clock.state(db,"?",now)
        production.advance(db,"?",clk,now)
        result={"ok":True,"month_index":clk["month_index"],"products":production.quote(db,"?",clk)}
        db.commit()
    return 200,result

def wallet(owner):
    with LOCK, connect() as db:
        db.execute("BEGIN IMMEDIATE")
        now=int(time.time())
        result=production.wallet(db,"?",owner,clock.state(db,"?",now),now)
        db.commit()
    return 200,result

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

class Handler(BaseHTTPRequestHandler):
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
        return profile["username"] if status==200 else None
    def _client(self):
        return self.headers.get("X-Real-IP",self.client_address[0])[:64] if self.client_address[0] in ("127.0.0.1","::1") else self.client_address[0]
    def do_GET(self):
        url=urlsplit(self.path)
        if url.path=="/health":return self._send(200,{"ok":True,"service":"lunexeconom-game","version":"0.2.0"})
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
        path=urlsplit(self.path).path
        if path not in ("/auth/register","/auth/login","/auth/logout","/build"):
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
        owner=self._identity()
        if not owner:return self._send(401,{"error":"unauthorized"})
        return self._send(*build(owner,payload))

if os.environ.get("LUNEX_DB_ENGINE") == "postgres":
    build = postgres_world.build
    events = postgres_world.events
    chunk = postgres_world.chunk
    wallet = postgres_world.wallet
    clock_state = postgres_world.clock_state
    market_state = postgres_world.market_state

if __name__=="__main__":
    if os.environ.get("LUNEX_DB_ENGINE") == "postgres":
        postgres_db.init()
    else:
        connect().close()
    ThreadingHTTPServer(("127.0.0.1",int(os.environ.get("LUNEX_PORT","18767"))),Handler).serve_forever()
