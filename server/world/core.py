"""Transactional, sparse and authoritative world data and city growth."""
from __future__ import annotations

import hashlib
import heapq
import json
import re
from collections import deque
from pathlib import Path

from psycopg.types.json import Jsonb
from server.ledger.api import account
from .cities import load_cities
from .generator import (
    CHUNK_CELLS, CELL_METERS, chunk as generate_chunk, terrain,
    radius_at_level, zone, build_allowed, travel_game_hours, connected,
)

CITY_DATA = load_cities()
SEED = CITY_DATA['seed']
CITIES = {city['id']: city for city in CITY_DATA['cities']}
LAND_ZONE_BP = {'center':16000, 'residential':10000, 'industrial':11500, 'free':6000}
BASE_LAND_PRICE = 15000  # draft game RUB per 6x6 parcel
PARCEL_CELLS = 6
MAX_REQUEST_COORD = 2**54  # safe for client JSON numbers
GROWTH_DEFAULTS = dict(threshold_bp=6000, min_buildings=10, population_step=10000)


def migrations():
    return [Path(__file__).resolve().parents[1] / 'migrations' / name for name in ('202611151700_world_core.sql', '202611161730_world_event_chunks.sql')]


def bootstrap(conn):
    """Idempotently introduce new cities and zero-balance city ledger accounts."""
    # Already validated on module import, and again here on app startup.
    load_cities()
    for c in CITY_DATA['cities']:
        conn.execute(
            '''INSERT INTO world_cities (id,population,base_population)
               VALUES (%s,%s,%s) ON CONFLICT(id) DO NOTHING''',
            (c['id'], c['population_estimate'], c['population_estimate'])
        )
        account(conn, 'city:' + c['id'], 'city')


def city_states(conn):
    rows = conn.execute(
        '''SELECT id,level,population,base_population,last_growth_month,growth_enabled
           FROM world_cities ORDER BY id'''
    ).fetchall()
    return {r[0]: dict(level=r[1], population=r[2], base_population=r[3],
                       last_growth_month=r[4], growth_enabled=r[5]) for r in rows}


def city_at(x, y, states):
    """Single authoritative owner for each occupied city cell; no floating point."""
    options = []
    for key, state in states.items():
        c = CITIES[key]
        radius = radius_at_level(c['base_radius'], state['level'])
        distance = max(abs(x-c['x']),abs(y-c['y']))
        if distance <= radius:
            options.append((distance, key))
    return CITIES[min(options)[1]] if options else None


def cell_zone(x,y,states):
    city = city_at(x,y,states)
    if city is None:
        return 'free', None
    return zone(x,y,city['x'],city['y'],city['base_radius'],states[city['id']]['level']),city['id']


def _path_contains(ax,ay,bx,by,x,y):
    """X-first Manhattan L-shaped segment from A to B, includes endpoints."""
    return (y==ay and min(ax,bx)<=x<=max(ax,bx) or
            x==bx and min(ay,by)<=y<=max(ay,by))


def trunk_edges():
    """Deterministic 20-city minimum spanning network; edges are physical grid paths."""
    remaining=set(CITIES) - {'ufa'}
    selected={'ufa'}
    edges=[]
    while remaining:
        candidates=[]
        for a in selected:
            for b in remaining:
                aa,bb=CITIES[a],CITIES[b]
                length=abs(aa['x']-bb['x'])+abs(aa['y']-bb['y'])
                candidates.append((length,a,b))
        distance,a,b=min(candidates)
        edges.append((a,b,distance))
        selected.add(b)
        remaining.remove(b)
    return edges


TRUNK=trunk_edges()


def virtual_road(x,y,states):
    """Crossroads and retained ring road skeleton, plus intercity trunk paths."""
    for a,b,_ in TRUNK:
        ca,cb=CITIES[a],CITIES[b]
        if _path_contains(ca['x'],ca['y'],cb['x'],cb['y'],x,y):
            return True
    for key,s in states.items():
        c=CITIES[key]
        dx,dy=x-c['x'],y-c['y']
        distance=max(abs(dx),abs(dy))
        if distance>radius_at_level(c['base_radius'],s['level']):
            continue
        # Cardinal spokes and concentric square perimeter roads, preserved after expansion.
        if dx==0 or dy==0:
            return True
        if any(distance==radius_at_level(c['base_radius'],n) for n in range(1,s['level']+1)):
            return True
    return False


def routes(start,end):
    if start not in CITIES or end not in CITIES:
        raise ValueError('unknown_city')
    if start==end:
        return {'from':start,'to':end,'cities':[start],'distance_meters':0,
                'game_minutes':0,'speed_kmh':85}
    adjacency={c:[] for c in CITIES}
    for a,b,d in TRUNK:
        adjacency[a].append((b,d));adjacency[b].append((a,d))
    queue=[(0,(start,),start)]
    best={}
    while queue:
        distance,path,node=heapq.heappop(queue)
        if node in best: continue
        best[node]=distance
        if node==end:
            meters=distance*CELL_METERS
            return {'from':start,'to':end,'cities':list(path),
                    'distance_meters':meters,'game_minutes':travel_game_hours(meters),
                    'speed_kmh':85}
        for adjacent,segment in adjacency[node]:
            if adjacent not in best:
                heapq.heappush(queue,(distance+segment,path+(adjacent,),adjacent))
    raise ValueError('disconnected_city_road')


def _chunks_for_cells(cells):
    return {(x//CHUNK_CELLS,y//CHUNK_CELLS) for x,y in cells}


# balance: draft. Public event objects carry no private account attributes.
EVENT_TYPES = {'occupation':'building_added', 'enterprise_construction':'building_added',
               'enterprise_stage':'building_stage_changed', 'demolition':'building_removed',
               'road_build':'road_added', 'land_buy':'parcel_owner_changed',
               'city_growth':'city_growth'}
MAX_EVENT_BYTES = 2048


def _object_for_event(conn, kind, payload):
    """Build the public render object from the enterprise row when it exists."""
    ref = payload.get('building_ref')
    eid = payload.get('enterprise_id')
    if ref is None and isinstance(eid, int):
        ref = 'enterprise:' + str(eid)
    if not isinstance(ref, str) or not re.fullmatch(r'enterprise:[1-9][0-9]{0,17}', ref):
        return None
    number = int(ref.split(':', 1)[1])
    row = conn.execute(
        'SELECT building_id,owner_id,stage,x,y,width,height FROM enterprises WHERE id=%s',
        (number,)).fetchone()
    if not row:
        return None
    catalog, owner, stage, x, y, width, height = row
    if kind in ('occupation','enterprise_construction'):
        stage = 0
    elif kind == 'enterprise_stage':
        stage = payload.get('stage_index', stage)
    return dict(object_id=ref[:64], catalog_id=catalog, owner_ref=str(owner),
                stage_index=int(stage), x=x, y=y, w=width, h=height,
                color_rgb=14658145 if stage == 4 else 10855585)


def _touch(conn, chunks, kind, city_id, payload):
    """Atomically version chunks, insert one event and index all its chunks."""
    chunks = sorted(set(chunks))
    payload = dict(payload)
    # The legacy column names and event kinds are kept unchanged.
    if kind in ('occupation', 'enterprise_construction', 'enterprise_stage', 'demolition'):
        obj = _object_for_event(conn,kind,payload)
        if obj:
            payload['object'] = obj
            payload['cells'] = [[x,y] for y in range(obj['y'],obj['y']+obj['h'])
                                      for x in range(obj['x'],obj['x']+obj['w'])]
        elif kind in ('occupation','demolition') and 'building_ref' in payload:
            # Preserve exact affected cells even for non-enterprise occupancy.
            ref = payload['building_ref']
            if kind == 'occupation':
                rows = conn.execute('SELECT x,y FROM world_occupied_cells WHERE building_ref=%s', (ref,)).fetchall()
                payload['cells'] = [list(cell) for cell in rows]
    if kind == 'road_build':
        payload['cells'] = [list(cell) for cell in payload.get('cells', [])]
    if kind == 'land_buy':
        payload.setdefault('owner_kind','player')
        payload.setdefault('owner_ref',str(payload.get('buyer_id','')))
    # Keep legacy source payload intact; only additive public render fields.
    if kind == 'demolition' and 'cells' not in payload:
        payload['cells'] = []
    # Event size includes the HTTP envelope, not just stored JSONB.
    envelope = dict(event_id=2**63-1,version=2**63-1,
                    type=EVENT_TYPES.get(kind,'unknown'),kind=kind,city_id=city_id,
                    cx=chunks[0][0] if len(chunks)==1 else None,
                    cy=chunks[0][1] if len(chunks)==1 else None,
                    chunks=[{'cx':x,'cy':y} for x,y in chunks[:16]],
                    object=payload.get('object'),payload=payload)
    if len(chunks)>16:
        envelope['chunks_truncated'] = True
    if len(json.dumps(envelope,ensure_ascii=False,separators=(',',':')).encode())>MAX_EVENT_BYTES:
        raise ValueError('world_event_too_large')
    for cx,cy in chunks:
        conn.execute("""INSERT INTO world_chunk_versions(cx,cy,version) VALUES(%s,%s,1)
                        ON CONFLICT(cx,cy) DO UPDATE
                        SET version=world_chunk_versions.version+1""",(cx,cy))
    version=conn.execute(
        """INSERT INTO world_events(kind,city_id,cx,cy,payload)
           VALUES(%s,%s,%s,%s,%s) RETURNING version""",
        (kind,city_id,chunks[0][0] if len(chunks)==1 else None,
         chunks[0][1] if len(chunks)==1 else None,Jsonb(payload))
    ).fetchone()[0]
    if chunks:
        with conn.cursor() as cursor:
            cursor.executemany('INSERT INTO world_event_chunks(event_id,cx,cy) VALUES(%s,%s,%s)',
                               [(version,cx,cy) for cx,cy in chunks])
    return version


def ring_cells(c,old_radius,new_radius):
    x,y=c['x'],c['y']
    for row in range(-new_radius,new_radius+1):
        for col in range(-new_radius,new_radius+1):
            if old_radius < max(abs(col),abs(row)) <= new_radius:
                yield x+col,y+row


def growth_stats(conn,city_id,threshold_bp=6000,min_buildings=10,population_step=10000,
                 *,locked_state=None):
    if city_id not in CITIES:
        raise ValueError('unknown_city')
    if not 1<=threshold_bp<=10000 or min_buildings<1 or population_step<0:
        raise ValueError('invalid_growth_threshold')
    if locked_state is None:
        row=conn.execute(
            '''SELECT level,population,base_population,last_growth_month,growth_enabled
               FROM world_cities WHERE id=%s''',(city_id,)
        ).fetchone()
    else:
        row=locked_state
    if row is None: raise ValueError('city_not_initialized')
    level,population,base_population,last_month,enabled=row
    c=CITIES[city_id]
    radius=radius_at_level(c['base_radius'],level)
    minx,maxx=c['x']-radius,c['x']+radius
    miny,maxy=c['y']-radius,c['y']+radius
    row2=conn.execute(
        '''SELECT count(*),count(DISTINCT building_ref) FROM world_occupied_cells
           WHERE city_id=%s AND x BETWEEN %s AND %s AND y BETWEEN %s AND %s''',
        (city_id,minx,maxx,miny,maxy)
    ).fetchone()
    occupied,buildings=row2
    total=(radius*2+1)**2
    occupancy_bp=occupied*10000//total
    need_people=base_population+population_step*level
    need_buildings=min_buildings*level
    population_ready=population>=need_people
    buildings_ready=buildings>=need_buildings
    ready=(enabled and level<6 and occupied*10000>total*threshold_bp
           and (population_ready or buildings_ready))
    return {
        'city_id':city_id,'level':level,'radius':radius,
        'population':population,'occupied_cells':occupied,'total_cells':total,
        'occupancy_bp':occupancy_bp,'threshold_bp':threshold_bp,
        'required_occupied_cells':(total*threshold_bp)//10000+1,
        'building_count':buildings,'required_building_count':need_buildings,
        'required_population':need_people,'growth_enabled':enabled,
        'ready':ready,'last_growth_month':last_month,
        'next_radius':radius_at_level(c['base_radius'],level+1) if level<6 else radius,
        'balance':'draft',
    }


def grow_month(conn,month_index,threshold_bp=6000,min_buildings=10,population_step=10000):
    if type(month_index) is not int or month_index<0:
        raise ValueError('invalid_month_index')
    grown=[]
    for city_id in sorted(CITIES):
        row=conn.execute(
            '''SELECT level,population,base_population,last_growth_month,growth_enabled
               FROM world_cities WHERE id=%s FOR UPDATE''',
            (city_id,)
        ).fetchone()
        stats=growth_stats(conn,city_id,threshold_bp,min_buildings,population_step,
                           locked_state=row)
        if not stats['ready'] or row[3]>=month_index:
            continue
        old,new=row[0],row[0]+1
        # A city may never grow more than one level in any month. Locked row
        # and unique growth receipt provide defense even outside clock worker.
        receipt=conn.execute(
            '''INSERT INTO world_growth_receipts(city_id,month_index,old_level,new_level)
               VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING city_id''',
            (city_id,month_index,old,new)
        ).fetchone()
        if not receipt:
            continue
        conn.execute(
            '''UPDATE world_cities SET level=%s,last_growth_month=%s,updated_at=now()
               WHERE id=%s''',(new,month_index,city_id)
        )
        c=CITIES[city_id]
        chunks=_chunks_for_cells(ring_cells(c,stats['radius'],stats['next_radius']))
        event=_touch(conn,chunks,'city_growth',city_id,{
            'city':city_id,'month_index':month_index,
            'old_level':old,'new_level':new,'old_radius':stats['radius'],
            'new_radius':stats['next_radius'],'reason':{
                'occupancy_bp':stats['occupancy_bp'],'threshold_bp':threshold_bp,
                'population':stats['population'],'building_count':stats['building_count']
            }
        })
        grown.append({'city':city_id,'level':new,'event_version':event})
    return grown


def nearest_city(x,y):
    return min(CITIES.values(),
               key=lambda c: (abs(x-c['x'])+abs(y-c['y']),c['id']))


def land_context(x,y,states):
    city=city_at(x,y,states)
    return city or nearest_city(x,y), 'city' if city else 'state'


def mark_occupied(conn,city_id,building_ref,cells):
    """Integration hook: occupancy only; enterprises module owns building records."""
    if city_id not in CITIES or not isinstance(building_ref,str) or not building_ref:
        raise ValueError('invalid occupation')
    cells=list(cells)
    if not cells or len(set(cells))!=len(cells):
        raise ValueError('invalid occupation cells')
    states=city_states(conn)
    for x,y in cells:
        selected=city_at(x,y,states)
        if selected is None or selected['id']!=city_id:
            raise ValueError('occupied cell outside city')
        if virtual_road(x,y,states):
            raise ValueError('building overlaps road')
    for x,y in cells:
        conn.execute('INSERT INTO world_occupied_cells(x,y,city_id,building_ref) VALUES(%s,%s,%s,%s)',
                     (x,y,city_id,building_ref))
    return _touch(conn,_chunks_for_cells(cells),'occupation',city_id,
                  {'building_ref':building_ref,'cell_count':len(cells)})


def clear_occupied(conn,building_ref):
    """Synchronous demolition hook: old parcels and zones remain unchanged."""
    rows=conn.execute('DELETE FROM world_occupied_cells WHERE building_ref=%s RETURNING x,y,city_id',
                      (building_ref,)).fetchall()
    if not rows:return None
    return _touch(conn,_chunks_for_cells((x,y) for x,y,_ in rows),'demolition',rows[0][2],
                  {'building_ref':building_ref,'cell_count':len(rows),
                   'cells':[[x,y] for x,y,_ in rows]})


def parcel_origin(px,py):
    return px*PARCEL_CELLS,py*PARCEL_CELLS


def parcel_at(px,py,states,overrides=None):
    x,y=parcel_origin(px,py)
    c=city_at(x+PARCEL_CELLS//2,y+PARCEL_CELLS//2,states)
    kind='city' if c else 'state'
    owner_ref=c['id'] if c else 'state'
    result={'px':px,'py':py,'x':x,'y':y,'width':6,'height':6,
            'city_id':c['id'] if c else None,'owner_kind':kind,
            'owner_ref':owner_ref,'balance':'draft'}
    if overrides:
        result.update(overrides)
    return result


def parcel_price(city_id,zone_name):
    if city_id not in CITIES or zone_name not in LAND_ZONE_BP:
        raise ValueError('invalid_parcel_price')
    return max(1,(BASE_LAND_PRICE*CITIES[city_id]['indices_bp']['land']
                   *LAND_ZONE_BP[zone_name]+100000000-1)//100000000)


def chunk_etag(conn,cx,cy):
    row=conn.execute('SELECT version FROM world_chunk_versions WHERE cx=%s AND cy=%s',
                     (cx,cy)).fetchone()
    version=row[0] if row else 0
    return f'"world-v1-{cx}-{cy}-{version}"'


def snapshot(conn,cx,cy):
    if type(cx) is not int or type(cy) is not int or abs(cx)>MAX_REQUEST_COORD or abs(cy)>MAX_REQUEST_COORD:
        raise ValueError('invalid_chunk_coordinates')
    states=city_states(conn)
    data=generate_chunk(SEED,cx,cy)
    x0,y0=cx*CHUNK_CELLS,cy*CHUNK_CELLS
    edits=conn.execute('''SELECT x,y,terrain FROM world_terrain_edits
                          WHERE x BETWEEN %s AND %s AND y BETWEEN %s AND %s''',
                       (x0,x0+11,y0,y0+11)).fetchall()
    for x,y,value in edits:
        data['terrain'][y-y0][x-x0]=value
    roads={(x,y) for x,y in conn.execute('''SELECT x,y FROM world_roads
                            WHERE x BETWEEN %s AND %s AND y BETWEEN %s AND %s''',
                            (x0,x0+11,y0,y0+11)).fetchall()}
    occupied={(x,y):ref for x,y,ref in conn.execute('''SELECT x,y,building_ref FROM world_occupied_cells
                            WHERE x BETWEEN %s AND %s AND y BETWEEN %s AND %s''',
                            (x0,x0+11,y0,y0+11)).fetchall()}
    zones=[]
    road_grid=[]
    building_grid=[]
    for dy in range(CHUNK_CELLS):
        zone_row,road_row,built_row=[],[],[]
        for dx in range(CHUNK_CELLS):
            x,y=x0+dx,y0+dy
            zone_row.append(cell_zone(x,y,states)[0])
            road_row.append((x,y) in roads or virtual_road(x,y,states))
            built_row.append(occupied.get((x,y)))
        zones.append(zone_row);road_grid.append(road_row);building_grid.append(built_row)
    version_row=conn.execute('''SELECT version FROM world_chunk_versions WHERE cx=%s AND cy=%s''',
                              (cx,cy)).fetchone()
    data.update({'cell_meters':CELL_METERS,'zones':zones,'roads':road_grid,
                 'buildings':building_grid,'version':version_row[0] if version_row else 0,
                 'generator_version':1})
    data['etag']=f'"world-v1-{cx}-{cy}-{data["version"]}"'
    return data


def placement_valid(conn,building_id,x,y):
    """Validation hook for the upcoming enterprises module. No building created."""
    from server.catalog import Catalog
    catalog=Catalog()
    building=catalog.index['buildings'].get(building_id)
    if building is None: raise ValueError('unknown_building')
    states=city_states(conn)
    xs=range(x,x+building['size']['width'])
    ys=range(y,y+building['size']['height'])
    footprint={(a,b) for a in xs for b in ys}
    for a,b in footprint:
        chosen,_=cell_zone(a,b,states)
        if not build_allowed(building,chosen):
            return False,'invalid_zone'
        if terrain(SEED,a,b)=='water':
            return False,'water'
        if virtual_road(a,b,states) or conn.execute(
            'SELECT 1 FROM world_roads WHERE x=%s AND y=%s',(a,b)
        ).fetchone():
            return False,'road_overlap'
        if conn.execute('SELECT 1 FROM world_occupied_cells WHERE x=%s AND y=%s',(a,b)).fetchone():
            return False,'occupied'
    for a,b in footprint:
        for n in ((a-1,b),(a+1,b),(a,b-1),(a,b+1)):
            if n in footprint: continue
            if virtual_road(*n,states) or conn.execute(
                'SELECT 1 FROM world_roads WHERE x=%s AND y=%s',n
            ).fetchone():
                return True,'ok'
    return False,'no_road_access'


# balance: draft. Automatic access road for a building that has no road contact.
AUTO_ROAD_MAX_CELLS = 12
AUTO_ROAD_CELL_COST = 1000


def plan_access_road(conn, actor_id, footprint):
    """Shortest free path from the building to the nearest existing road.

    Returns (cells, None) with new road cells ordered from the building to the road,
    or (None, reason). Deterministic: BFS, 4 directions, start cells sorted by (y, x).
    Passable: dry, unoccupied, not already road, inside no one else's parcel.
    No database writes.
    """
    states = city_states(conn)
    footprint = set(footprint)
    parcel_cache = {}

    def parcel_ok(x, y):
        key = (x // 6, y // 6)
        if key not in parcel_cache:
            row = conn.execute('SELECT owner_kind,owner_ref FROM world_parcels WHERE px=%s AND py=%s',
                               key).fetchone()
            parcel_cache[key] = (row is None or row[0] in ('city', 'state')
                                 or row == ('player', str(actor_id)))
        return parcel_cache[key]

    def is_road(x, y):
        return virtual_road(x, y, states) or conn.execute(
            'SELECT 1 FROM world_roads WHERE x=%s AND y=%s', (x, y)).fetchone() is not None

    def passable(x, y):
        if (x, y) in footprint or not parcel_ok(x, y) or terrain(SEED, x, y) == 'water':
            return False
        if is_road(x, y):
            return False
        return conn.execute('SELECT 1 FROM world_occupied_cells WHERE x=%s AND y=%s',
                            (x, y)).fetchone() is None

    def neighbours(x, y):
        return ((x, y - 1), (x - 1, y), (x + 1, y), (x, y + 1))

    starts = sorted({n for a, b in footprint for n in neighbours(a, b)
                     if n not in footprint and passable(*n)}, key=lambda c: (c[1], c[0]))
    previous = {}
    queue = []
    for c in starts:
        previous[c] = None
        queue.append((c, 1))
    head = 0
    while head < len(queue):
        cell, length = queue[head]
        head += 1
        if any(is_road(*n) for n in neighbours(*cell)):
            path = []
            node = cell
            while node is not None:
                path.append(node)
                node = previous[node]
            path.reverse()
            return path, None
        if length >= AUTO_ROAD_MAX_CELLS:
            continue
        for n in neighbours(*cell):
            if n not in previous and passable(*n):
                previous[n] = cell
                queue.append((n, length + 1))
    return None, 'road_unreachable'
