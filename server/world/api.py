"""Read-only world queries and authenticated, transactional land/road mutations."""
from __future__ import annotations

import re
import json
import threading
import time
from collections import deque

from server.platform.api import authenticate
from server.ledger.api import account, transfer
from . import core
from .generator import connected, terrain

IDENT=re.compile(r'^[a-zA-Z0-9_.:-]{1,128}$')


def _arg(ctx,key,default=None):
    values=ctx.get('query',{}).get(key)
    return values[0] if isinstance(values,list) and len(values)==1 else default


def _integer(value,low=None,high=None):
    if type(value) is int:
        number=value
    elif isinstance(value,str) and len(value)<=20 and re.fullmatch(r'-?(?:0|[1-9][0-9]*)',value):
        number=int(value)
    else:
        raise ValueError('invalid integer')
    if (low is not None and number<low) or (high is not None and number>high):
        raise ValueError('out of range')
    return number


def _settings(ctx):
    settings=ctx.get('settings',{})
    return dict(threshold_bp=settings.get('world_growth_threshold_bp',6000),
                min_buildings=settings.get('world_growth_min_buildings',10),
                population_step=settings.get('world_growth_population_step',10000))


def list_cities(body,ctx):
    conn=ctx['conn']
    states=core.city_states(conn)
    return 200,{'cities':[{
        **core.CITIES[cid],
        **core.growth_stats(conn,cid,**_settings(ctx)),
        'center':{'x':core.CITIES[cid]['x'],'y':core.CITIES[cid]['y']},
    } for cid in core.CITIES if cid in states],'seed':core.SEED,'cell_meters':20,'balance':'draft'}


def city_one(city_id):
    def handler(body,ctx):
        if city_id not in core.city_states(ctx['conn']):
            return 404,{'error':'not_found'}
        c=core.CITIES[city_id]
        return 200,{**c,**core.growth_stats(ctx['conn'],city_id,**_settings(ctx))}
    return handler


def get_chunk(body,ctx):
    cx=_integer(_arg(ctx,'cx'),-core.MAX_REQUEST_COORD,core.MAX_REQUEST_COORD)
    cy=_integer(_arg(ctx,'cy'),-core.MAX_REQUEST_COORD,core.MAX_REQUEST_COORD)
    etag=core.chunk_etag(ctx['conn'],cx,cy)
    ctx['world_etag']=etag
    tags={tag.strip() for tag in ctx.get('if_none_match','').split(',')}
    if etag in tags or '*' in tags:
        return 304,{}
    return 200,core.snapshot(ctx['conn'],cx,cy)


# balance: draft. Per-process caps: the global and account limits are deliberately
# independent of the PostgreSQL connection pool and reveal no authentication data.
_LIMIT_LOCK = threading.Lock()
_REQUESTS = {}
_WAITERS = set()


def _subscribe_chunks(ctx):
    values = ctx.get('query', {}).get('chunks')
    if values is None:
        return None
    if not isinstance(values,list) or len(values)!=1 or not values[0]:
        raise ValueError('invalid_chunks')
    entries = values[0].split(';')
    if not 1 <= len(entries) <= 96:
        raise ValueError('invalid_chunks')
    chunks=[]
    for entry in entries:
        parts=entry.split(',')
        if len(parts)!=2:
            raise ValueError('invalid_chunks')
        chunks.append((_integer(parts[0],-core.MAX_REQUEST_COORD,core.MAX_REQUEST_COORD),
                       _integer(parts[1],-core.MAX_REQUEST_COORD,core.MAX_REQUEST_COORD)))
    if len(set(chunks)) != len(chunks):
        raise ValueError('duplicate_chunks')
    return chunks


def _event_data(conn,after,chunks,gap):
    tip=conn.execute('SELECT COALESCE(MAX(version),0) FROM world_events').fetchone()[0]
    earliest=conn.execute('SELECT MIN(version) FROM world_events').fetchone()[0]
    reset=tip-after>gap or (earliest is not None and after>0 and after<earliest-1)
    if reset:
        return {'events':[],'next_after':tip,'tip':tip,'reset':True,'scanned':tip}
    # Page against the ordered global journal, even if an area has no events.
    # The scanned cursor always follows the global page rather than the last match.
    rows=conn.execute("""SELECT version,kind,city_id,cx,cy,payload
        FROM world_events WHERE version>%s ORDER BY version ASC LIMIT 100""",(after,)).fetchall()
    scanned=rows[-1][0] if rows else max(after,tip)
    candidates=[]
    if chunks is not None and rows:
        ids=[r[0] for r in rows]
        # VALUES has bound positions only, no user-provided SQL text.
        coords=','.join(['(%s,%s)']*len(chunks))
        params=[v for pair in chunks for v in pair]+[ids[0],ids[-1]]
        matches=conn.execute("""SELECT DISTINCT w.event_id FROM world_event_chunks w
          JOIN (VALUES """+coords+""") AS wanted(cx,cy)
          ON w.cx=wanted.cx AND w.cy=wanted.cy
          WHERE w.event_id BETWEEN %s AND %s""",params).fetchall()
        candidates={r[0] for r in matches}
        # Growth affects a ring wider than the first 16 listed chunks.
        candidates.update(r[0] for r in rows if r[1]=='city_growth')
    items=[]
    for version,kind,city_id,cx,cy,payload in rows:
        if chunks is not None and version not in candidates:
            continue
        affected=conn.execute('SELECT cx,cy FROM world_event_chunks WHERE event_id=%s ORDER BY cx,cy LIMIT 17',(version,)).fetchall()
        event={'event_id':version,'version':version,'type':core.EVENT_TYPES.get(kind,'unknown'),
               'kind':kind,'city_id':city_id,'cx':cx,'cy':cy,
               'chunks':[{'cx':x,'cy':y} for x,y in affected[:16]],
               'object':payload.get('object'), 'payload':payload}
        if kind=='road_build':
            event['removed']=bool(payload.get('removed',False))
            event['type']='road_removed' if event['removed'] else 'road_added'
        if len(affected)>16:
            event['chunks_truncated']=True
        if len(json.dumps(event,ensure_ascii=False,separators=(',',':')).encode())>2048:
            # Keep old stored data accessible through snapshots instead of exposing
            # an oversized event, and tell the client to reset safely.
            return {'events':[],'next_after':tip,'tip':tip,'reset':True,'scanned':tip}
        trial={'events':items+[event],'next_after':scanned,'tip':tip,'reset':False,'scanned':scanned}
        if len(json.dumps(trial,ensure_ascii=False,separators=(',',':')).encode())>65536:
            # Stop at the preceding event; continue there without gaps.
            scanned=items[-1]['version'] if items else after
            break
        items.append(event)
    return {'events':items,'next_after':scanned,'tip':tip,'reset':False,'scanned':scanned}


def _rate_key(ctx):
    from server.platform.api import _ip
    # An authenticated account only; do not resolve/hash tokens into log messages.
    actor=authenticate(ctx,track=False)
    return str(actor['id']) if actor else None, _ip(ctx)


def _admit(account,ip,waiting=False,cap=12):
    now=time.monotonic()
    with _LIMIT_LOCK:
        for key,limit in (('ip:'+ip,600),('account:'+str(account),90)):
            if key=='account:None':
                continue
            history=_REQUESTS.setdefault(key,deque())
            while history and history[0]<=now-60:
                history.popleft()
            if len(history)>=limit:
                return False,'rate'
        if waiting and (len(_WAITERS)>=cap or (account is not None and account in _WAITERS)):
            return False,'cap'
        for key in ('ip:'+ip,'account:'+str(account)):
            if key!='account:None':
                _REQUESTS[key].append(now)
        if waiting:
            _WAITERS.add(account if account is not None else 'ip:'+ip)
        return True,None


def _release_waiter(account,ip):
    with _LIMIT_LOCK:
        _WAITERS.discard(account if account is not None else 'ip:'+ip)


def events(body,ctx):
    after=_integer(_arg(ctx,'after','0'),0,2**63-1)
    chunks=_subscribe_chunks(ctx)
    wait_ms=_integer(_arg(ctx,'wait_ms','0'),0,25000)
    settings=ctx.get('settings',{})
    enabled=bool(settings.get('world_events_wait_enabled',False))
    # game_server WSGI currently provides a connection held for an entire
    # dispatch. Until a separate pre-dispatch hook exists, NEVER sleep here.
    # This is essential: a 25-second sleep would exhaust the pool of 20.
    account,ip=_rate_key(ctx)
    admitted,reason=_admit(account,ip,False)
    if not admitted:
        return 429,{'error':'rate_limited'}
    response=_event_data(ctx['conn'],after,chunks,int(settings.get('world_events_catchup_max_gap',5000)))
    if enabled and wait_ms and not response['events'] and not response['reset']:
        # Fail fast rather than retaining the WSGI transaction. This branch can
        # switch to a wait after the server's entrypoint has a pool-free hook.
        response['retry_after_ms']=1000
    return 200,response


def get_routes(body,ctx):
    start,end=_arg(ctx,'from'),_arg(ctx,'to')
    if start not in core.CITIES or end not in core.CITIES:
        return 404,{'error':'unknown_city'}
    return 200,core.routes(start,end)


def _requested_chunk(ctx):
    text=_arg(ctx,'chunk')
    if text is not None:
        parts=text.split(',')
        if len(parts)!=2:raise ValueError('invalid chunk')
        return (_integer(parts[0],-core.MAX_REQUEST_COORD,core.MAX_REQUEST_COORD),
                _integer(parts[1],-core.MAX_REQUEST_COORD,core.MAX_REQUEST_COORD))
    return (_integer(_arg(ctx,'cx'),-core.MAX_REQUEST_COORD,core.MAX_REQUEST_COORD),
            _integer(_arg(ctx,'cy'),-core.MAX_REQUEST_COORD,core.MAX_REQUEST_COORD))


def parcels(body,ctx):
    cx,cy=_requested_chunk(ctx)
    states=core.city_states(ctx['conn'])
    px0,py0=cx*2,cy*2
    rows=ctx['conn'].execute(
        '''SELECT px,py,city_id,owner_kind,owner_ref,paid_amount FROM world_parcels
           WHERE px BETWEEN %s AND %s AND py BETWEEN %s AND %s''',
        (px0,px0+1,py0,py0+1)
    ).fetchall()
    overrides={(r[0],r[1]):{'city_id':r[2],'owner_kind':r[3],
                            'owner_ref':r[4],'paid_amount':r[5]} for r in rows}
    result=[]
    for py in range(py0,py0+2):
        for px in range(px0,px0+2):
            entry=core.parcel_at(px,py,states,overrides.get((px,py)))
            if entry['owner_kind'] in ('city','state'):
                zone_name,_=core.cell_zone(px*6+3,py*6+3,states)
                nearest=core.nearest_city(px*6+3,py*6+3)
                entry['price']=core.parcel_price(entry['city_id'] or nearest['id'],zone_name)
                entry['zone']=zone_name
            result.append(entry)
    return 200,{'cx':cx,'cy':cy,'parcels':result}


def buy(body,ctx):
    if not isinstance(body,dict):
        return 400,{'error':'invalid_body'}
    try:
        px=_integer(body.get('px'),-core.MAX_REQUEST_COORD,core.MAX_REQUEST_COORD)
        py=_integer(body.get('py'),-core.MAX_REQUEST_COORD,core.MAX_REQUEST_COORD)
    except ValueError:
        return 400,{'error':'invalid_coordinates'}
    request_id=body.get('request_id')
    if not isinstance(request_id,str) or not IDENT.fullmatch(request_id):
        return 400,{'error':'invalid_request_id'}
    actor=authenticate(ctx)
    if not actor:
        return 401,{'error':'unauthorized'}
    conn=ctx['conn']
    # Lock the request key as well as the city, so duplicate request ids
    # cannot purchase distinct parcels concurrently.
    conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',
                 ('world:buy:'+request_id,))
    previous=conn.execute(
        '''SELECT px,py,buyer_id,amount,transfer_id FROM world_land_requests
           WHERE request_id=%s''',(request_id,)
    ).fetchone()
    if previous:
        if previous[:3]!=(px,py,actor['id']):
            return 409,{'error':'request_id_conflict'}
        return 200,{'px':px,'py':py,'price':previous[3],
                    'transfer_id':previous[4],'idempotent':True}
    states=core.city_states(conn)
    center_x,center_y=px*6+3,py*6+3
    city,kind=core.land_context(center_x,center_y,states)
    city_id=city['id']
    # Same city row first for land buys and monthly expansion.
    conn.execute('SELECT id FROM world_cities WHERE id=%s FOR UPDATE',(city_id,))
    states=core.city_states(conn)
    city_now,kind_now=core.land_context(center_x,center_y,states)
    if city_now['id']!=city_id:
        return 409,{'error':'city_changed'}
    kind=kind_now
    initial_ref=city_id if kind=='city' else 'state'
    stored_city=city_id if kind=='city' else None
    conn.execute(
        '''INSERT INTO world_parcels(px,py,city_id,owner_kind,owner_ref)
           VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
        (px,py,stored_city,kind,initial_ref)
    )
    row=conn.execute('''SELECT owner_kind,owner_ref,city_id FROM world_parcels
                       WHERE px=%s AND py=%s FOR UPDATE''',(px,py)).fetchone()
    if row != (kind,initial_ref,stored_city):
        return 409,{'error':'parcel_unavailable'}
    zone_name,_=core.cell_zone(center_x,center_y,states)
    price=core.parcel_price(city_id,zone_name)
    player_wallet=account(conn,'player:'+actor['username'].lower(),'player',actor['id'])
    seller_wallet=(account(conn,'city:'+city_id,'city') if kind=='city'
                   else account(conn,'system:treasury'))
    try:
        transaction=transfer(conn,'world:land:'+request_id,player_wallet,seller_wallet,price)
    except ValueError as e:
        return 409,{'error':'payment_failed','reason':str(e)}
    conn.execute(
        '''UPDATE world_parcels SET owner_kind='player',owner_ref=%s,paid_amount=%s
           WHERE px=%s AND py=%s''',
        (str(actor['id']),price,px,py)
    )
    conn.execute(
        '''INSERT INTO world_land_requests(request_id,px,py,buyer_id,amount,transfer_id)
           VALUES(%s,%s,%s,%s,%s,%s)''',
        (request_id,px,py,actor['id'],price,transaction)
    )
    version=core._touch(conn,
        core._chunks_for_cells((x,y) for x in range(px*6,px*6+6)
                                         for y in range(py*6,py*6+6)),
        'land_buy',city_id,{'px':px,'py':py,'buyer_id':actor['id'],'price':price,'seller':kind})
    return 201,{'px':px,'py':py,'price':price,'transfer_id':transaction,
                'event_version':version,'idempotent':False,'balance':'draft'}


def build_roads(body,ctx):
    actor=authenticate(ctx)
    if not actor:return 401,{'error':'unauthorized'}
    values=body.get('cells') if isinstance(body,dict) else None
    if not isinstance(values,list) or not 1<=len(values)<=256:
        return 400,{'error':'invalid_road_cells'}
    try:
        cells=[(_integer(v[0],-core.MAX_REQUEST_COORD,core.MAX_REQUEST_COORD),
                _integer(v[1],-core.MAX_REQUEST_COORD,core.MAX_REQUEST_COORD))
               for v in values if isinstance(v,list) and len(v)==2]
    except (TypeError,IndexError,ValueError):
        return 400,{'error':'invalid_road_cells'}
    if len(cells)!=len(values) or len(set(cells))!=len(cells):
        return 400,{'error':'duplicate_road_cells'}
    cellset=set(cells)
    if not connected(cellset,cells[0],cells[-1]) or any(not connected(cellset,cells[0],c) for c in cells):
        return 409,{'error':'roads_must_form_one_connected_path'}
    conn=ctx['conn']
    states=core.city_states(conn)
    ids={core.land_context(x,y,states)[0]['id'] for x,y in cells}
    if len(ids)!=1:
        return 409,{'error':'road_crosses_city_boundary'}
    city_id=ids.pop()
    conn.execute('SELECT id FROM world_cities WHERE id=%s FOR UPDATE',(city_id,))
    for px,py in {(x//6,y//6) for x,y in cells}:
        row=conn.execute('SELECT owner_kind,owner_ref FROM world_parcels WHERE px=%s AND py=%s',
                         (px,py)).fetchone()
        if row!=('player',str(actor['id'])):
            return 403,{'error':'parcel_not_owned'}
    for x,y in cells:
        if terrain(core.SEED,x,y)=='water':
            return 409,{'error':'water_requires_bridge'}
        if conn.execute('SELECT 1 FROM world_occupied_cells WHERE x=%s AND y=%s',(x,y)).fetchone():
            return 409,{'error':'road_overlaps_building'}
    # A newly-built road must attach to the existing authoritative road network.
    touches=False
    for x,y in cells:
        for n in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
            if n not in cellset and (core.virtual_road(*n,states) or
                        conn.execute('SELECT 1 FROM world_roads WHERE x=%s AND y=%s',n).fetchone()):
                touches=True
                break
        if touches:break
    if not touches:return 409,{'error':'no_road_connection'}
    created=[]
    for x,y in sorted(cells):
        result=conn.execute('''INSERT INTO world_roads(x,y,builder_id)
            VALUES(%s,%s,%s) ON CONFLICT DO NOTHING RETURNING x,y''',(x,y,actor['id'])).fetchone()
        if result: created.append(result)
    if created:
        version=None
        for offset in range(0,len(created),48):
            section=created[offset:offset+48]
            version=core._touch(conn,core._chunks_for_cells(section),
                                'road_build',city_id,{'cells':section,'player':actor['id']})
    else: version=None
    return 200,{'created':len(created),'event_version':version,'balance':'draft'}


def admin_growth(body,ctx):
    if not ctx.get('admin_verified'):
        return 403,{'error':'forbidden'}
    cid=(body.get('city') if isinstance(body,dict) else None) or _arg(ctx,'city')
    if cid not in core.CITIES:
        return 404,{'error':'unknown_city'}
    if ctx.get('method')=='POST':
        enabled=body.get('enabled')
        if type(enabled) is not bool:
            return 400,{'error':'invalid_enabled'}
        ctx['conn'].execute('UPDATE world_cities SET growth_enabled=%s WHERE id=%s',(enabled,cid))
        ctx['conn'].execute(
            '''INSERT INTO audit(actor,action,payload) VALUES(%s,%s,%s)''',
            ('admin','world.growth_enabled',f'{{"city":"{cid}","enabled":{str(enabled).lower()}}}')
        )
    stats=core.growth_stats(ctx['conn'],cid,**_settings(ctx))
    stats['global_growth_enabled']=ctx.get('settings',{}).get('world_growth_enabled',True)
    return 200,stats
