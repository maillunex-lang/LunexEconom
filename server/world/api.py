"""Read-only world queries and authenticated, transactional land/road mutations."""
from __future__ import annotations

import re

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


def events(body,ctx):
    after=_integer(_arg(ctx,'after','0'),0,2**63-1)
    rows=ctx['conn'].execute(
        '''SELECT version,kind,city_id,cx,cy,payload
           FROM world_events WHERE version>%s ORDER BY version ASC LIMIT 100''',(after,)
    ).fetchall()
    items=[{'version':r[0],'kind':r[1],'city_id':r[2],
            'cx':r[3],'cy':r[4],'payload':r[5]} for r in rows]
    return 200,{'events':items,'next_after':items[-1]['version'] if items else after}


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
        version=core._touch(conn,core._chunks_for_cells(created),
                            'road_build',city_id,{'cells':created,'player':actor['id']})
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
