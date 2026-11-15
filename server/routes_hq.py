"""Dedicated HQ routing. Authorization is done by game_server.Handler._identity."""
import json

import auto_managers
import holding
import hq_api


def get(db, ph, owner, path, query):
    if not owner:
        return 401,{'error':'unauthorized'}
    holding.ensure(db,ph)
    if path == '/hq':
        import game_server
        import os
        scope = os.environ.get('LUNEX_PG_DB','postgres') if ph=='%s' else game_server.DB
        return hq_api.snapshot(db,ph,owner,cache=True,scope=scope)
    if path == '/finance/overview':
        return 200,holding.overview(db,ph,owner)
    if path == '/enterprise':
        ids = query.get('id',[])
        return hq_api.enterprise(db,ph,owner,ids[0] if len(ids)==1 else '')
    return 404,{'error':'not_found'}


def post(db,ph,owner,path,payload,now):
    if not owner: return 401,{'error':'unauthorized'}
    if path != '/enterprise/settings':return 404,{'error':'not_found'}
    if not isinstance(payload,dict):return 400,{'error':'invalid_body'}
    bid=payload.get('id')
    if not isinstance(bid,str) or not 1<=len(bid)<=100:return 400,{'error':'invalid_id'}
    row=db.execute('SELECT owner FROM buildings WHERE id='+ph,(bid,)).fetchone()
    if row is None:return 404,{'error':'not_found'}
    if row[0]!=owner:return 403,{'error':'not_owner'}
    allowed={'id','name','price','price_rule','min_stock','buy_limit','auto_managers'}
    if any(k not in allowed for k in payload):return 400,{'error':'unknown_setting'}
    old=db.execute('SELECT name,price,price_rule,min_stock,buy_limit,managers FROM enterprise_settings WHERE object_id='+ph,(bid,)).fetchone()
    if old is None:old=('' ,None,'market','{}',0,'{}')
    name=payload.get('name',old[0]); price=payload.get('price',old[1]); rule=payload.get('price_rule',old[2])
    minimum=payload.get('min_stock',json.loads(old[3])); limit=payload.get('buy_limit',old[4]); managers=payload.get('auto_managers',json.loads(old[5]))
    if not isinstance(name,str) or len(name)>80 or any(ord(c)<32 for c in name):return 400,{'error':'invalid_name'}
    if price is not None and (type(price) is not int or price<1 or price>1_000_000_000):return 400,{'error':'invalid_price'}
    if rule not in ('market','manual','reference'):return 400,{'error':'invalid_price_rule'}
    if rule=='manual' and price is None:return 400,{'error':'price_required'}
    if not isinstance(minimum,dict) or len(minimum)>80 or any(not isinstance(k,str) or len(k)>60 or type(v) is not int or v<0 or v>10**9 for k,v in minimum.items()):
        return 400,{'error':'invalid_min_stock'}
    if type(limit) is not int or not 0<=limit<=10**12:return 400,{'error':'invalid_buy_limit'}
    try:auto_managers.validate(managers)
    except ValueError:return 400,{'error':'invalid_auto_managers'}
    holding.ensure(db,ph)
    db.execute('INSERT INTO enterprise_settings(object_id,owner,name,price,price_rule,min_stock,buy_limit,managers) VALUES('+','.join([ph]*8)+') ON CONFLICT(object_id) DO UPDATE SET name=excluded.name,price=excluded.price,price_rule=excluded.price_rule,min_stock=excluded.min_stock,buy_limit=excluded.buy_limit,managers=excluded.managers',
               (bid,owner,name,price,rule,json.dumps(minimum,ensure_ascii=False),limit,json.dumps(managers,ensure_ascii=False)))
    with hq_api._cache_lock:hq_api._cache.clear()
    return 200,{'ok':True,'id':bid}