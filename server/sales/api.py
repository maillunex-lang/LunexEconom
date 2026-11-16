"""Authenticated, bounded sales API. Caller owns its transaction."""
from __future__ import annotations

import re
from server.platform.api import authenticate
from server.enterprises import core as enterprises
from server.supply import core as supply
from . import core
from .model import price_valid

REQUEST = re.compile(r'^[A-Za-z0-9_.:-]{1,100}$')


def _enabled(ctx):
    return ctx.get('settings',{}).get('supply_sales_modes_enabled',False) is True


def _actor(ctx):
    return authenticate(ctx)


def _own(ctx):
    actor=_actor(ctx)
    if not actor:
        return None,None,(401,{'error':'unauthorized'})
    try:
        eid=enterprises.integer(int(ctx['path_params']['id']),1)
    except (KeyError,ValueError,TypeError):
        return actor,None,(404,{'error':'not_found'})
    row=ctx['conn'].execute('''SELECT id,owner_id,recipe_id FROM enterprises
        WHERE id=%s AND sold_at IS NULL''',(eid,)).fetchone()
    if not row or row[1]!=actor['id']:
        return actor,None,(404,{'error':'not_found'})
    return actor,row,None


def _product(ctx):
    product=ctx.get('path_params',{}).get('product')
    if not isinstance(product,str) or product not in enterprises.catalog().index['products']:
        return None
    return product


def _output(row, product):
    recipe=supply._recipe(row[2])
    return bool(recipe and product in recipe['outputs'])


def policy_get(body,ctx):
    actor,row,error=_own(ctx)
    if error:return error
    if not _enabled(ctx):return 404,{'error':'feature_disabled'}
    product=_product(ctx)
    if product is None or not _output(row,product):return 404,{'error':'unknown_output'}
    day=enterprises.today(ctx['conn'])
    return 200,{'enterprise_id':row[0], 'product_id':product,
                'day_index':day,'active':core.current_policy(ctx['conn'],row[0],product,day),
                'pending':core.pending_policy(ctx['conn'],row[0],product)}


def policy_put(body,ctx):
    actor,row,error=_own(ctx)
    if error:return error
    if not _enabled(ctx):return 404,{'error':'feature_disabled'}
    product=_product(ctx)
    if product is None or not _output(row,product):return 404,{'error':'unknown_output'}
    if not isinstance(body,dict) or not {'mode','reserve_bp','price','expected_version','request_id'}.issubset(body):
        return 400,{'error':'invalid_body'}
    if set(body)-{'mode','reserve_bp','price','expected_version','request_id','dry_run','invited_owner_ids'}:
        return 400,{'error':'invalid_body'}
    mode, reserve, price=body['mode'],body['reserve_bp'],body['price']
    if mode not in core.MODES or type(reserve) is not int or not 0<=reserve<=10000:
        return 400,{'error':'invalid_policy'}
    if mode!='mixed' and reserve not in (0,10000):
        return 400,{'error':'reserve_only_for_mixed'}
    flags=ctx['settings'];ref=enterprises.catalog().index['products'][product]['reference_price']
    try:
        if not price_valid(price,ref,flags['sales_price_min_bp'],flags['sales_price_max_bp'],
                           flags['sales_price_step_rub']):
            return 400,{'error':'price_out_of_range'}
        expected=enterprises.integer(body['expected_version'])
    except ValueError:
        return 400,{'error':'invalid_numeric_value'}
    request=body['request_id']
    if not isinstance(request,str) or not REQUEST.fullmatch(request):
        return 400,{'error':'invalid_request_id'}
    dry=body.get('dry_run',False)
    if type(dry) is not bool:return 400,{'error':'invalid_dry_run'}
    invites=body.get('invited_owner_ids',[])
    if not isinstance(invites,list) or len(invites)>50:
        return 400,{'error':'invalid_invites'}
    try:
        invites=sorted(set(enterprises.integer(i,1) for i in invites))
    except ValueError:
        return 400,{'error':'invalid_invites'}
    conn=ctx['conn'];eid=row[0];day=enterprises.today(conn)
    # Serialize policy edits by seller and SKU; session transactions own the locks.
    conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',
                 (f'sales:policy:{eid}:{product}',))
    previous=conn.execute('''SELECT enterprise_id,product_id,owner_id,mode,reserve_bp,
        price,version,effective_day FROM sales_policy_changes WHERE request_id=%s''',
        (request,)).fetchone()
    if previous:
        if previous[:6]!=(eid,product,actor['id'],mode,reserve,price):
            return 409,{'error':'request_id_conflict'}
        return 200,{'version':previous[6],'effective_day':previous[7],
                    'idempotent':True}
    current=core.pending_policy(conn,eid,product)
    version=current['version'] if current else 0
    if expected!=version:return 409,{'error':'version_conflict','current_version':version}
    if current and current['effective_day']>day:
        return 409,{'error':'pending_change_exists'}
    if mode=='private' and core.reserve_for_contracts(conn,eid,product,day):
        return 409,{'error':'active_contracts_block_private'}
    if mode=='invited' and invites:
        existing=conn.execute('SELECT id FROM accounts WHERE id=ANY(%s)',(invites,)).fetchall()
        if len(existing)!=len(invites):return 400,{'error':'unknown_invited_owner'}
    next_day=day+1
    preview={'enterprise_id':eid,'product_id':product,'mode':mode,
             'reserve_bp':reserve,'price':price,'effective_day':next_day,
             'version':version+1,'previous':current,'dry_run':dry}
    if dry:return 200,preview
    conn.execute('''INSERT INTO sales_policies
        (enterprise_id,product_id,mode,reserve_bp,price,effective_day,version)
        VALUES(%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT(enterprise_id,product_id) DO UPDATE SET
        mode=excluded.mode,reserve_bp=excluded.reserve_bp,price=excluded.price,
        effective_day=excluded.effective_day,version=excluded.version''',
        (eid,product,mode,reserve,price,next_day,version+1))
    conn.execute('''INSERT INTO sales_policy_changes
        (enterprise_id,product_id,request_id,owner_id,mode,reserve_bp,price,
         effective_day,version) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
        (eid,product,request,actor['id'],mode,reserve,price,next_day,version+1))
    if mode=='invited':
        conn.execute('DELETE FROM sales_invites WHERE enterprise_id=%s AND product_id=%s',
                     (eid,product))
        for oid in invites:
            conn.execute('''INSERT INTO sales_invites
                (enterprise_id,product_id,buyer_owner_id) VALUES(%s,%s,%s)''',
                (eid,product,oid))
    return 200,preview


def _query(ctx,key):
    values=ctx.get('query',{}).get(key,[])
    return values[0] if len(values)==1 else None


def offers(body,ctx):
    actor=_actor(ctx)
    if not actor:return 401,{'error':'unauthorized'}
    if not _enabled(ctx):return 404,{'error':'feature_disabled'}
    city,product=_query(ctx,'city'),_query(ctx,'product')
    if not city or product not in enterprises.catalog().index['products']:
        return 400,{'error':'invalid_query'}
    day=enterprises.today(ctx['conn'])
    results=[]
    rows=ctx['conn'].execute('''SELECT e.id,e.owner_id,e.recipe_id,i.quantity,
        i.quality,e.city_id,e.x,e.y FROM enterprises e JOIN enterprise_inventory i
        ON i.enterprise_id=e.id AND i.product_id=%s
        WHERE e.sold_at IS NULL AND e.stage=4 AND e.running AND i.quantity>0
        ORDER BY e.id LIMIT 500''',(product,)).fetchall()
    for eid,owner,recipe,quantity,quality,place,x,y in rows:
        if supply._city(place,x,y)!=city:
            continue
        policy=core.current_policy(ctx['conn'],eid,product,day)
        if not policy or not _output((eid,owner,recipe),product):continue
        entitled=owner==actor['id'] or core.seller_allowed(
            ctx['conn'],eid,actor['id'],product,day,via_market=True)
        if not entitled:continue
        if policy['mode']=='private' and owner!=actor['id']:continue
        if policy['mode']=='mixed' and owner!=actor['id']:
            quantity-=quantity*policy['reserve_bp']//10000
        quantity=max(0,quantity-core.reserve_for_contracts(ctx['conn'],eid,product,day))
        results.append({'seller_enterprise_id':eid,'product_id':product,
                        'price':policy['price'],'quality':quality,
                        'stock_class':('нет' if quantity==0 else 'мало' if quantity<20
                                       else 'есть' if quantity<200 else 'много'),
                        'reliability':core.reliability(ctx['conn'],eid,product,day),
                        'mode':policy['mode'] if owner==actor['id'] else
                               'public' if policy['mode'] in ('public','mixed') else 'invited'})
    return 200,{'city':city,'product_id':product,'offers':results[:100]}


def contract(body,ctx):
    actor=_actor(ctx)
    if not actor:return 401,{'error':'unauthorized'}
    if not _enabled(ctx):return 404,{'error':'feature_disabled'}
    if not isinstance(body,dict) or set(body)!={'seller_enterprise_id','buyer_enterprise_id',
        'product_id','volume','start_day','end_day','price','request_id'}:
        return 400,{'error':'invalid_body'}
    try:
        seller=enterprises.integer(body['seller_enterprise_id'],1)
        buyer=enterprises.integer(body['buyer_enterprise_id'],1)
        volume=enterprises.integer(body['volume'],1)
        start=enterprises.integer(body['start_day']);end=enterprises.integer(body['end_day'],start)
        price=enterprises.integer(body['price'],1)
    except ValueError:
        return 400,{'error':'invalid_numbers'}
    request=body['request_id'];product=body['product_id']
    if not isinstance(request,str) or not REQUEST.fullmatch(request):
        return 400,{'error':'invalid_request_id'}
    if product not in enterprises.catalog().index['products'] or seller==buyer:
        return 400,{'error':'invalid_contract'}
    conn=ctx['conn']
    conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',
                 ('sales:contract:'+request,))
    previous=conn.execute('''SELECT id,seller_enterprise_id,buyer_enterprise_id,
        product_id,volume,start_day,end_day,price FROM sales_contract_reservations
        WHERE request_id=%s''',(request,)).fetchone()
    if previous:
        if previous[1:]!=(seller,buyer,product,volume,start,end,price):
            return 409,{'error':'request_id_conflict'}
        return 200,{'contract_id':previous[0],'idempotent':True}
    owners=conn.execute('''SELECT id,owner_id,recipe_id FROM enterprises
        WHERE id IN (%s,%s) AND sold_at IS NULL ORDER BY id FOR UPDATE''',
        (seller,buyer)).fetchall()
    if len(owners)!=2:return 404,{'error':'not_found'}
    keyed={r[0]:r for r in owners}
    if keyed[seller][1]!=actor['id']:
        return 404,{'error':'not_found'}
    if keyed[seller][1]==keyed[buyer][1]:
        return 400,{'error':'same_owner_contract'}
    if not _output(keyed[seller],product):return 400,{'error':'not_produced'}
    day=enterprises.today(conn)
    if start<day or end>day+365:
        return 400,{'error':'invalid_term'}
    policy=core.current_policy(conn,seller,product,day)
    if policy and policy['mode']=='private':return 409,{'error':'private_mode'}
    reference=enterprises.catalog().index['products'][product]['reference_price']
    flags=ctx['settings']
    try:
        valid=price_valid(price,reference,flags['sales_price_min_bp'],
                          flags['sales_price_max_bp'],flags['sales_price_step_rub'])
    except ValueError:
        valid=False
    if not valid:return 400,{'error':'price_out_of_range'}
    available=enterprises.stock(conn,seller).get(product,{}).get('quantity',0)
    reserved=core.reserve_for_contracts(conn,seller,product,day)
    if volume>max(0,available-reserved):return 409,{'error':'insufficient_unreserved_stock'}
    cid=conn.execute('''INSERT INTO sales_contract_reservations
        (request_id,seller_enterprise_id,buyer_enterprise_id,product_id,volume,
         reserved_remaining,start_day,end_day,price)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',
        (request,seller,buyer,product,volume,volume,start,end,price)).fetchone()[0]
    return 201,{'contract_id':cid,'reserved':volume}


def daily(body,ctx):
    actor,row,error=_own(ctx)
    if error:return error
    if not _enabled(ctx):return 404,{'error':'feature_disabled'}
    try:
        day=enterprises.integer(int(_query(ctx,'day') or enterprises.today(ctx['conn'])))
    except ValueError:
        return 400,{'error':'invalid_day'}
    rows=ctx['conn'].execute('''SELECT product_id,offered,shipped,unfilled,revenue
        FROM sales_metrics_daily WHERE seller_enterprise_id=%s AND day_index=%s
        ORDER BY product_id LIMIT 200''',(row[0],day)).fetchall()
    return 200,{'enterprise_id':row[0],'day_index':day,'products':[
        dict(product_id=p,offered=o,shipped=s,unfilled=u,revenue=r)
        for p,o,s,u,r in rows]}


def quotes(body,ctx):
    actor=_actor(ctx)
    if not actor:return 401,{'error':'unauthorized'}
    if not _enabled(ctx):return 404,{'error':'feature_disabled'}
    return 200,{'notice':'Use /supply/offers for supply quotes; final delivery charged at purchase.'}


def purchase(body,ctx):
    actor=_actor(ctx)
    if not actor:return 401,{'error':'unauthorized'}
    if not _enabled(ctx):return 404,{'error':'feature_disabled'}
    if not isinstance(body,dict) or set(body)!={'buyer_enterprise_id','seller_enterprise_id',
        'product_id','quantity','request_id'}:
        return 400,{'error':'invalid_body'}
    try:
        seller=enterprises.integer(body['seller_enterprise_id'],1)
        buyer=enterprises.integer(body['buyer_enterprise_id'],1)
        quantity=enterprises.integer(body['quantity'],1)
    except ValueError:
        return 400,{'error':'invalid_numbers'}
    product=body['product_id'];request=body['request_id']
    if not isinstance(request,str) or not REQUEST.fullmatch(request):
        return 400,{'error':'invalid_request_id'}
    if product not in enterprises.catalog().index['products'] or buyer==seller:
        return 400,{'error':'invalid_purchase'}
    conn=ctx['conn']
    conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('sales:purchase:'+request,))
    previous=conn.execute('''SELECT buyer_enterprise_id,seller_enterprise_id,product_id,
        quantity,unit_price,day_index FROM sales_purchase_receipts WHERE request_id=%s''',
        (request,)).fetchone()
    owner=conn.execute('SELECT owner_id FROM enterprises WHERE id=%s AND sold_at IS NULL',
                       (buyer,)).fetchone()
    if not owner or owner[0]!=actor['id']:return 404,{'error':'not_found'}
    if previous:
        if previous[:4]!=(buyer,seller,product,quantity):
            return 409,{'error':'request_id_conflict'}
        return 200,{'quantity':quantity,'unit_price':previous[4],'idempotent':True}
    day=enterprises.today(conn)
    policy=core.current_policy(conn,seller,product,day)
    if not policy or not core.seller_allowed(conn,seller,actor['id'],product,day):
        return 403,{'error':'not_for_sale'}
    if policy['mode']=='private':return 403,{'error':'private_mode'}
    seller_owner=conn.execute('SELECT owner_id FROM enterprises WHERE id=%s',(seller,)).fetchone()
    if not seller_owner or seller_owner[0]==actor['id']:
        return 403,{'error':'self_trade'}
    # Serialize all manual spot buyers for a seller/SKU/day in one advisory
    # queue. Inventory is locked by _purchase, preventing TOCTOU overselling.
    conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',
                 (f'sales:spot:{seller}:{product}:{day}',))
    available=enterprises.stock(conn,seller).get(product,{}).get('quantity',0)
    own,contracts,spot=core.offer_quantities(available,policy['mode'],policy['reserve_bp'],
                                             core.reserve_for_contracts(conn,seller,product,day))
    if quantity>spot:return 409,{'error':'insufficient_spot_stock'}
    # No client can bypass the per-holding 40% aggregate cap through repeated orders.
    city=conn.execute('SELECT city_id FROM enterprises WHERE id=%s',(seller,)).fetchone()[0]
    sold=conn.execute('''SELECT COALESCE(sum(quantity),0) FROM sales_purchase_receipts r
        JOIN enterprises b ON b.id=r.buyer_enterprise_id
        JOIN enterprises s ON s.id=r.seller_enterprise_id
        WHERE b.owner_id=%s AND r.product_id=%s AND r.day_index=%s AND s.city_id=%s''',
        (actor['id'],product,day,city)).fetchone()[0]
    cap=available*ctx['settings']['sales_market_share_cap_bp']//10000
    if sold+quantity>cap:return 409,{'error':'market_share_cap'}
    score=core.quote_score(conn,seller,buyer,product,policy['price'],
                           enterprises.stock(conn,seller).get(product,{}).get('quality',50),
                           day,ctx['settings'])
    if score is None:return 409,{'error':'uncompetitive_or_low_quality'}
    try:
        with conn.transaction():
            core._purchase(conn,seller,buyer,product,quantity,day,policy['price'],
                           ctx['settings'],request)
    except ValueError as exc:
        if str(exc) in ('insufficient_balance','insufficient_stock','warehouse_full','insufficient_fuel'):
            return 409,{'error':str(exc)}
        raise
    return 201,{'quantity':quantity,'unit_price':policy['price'],'score':score}
