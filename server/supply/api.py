"""Authenticated supply links, atomic replacement per enterprise."""
from server.platform.api import authenticate
from server.enterprises import core as enterprise
from . import core
from server.platform.settings import read_settings

def _mine(ctx):
    actor=authenticate(ctx)
    if not actor:return None,None,(401,{'error':'unauthorized'})
    try:eid=enterprise.integer(int(ctx['path_params']['id']),1)
    except (ValueError,KeyError,TypeError):return actor,None,(404,{'error':'not_found'})
    row=ctx['conn'].execute('SELECT id,owner_id,recipe_id FROM enterprises WHERE id=%s AND sold_at IS NULL FOR UPDATE',(eid,)).fetchone()
    if not row or row[1]!=actor['id']:
        return actor,None,(404,{'error':'not_found'})
    return actor,row,None

def get(body,ctx):
    _,row,error=_mine(ctx)
    if error:return error
    conn = ctx['conn']
    links = core.read_links(conn, row[0])
    registry = ctx.get('registry')
    flags = ctx.get('settings')
    if flags is None:
        flags = read_settings(conn, registry.flags, registry.flag_constraints) if registry else {}
    origin = conn.execute('SELECT city_id,x,y FROM enterprises WHERE id=%s', (row[0],)).fetchone()
    destination = core._city(*origin)
    enriched = {}
    for product, entries in links.items():
        enriched[product] = []
        for entry in entries:
            result = dict(entry)
            kind = entry['source_type']
            supplier = entry['source_enterprise_id']
            source = None
            if kind == 'enterprise':
                info = conn.execute('SELECT city_id,x,y FROM enterprises WHERE id=%s', (supplier,)).fetchone()
                if info:
                    source = core._city(*info)
            elif kind == 'port':
                source = core._port(flags, destination)
            if source:
                # The actual dispatch quantity is determined at the daily tick.
                # Quote a full recipe target apportioned by the link share.
                recipe = core._recipe(row[2])
                planned = (recipe or {'inputs': {}})['inputs'].get(product, 0)
                quantity = planned * entry['share'] // 1000
                liters, cost = core.fuel_quote(source, destination, quantity, flags)
                result['fuel_liters'] = liters
                if flags.get('logistics_fuel_autobuy', True):
                    result['fuel_cost'] = cost
                if source != destination:
                    result['transport_cost'] = core._travel(
                        source, destination, quantity,
                        flags.get('supply_transport_rub_per_km_unit_draft', 1))[1]
            else:
                result['fuel_liters'] = 0
            enriched[product].append(result)
    failures = conn.execute("""SELECT product_id,reason FROM supply_fuel_failures
        WHERE enterprise_id=%s AND day_index=(SELECT max(day_index)
            FROM supply_fuel_failures WHERE enterprise_id=%s)""",
        (row[0], row[0])).fetchall()
    return 200, {'enterprise_id':row[0], 'inputs':links, 'balance':'draft',
                 'links':[{**item, 'product_id':product}
                          for product, entries in enriched.items() for item in entries],
                 'fuel_failures':[{'product_id':product,'reason':reason}
                                  for product,reason in failures]}


def put(body,ctx):
    _,row,error=_mine(ctx)
    if error:return error
    if not isinstance(body,dict) or set(body)!={'inputs'}:
        return 400,{'error':'invalid_body'}
    try:
        links=core.validate_links(ctx['conn'],row,body['inputs'])
    except (TypeError,ValueError) as exc:
        return 400,{'error':str(exc)}
    ctx['conn'].execute('DELETE FROM supply_links WHERE enterprise_id=%s',(row[0],))
    for product,entry in links:
        ctx['conn'].execute("""INSERT INTO supply_links(enterprise_id,product_id,slot,source_type,source_enterprise_id,share,priority,max_price,min_quality)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (row[0],product,entry['slot'],entry['source_type'],entry['source_enterprise_id'],entry['share'],entry['priority'],entry['max_price'],entry['min_quality']))
    return 200,{'enterprise_id':row[0],'inputs':core.read_links(ctx['conn'],row[0]),'balance':'draft'}

def policy_get(body,ctx):
    """Owner-only seller consent; absent row means no public sales."""
    _,row,error=_mine(ctx)
    if error:return error
    found=ctx['conn'].execute(
        'SELECT allow_direct_sales,allow_city_market FROM supply_seller_policy '
        'WHERE enterprise_id=%s',(row[0],)).fetchone()
    return 200,{'enterprise_id':row[0],
                'allow_direct_sales':found[0] if found else False,
                'allow_city_market':found[1] if found else False}


def policy_put(body,ctx):
    _,row,error=_mine(ctx)
    if error:return error
    if (not isinstance(body,dict)
            or set(body)!={'allow_direct_sales','allow_city_market'}
            or any(type(value) is not bool for value in body.values())):
        return 400,{'error':'invalid_seller_policy'}
    ctx['conn'].execute(
        """INSERT INTO supply_seller_policy(enterprise_id,allow_direct_sales,
           allow_city_market)
           VALUES(%s,%s,%s)
           ON CONFLICT(enterprise_id)
           DO UPDATE SET allow_direct_sales=EXCLUDED.allow_direct_sales,
                         allow_city_market=EXCLUDED.allow_city_market,
                         updated_at=now()""",
        (row[0],body['allow_direct_sales'],body['allow_city_market']))
    return policy_get(body,ctx)
