"""PostgreSQL-backed world operations. Transactions serialize conflicting footprints."""
import json
import time
import uuid
import psycopg
import postgres_db

CHUNK = 12
MAX_COORD = 10000
KINDS = {"farm":(2,2),"mine":(2,3),"factory":(3,2)}

def build(owner,payload):
    kind=payload.get("kind")
    x=payload.get("x")
    y=payload.get("y")
    request_id=payload.get("request_id")
    if kind not in KINDS or type(x) is not int or type(y) is not int or abs(x)>MAX_COORD or abs(y)>MAX_COORD:
        return 400,{"error":"invalid_build"}
    try:uuid.UUID(request_id)
    except (ValueError,TypeError,AttributeError):return 400,{"error":"invalid_request_id"}
    w,h=KINDS[kind]
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
        oid=uuid.uuid4().hex
        db.execute("INSERT INTO buildings(id,owner,kind,x,y,created) VALUES(%s,%s,%s,%s,%s,%s)",
                   (oid,owner,kind,x,y,int(time.time())))
        with db.cursor() as cursor:
            cursor.executemany("INSERT INTO cells(x,y,object_id) VALUES(%s,%s,%s)",[(xx,yy,oid) for xx,yy in footprint])
        grouped={}
        for xx,yy in footprint:grouped.setdefault((xx//CHUNK,yy//CHUNK),[]).append([xx,yy])
        events=[]
        for (cx,cy),coords in sorted(grouped.items()):
            version=db.execute("""INSERT INTO chunks(cx,cy,version) VALUES(%s,%s,1)
               ON CONFLICT(cx,cy) DO UPDATE SET version=chunks.version+1 RETURNING version""",(cx,cy)).fetchone()[0]
            data={"object_id":oid,"kind":kind,"owner":owner,"cells":coords}
            seq=db.execute("""INSERT INTO events(cx,cy,version,kind,payload)
                VALUES(%s,%s,%s,%s,%s) RETURNING seq""",(cx,cy,version,"building_created",json.dumps(data))).fetchone()[0]
            events.append({"seq":seq,"cx":cx,"cy":cy,"version":version,"kind":"building_created",**data})
        result={"ok":True,"object_id":oid,"events":events}
        db.execute("INSERT INTO commands(owner,request_id,response) VALUES(%s,%s,%s)",(owner,request_id,json.dumps(result)))
        return 201,result

def events(after):
    if type(after) is not int or after<0:return 400,{"error":"invalid_cursor"}
    with postgres_db.connect() as db:
        rows=db.execute("SELECT seq,cx,cy,version,kind,payload FROM events WHERE seq>%s ORDER BY seq LIMIT 100",(after,)).fetchall()
        latest=db.execute("SELECT COALESCE(MAX(seq),0) FROM events").fetchone()[0]
    items=[{"seq":s,"cx":cx,"cy":cy,"version":v,"kind":kind,**json.loads(payload)} for s,cx,cy,v,kind,payload in rows]
    return 200,{"events":items,"cursor":items[-1]["seq"] if items else after,"latest":latest,"has_more":bool(items and items[-1]["seq"]<latest)}

def chunk(cx,cy):
    if type(cx) is not int or type(cy) is not int or abs(cx)>1000 or abs(cy)>1000:
        return 400,{"error":"invalid_chunk"}
    with postgres_db.connect() as db:
        row=db.execute("SELECT version FROM chunks WHERE cx=%s AND cy=%s",(cx,cy)).fetchone()
        cells=db.execute("""SELECT c.x,c.y,b.kind,b.id,b.owner FROM cells c JOIN buildings b ON c.object_id=b.id
          WHERE c.x>=%s AND c.x<%s AND c.y>=%s AND c.y<%s ORDER BY c.x,c.y""",
          (cx*CHUNK,(cx+1)*CHUNK,cy*CHUNK,(cy+1)*CHUNK)).fetchall()
    return 200,{"cx":cx,"cy":cy,"version":row[0] if row else 0,"cells":[{"x":x,"y":y,"kind":kind,"object_id":oid,"owner":owner} for x,y,kind,oid,owner in cells]}
