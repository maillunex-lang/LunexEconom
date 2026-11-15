"""Authenticated supply links, atomic replacement per enterprise."""
from server.platform.api import authenticate
from server.enterprises import core as enterprise
from . import core

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
    return 200,{'enterprise_id':row[0],'inputs':core.read_links(ctx['conn'],row[0]),'balance':'draft'}

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
