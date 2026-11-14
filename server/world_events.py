"""Persistent authoritative event log, internal write API only. SQLite test backend."""
import json, sqlite3, threading
from pathlib import Path

DB = Path(__file__).with_name('world_state.sqlite3')
LOCK = threading.RLock()
CHUNK = 12
ALLOWED = {'building_created', 'building_removed', 'road_changed'}

def connect():
    db = sqlite3.connect(DB, timeout=5)
    db.execute('PRAGMA busy_timeout=5000')
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE IF NOT EXISTS chunks (cx INTEGER NOT NULL, cy INTEGER NOT NULL, version INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(cx,cy))')
    db.execute('CREATE TABLE IF NOT EXISTS cells (x INTEGER NOT NULL,y INTEGER NOT NULL,kind TEXT NOT NULL,object_id TEXT NOT NULL, PRIMARY KEY(x,y))')
    db.execute('CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT,cx INTEGER NOT NULL,cy INTEGER NOT NULL,version INTEGER NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL)')
    db.commit()
    return db

def _chunk(x,y): return x//CHUNK,y//CHUNK

def apply(kind, x, y, object_id='demo', footprint=None):
    if kind not in ALLOWED or not isinstance(x,int) or not isinstance(y,int) or abs(x)>100000 or abs(y)>100000: raise ValueError('invalid event')
    footprint = footprint if footprint is not None else [[x,y]]
    if not isinstance(footprint,list) or not 1<=len(footprint)<=144 or any(not isinstance(c,list) or len(c)!=2 or not all(isinstance(v,int) and abs(v)<=100000 for v in c) for c in footprint): raise ValueError('invalid footprint')
    if len({tuple(c) for c in footprint}) != len(footprint): raise ValueError('duplicate cells')
    if not isinstance(object_id,str) or not 1<=len(object_id)<=64: raise ValueError('invalid object id')
    grouped = {}
    for cell in footprint: grouped.setdefault(_chunk(*cell),[]).append(cell)
    out=[]
    with LOCK, connect() as db:
        for cx,cy in sorted(grouped):
            old=db.execute('SELECT version FROM chunks WHERE cx=? AND cy=?',(cx,cy)).fetchone()
            version=(old[0] if old else 0)+1
            db.execute('INSERT INTO chunks(cx,cy,version) VALUES(?,?,?) ON CONFLICT(cx,cy) DO UPDATE SET version=excluded.version',(cx,cy,version))
            for xx,yy in grouped[(cx,cy)]:
                if kind=='building_removed': db.execute('DELETE FROM cells WHERE x=? AND y=?',(xx,yy))
                else: db.execute('INSERT INTO cells(x,y,kind,object_id) VALUES(?,?,?,?) ON CONFLICT(x,y) DO UPDATE SET kind=excluded.kind,object_id=excluded.object_id',(xx,yy,kind,object_id))
            payload={'object_id':object_id,'cells':grouped[(cx,cy)]}
            cur=db.execute('INSERT INTO events(cx,cy,version,kind,payload) VALUES(?,?,?,?,?)',(cx,cy,version,kind,json.dumps(payload)))
            out.append({'seq':cur.lastrowid,'cx':cx,'cy':cy,'version':version,'kind':kind,**payload})
    return out

def changes(after=0,limit=100):
    if not isinstance(after,int) or after<0 or not 1<=limit<=200: raise ValueError('invalid cursor')
    with connect() as db:
        rows=db.execute('SELECT seq,cx,cy,version,kind,payload FROM events WHERE seq>? ORDER BY seq LIMIT ?',(after,limit)).fetchall()
        latest=db.execute('SELECT COALESCE(MAX(seq),0) FROM events').fetchone()[0]
    events=[{'seq':s,'cx':cx,'cy':cy,'version':v,'kind':k,**json.loads(p)} for s,cx,cy,v,k,p in rows]
    return {'events':events,'cursor':events[-1]['seq'] if events else after,'latest':latest,'has_more':bool(events and events[-1]['seq']<latest)}

def snapshot(cx,cy):
    if not all(isinstance(v,int) and abs(v)<=10000 for v in (cx,cy)): raise ValueError('invalid chunk')
    with connect() as db:
        row=db.execute('SELECT version FROM chunks WHERE cx=? AND cy=?',(cx,cy)).fetchone()
        cells=db.execute('SELECT x,y,kind,object_id FROM cells WHERE x>=? AND x<? AND y>=? AND y<? ORDER BY x,y',(cx*CHUNK,(cx+1)*CHUNK,cy*CHUNK,(cy+1)*CHUNK)).fetchall()
    return {'cx':cx,'cy':cy,'version':row[0] if row else 0,'cells':[{'x':x,'y':y,'kind':kind,'object_id':obj} for x,y,kind,obj in cells]}