"""Persisted server-authoritative visual construction stages; no client-supplied stage."""
import json
import os
import time

# 7 real days = 1 game year, 14 real hours = 1 game month.
# Each visual stage lasts one sixth of a game month by default.
DEFAULT_STEP_SECONDS = 14 * 3600 // 6


def step_seconds():
    raw = os.environ.get('LUNEX_CONSTRUCTION_STEP_SECONDS', str(DEFAULT_STEP_SECONDS))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_STEP_SECONDS
    return value if 1 <= value <= 86400 else DEFAULT_STEP_SECONDS


def ensure(db, marker):
    db.execute('CREATE TABLE IF NOT EXISTS construction_stages (object_id TEXT PRIMARY KEY REFERENCES buildings(id) ON DELETE CASCADE, stage TEXT NOT NULL CHECK(stage IN (\'foundation\',\'frame\',\'complete\')), next_at BIGINT NOT NULL)')
    db.execute("CREATE INDEX IF NOT EXISTS construction_stages_due ON construction_stages(next_at) WHERE stage != 'complete'")


def register(db, marker, object_id, now):
    db.execute(f'INSERT INTO construction_stages(object_id,stage,next_at) VALUES({marker},{marker},{marker})', (object_id, 'foundation', now + step_seconds()))


def advance(db, marker, now, chunk_size=12):
    """Advance due stages atomically; append chunk-versioned events only on change."""
    due = db.execute(f"SELECT object_id,stage,next_at FROM construction_stages WHERE stage!='complete' AND next_at<={marker} ORDER BY object_id", (now,)).fetchall()
    emitted = 0
    for oid, old_stage, next_at in due:
        step = step_seconds()
        new_stage = 'complete' if old_stage == 'frame' and now >= next_at else 'frame'
        new_next = 0 if new_stage == 'complete' else next_at + step
        if old_stage == 'foundation' and now >= next_at + step:
            new_stage, new_next = 'complete', 0
        db.execute(f'UPDATE construction_stages SET stage={marker},next_at={marker} WHERE object_id={marker}', (new_stage, new_next, oid))
        building = db.execute(f'SELECT owner,kind FROM buildings WHERE id={marker}', (oid,)).fetchone()
        if not building:
            continue
        owner, kind = building
        cells = db.execute(f'SELECT x,y FROM cells WHERE object_id={marker} ORDER BY x,y', (oid,)).fetchall()
        grouped = {}
        for x, y in cells:
            grouped.setdefault((x//chunk_size,y//chunk_size),[]).append([x,y])
        for (cx,cy), coords in sorted(grouped.items()):
            db.execute(f'INSERT INTO chunks(cx,cy,version) VALUES({marker},{marker},1) ON CONFLICT(cx,cy) DO UPDATE SET version=chunks.version+1',(cx,cy))
            version = db.execute(f'SELECT version FROM chunks WHERE cx={marker} AND cy={marker}', (cx,cy)).fetchone()[0]
            payload = json.dumps({'object_id':oid,'owner':owner,'building_kind':kind,'construction_stage':new_stage,'cells':coords})
            db.execute(f'INSERT INTO events(cx,cy,version,kind,payload) VALUES({marker},{marker},{marker},{marker},{marker})',(cx,cy,version,'building_created',payload))
            emitted += 1
    return emitted


def stages_for_chunk(db, marker, object_ids):
    if not object_ids:
        return {}
    params=','.join([marker]*len(object_ids))
    return dict(db.execute(f'SELECT object_id,stage FROM construction_stages WHERE object_id IN ({params})', tuple(object_ids)).fetchall())