"""A2 city administration with request-id-safe auditing and world event feed."""
import re
from server.platform import admin
from server.platform import admin_server as safe
from server.world import core


def _settings(ctx):
    flags=ctx.get("settings",{})
    return {"threshold_bp":flags.get("world_growth_threshold_bp",6000),
            "min_buildings":flags.get("world_growth_min_buildings",10),
            "population_step":flags.get("world_growth_population_step",10000)}


def cities(body,ctx):
    actor,err=safe.guard(ctx)
    if err:return err
    try:limit=safe.integer(admin._query(ctx,'limit','20'),1,100)
    except ValueError:return 400,{'error':'invalid_pagination'}
    after=admin._query(ctx,'after','')
    if after and after not in core.CITIES:return 400,{'error':'invalid_pagination'}
    states=core.city_states(ctx['conn'])
    names=sorted(core.CITIES)
    page_names=[name for name in names if name>after][:limit]
    items=[]
    for city_id in page_names:
        if city_id not in states:continue
        c=core.CITIES[city_id]
        stats=core.growth_stats(ctx['conn'],city_id,**_settings(ctx))
        items.append({'id':city_id,'name':c['name'],'level':stats['level'],
                      'radius':stats['radius'],'occupancy_percent':stats['occupancy_bp']/100,
                      'population':stats['population'],'buildings':stats['building_count'],
                      'growth_enabled':stats['growth_enabled'],'ready':stats['ready']})
    return 200,{'items':items,'count':len(names),'next_after':items[-1]['id'] if len(items)==limit and items[-1]['id']!=names[-1] else None}


def events(body,ctx):
    actor,err=safe.guard(ctx)
    if err:return err
    try:limit,after=safe.page(ctx)
    except ValueError:return 400,{'error':'invalid_pagination'}
    rows=ctx['conn'].execute('''SELECT version,kind,city_id,cx,cy,created_at
                FROM world_events WHERE version>%s ORDER BY version ASC LIMIT %s''', (after,limit)).fetchall()
    items=[{'id':r[0],'kind':r[1],'city_id':r[2],'cx':r[3], 'cy':r[4],
            'at':r[5].isoformat()} for r in rows]
    return 200,{'items':items,'limit':limit,'next_after':items[-1]['id'] if len(items)==limit else None}


def parcels(body,ctx):
    actor,err=safe.guard(ctx)
    if err:return err
    owner=admin._query(ctx,'owner')
    city=admin._query(ctx,'city')
    if owner is not None and not re.fullmatch(r'[A-Za-z0-9_:.\-]{1,128}',owner):return 400,{'error':'invalid_owner'}
    if city is not None and city not in core.CITIES:return 400,{'error':'invalid_city'}
    try:limit=safe.integer(admin._query(ctx,'limit','50'),1,100)
    except ValueError:return 400,{'error':'invalid_pagination'}
    after=admin._query(ctx,'after','')
    if after:
        match=re.fullmatch(r'(-?[0-9]{1,19}):(-?[0-9]{1,19})',after)
        if not match:return 400,{'error':'invalid_pagination'}
        x,y=map(int,match.groups())
        if not all(-2**63 <= v < 2**63 for v in (x,y)):
            return 400,{'error':'invalid_pagination'}
    else:x,y=None,None
    rows=ctx['conn'].execute('''SELECT px,py,city_id,owner_kind,owner_ref,paid_amount FROM world_parcels
          WHERE (%s::text IS NULL OR owner_ref=%s)
            AND (%s::text IS NULL OR city_id=%s)
            AND (%s::bigint IS NULL OR (px,py)>(%s::bigint,%s::bigint))
          ORDER BY px,py LIMIT %s''',(owner,owner,city,city,x,x,y,limit)).fetchall()
    items=[{'px':r[0],'py':r[1],'city_id':r[2],'owner_kind':r[3],
            'owner_ref':r[4],'paid_amount':int(r[5])} for r in rows]
    return 200,{'items':items,'limit':limit,
                'next_after':f'{items[-1]["px"]}:{items[-1]["py"]}' if len(items)==limit else None}


def growth(body,ctx):
    actor,err=safe.guard(ctx,{'admin','owner'})
    if err:return err
    city_id=ctx.get('path_params',{}).get('id')
    if city_id not in core.CITIES:return 404,{'error':'unknown_city'}
    enabled=body.get('enabled'); reason=body.get('reason'); request_id=body.get('request_id')
    if type(enabled) is not bool or not isinstance(reason,str) or not 1<=len(reason.strip())<=500 or not isinstance(request_id,str) or not re.fullmatch(r'[a-zA-Z0-9_.:\-]{8,128}',request_id):
        return 400,{'error':'invalid_growth_request'}
    conn=ctx['conn']
    with conn.transaction():
        # Only lock the target city, all concurrent switches serialize behind it.
        row=conn.execute('SELECT growth_enabled FROM world_cities WHERE id=%s FOR UPDATE',(city_id,)).fetchone()
        if row is None:return 404,{'error':'unknown_city'}
        old=bool(row[0])
        receipt=conn.execute('SELECT city_id,enabled,reason FROM admin_growth_requests WHERE request_id=%s',(request_id,)).fetchone()
        if receipt:
            if receipt!=(city_id,enabled,reason.strip()):return 409,{'error':'request_id_conflict'}
            return 200,{'ok':True,'city_id':city_id,'enabled':enabled,'replayed':True}
        # This column is exactly the setting consumed by the existing world.grow_month hook.
        conn.execute('UPDATE world_cities SET growth_enabled=%s,updated_at=now() WHERE id=%s',(enabled,city_id))
        conn.execute('INSERT INTO admin_growth_requests(request_id,city_id,enabled,reason) VALUES(%s,%s,%s,%s)',
                     (request_id,city_id,enabled,reason.strip()))
        admin._audit(ctx,actor,'world.growth_enabled',{'city_id':city_id,'reason':reason.strip(),'request_id':request_id},
                     old={'growth_enabled':old},new={'growth_enabled':enabled})
    return 200,{'ok':True,'city_id':city_id,'enabled':enabled,'replayed':False}
