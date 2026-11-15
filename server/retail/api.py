"""Owner-only store setup and sales, public city competition ratings."""
from server.platform.api import authenticate
from server.enterprises.core import catalog
from server.world.core import CITIES
from . import core


def _mine(ctx):
    actor=authenticate(ctx)
    if not actor:
        return None,(401,{'error':'unauthorized'})
    try:
        eid=int(ctx['path_params']['id'])
        core.integer(eid,1)
    except (KeyError,ValueError,TypeError):
        return None,(404,{'error':'not_found'})
    row=ctx['conn'].execute('SELECT id,owner_id,building_id FROM enterprises WHERE id=%s AND sold_at IS NULL FOR UPDATE',(eid,)).fetchone()
    if not row or row[1]!=actor['id']:
        return None,(404,{'error':'not_found'})
    try:
        core.building_details(row[2])
    except ValueError:
        return None,(409,{'error':'not_retail_store'})
    return row,None


def _read(conn,eid):
    rows=conn.execute('SELECT cell_index,product_id,price,min_stock,supply_link_slot FROM retail_cells WHERE enterprise_id=%s ORDER BY cell_index',(eid,)).fetchall()
    return [dict(cell_index=idx,product_id=good,price=price,min_stock=minimum,supply_link_slot=slot) for idx,good,price,minimum,slot in rows]


def get_cells(body,ctx):
    row,error=_mine(ctx)
    if error:return error
    building=core.building_details(row[2])
    return 200,{'enterprise_id':row[0],'capacity':building['retail_cells'],
                'allowed_goods':building['allowed_goods'],'cells':_read(ctx['conn'],row[0]),'balance':'draft'}


def put_cells(body,ctx):
    row,error=_mine(ctx)
    if error:return error
    if type(body) is not dict or set(body)!={'cells'}:
        return 400,{'error':'invalid_body'}
    try:
        cells=core.validate_cells(core.building_details(row[2]),body['cells'])
        # Supply links are per-SKU in V2-05, not per-cell. Validate the
        # requested supplier priority against existing shared SKU links.
        links={(good,slot) for good,slot in ctx['conn'].execute(
            'SELECT product_id,slot FROM supply_links WHERE enterprise_id=%s',(row[0],)).fetchall()}
        if any(cell['supply_link_slot'] is not None and
               (cell['product_id'],cell['supply_link_slot']) not in links for cell in cells):
            raise ValueError('unknown_supply_link')
    except (ValueError,TypeError) as exc:
        return 400,{'error':str(exc)}
    with ctx['conn'].transaction():
        ctx['conn'].execute('DELETE FROM retail_cells WHERE enterprise_id=%s',(row[0],))
        for cell in cells:
            ctx['conn'].execute("""INSERT INTO retail_cells
              (enterprise_id,cell_index,product_id,price,min_stock,supply_link_slot)
              VALUES(%s,%s,%s,%s,%s,%s)""",
              (row[0],cell['cell_index'],cell['product_id'],cell['price'],
               cell['min_stock'],cell['supply_link_slot']))
    return get_cells({},ctx)


def sales(body,ctx):
    row,error=_mine(ctx)
    if error:return error
    query=ctx.get('query',{})
    try:
        first=int(query.get('day_from',['0'])[0])
        last=int(query.get('day_to',[str(first+30)])[0])
        core.integer(first)
        core.integer(last,first,first+366)
    except (ValueError,TypeError,IndexError):
        return 400,{'error':'invalid_day_range'}
    records=ctx['conn'].execute("""SELECT day_index,cell_index,product_id,quantity,
         price,revenue,rating,vat_bp,city_id,district_id,income_layer FROM retail_sales_daily
         WHERE enterprise_id=%s AND day_index BETWEEN %s AND %s
         ORDER BY day_index,cell_index""",(row[0],first,last)).fetchall()
    return 200,{'enterprise_id':row[0],'day_from':first,'day_to':last,
                'sales':[dict(day_index=d,cell_index=c,product_id=g,quantity=q,
                  price=p,revenue=r,rating=rating,vat_bp=vat,city_id=city,
                  district_id=district,income_layer=layer)
                  for d,c,g,q,p,r,rating,vat,city,district,layer in records]}


def ratings(body,ctx):
    query=ctx.get('query',{})
    city=query.get('city',[''])[0]
    good=query.get('good',[''])[0]
    if city not in CITIES or good not in catalog().index['products']:
        return 400,{'error':'invalid_city_or_good'}
    rows=core._grouped(core._active_cells(ctx['conn'])).get((city,good),[])
    ranked=sorted(rows,key=lambda r:(-r['rating'],-r['appeal'],r['eid'],r['idx']))
    return 200,{'city':city,'good':good,'district_id':None,'income_layer':0,
                'ratings':[dict(enterprise_id=r['eid'],cell_index=r['idx'],
                  price=r['price'],rating=r['rating'],appeal=r['appeal'],
                  stock=r['stock']) for r in ranked],'balance':'draft'}
