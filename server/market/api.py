"""Market quotes and history; public read-only API."""
from server.world.core import CITIES
from server.enterprises.core import catalog

def city_for(city_id):
    def handler(body,ctx):
        return _city(ctx,city_id)
    return handler

def city(body,ctx):
    # Kept for a future generic route-capable dispatcher.
    city_id=ctx.get('path_params',{}).get('city')
    return _city(ctx,city_id)

def _city(ctx,city_id):
    if city_id not in CITIES:
        return 404,{'error':'unknown_city'}
    day=ctx['conn'].execute('SELECT MAX(day_index) FROM market_prices WHERE city_id=%s',(city_id,)).fetchone()[0]
    if day is None:
        return 200,{'city':city_id,'day_index':None,'products':[],'balance':'draft'}
    rows=ctx['conn'].execute('SELECT product_id,price,demand,supply,volume FROM market_prices WHERE city_id=%s AND day_index=%s ORDER BY product_id',(city_id,day)).fetchall()
    return 200,{'city':city_id,'day_index':day,'products':[dict(product_id=p,price=price,demand=d,supply=s,volume=v) for p,price,d,s,v in rows],'balance':'draft'}

def history(body,ctx):
    query=ctx.get('query',{})
    city_id=query.get('city',[''])[0]
    product=query.get('product',[''])[0]
    if city_id not in CITIES or product not in catalog().index['products']:
        return 400,{'error':'invalid_city_or_product'}
    rows=ctx['conn'].execute('SELECT day_index,price,demand,supply,volume FROM market_prices WHERE city_id=%s AND product_id=%s ORDER BY day_index DESC LIMIT 100',(city_id,product)).fetchall()
    return 200,{'city':city_id,'product_id':product,'history':[dict(day_index=d,price=p,demand=n,supply=s,volume=v) for d,p,n,s,v in rows],'balance':'draft'}
