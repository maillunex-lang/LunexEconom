"""V2-05: integer-only, per-buyer isolated supply clearing.

Daily phases are intentionally split: links at order 20, market at 30,
enterprise production at 40. Each phase is idempotent for the same day.
"""
from __future__ import annotations

from collections import defaultdict
from server.enterprises import core as enterprise
from server.ledger.api import account,transfer
from server.world import core as world

MAX=2**63-1
PERMILLE=1000

def _int(value,lower=0,upper=MAX):
    if type(value) is not int or not lower<=value<=upper:
        raise ValueError('invalid_integer')
    return value

def _recipe(row):
    return enterprise.catalog().index['recipes'].get(row[2]) if row[2] else None

def validate_links(conn,enterprise_row,inputs):
    if not isinstance(inputs,dict):
        raise ValueError('invalid_inputs')
    recipe=_recipe(enterprise_row)
    allowed=set(recipe['inputs']) if recipe else set()
    if not set(inputs)<=allowed:
        raise ValueError('not_own_input')
    output=[]
    for product,suppliers in sorted(inputs.items()):
        if not isinstance(suppliers,list) or len(suppliers)>3:
            raise ValueError('too_many_suppliers')
        shares=0
        priorities=set()
        sources=set()
        for index,item in enumerate(suppliers,1):
            if not isinstance(item,dict) or set(item)-{'source_type','source_enterprise_id','share','priority','max_price','min_quality'}:
                raise ValueError('invalid_link')
            typ=item.get('source_type')
            if typ not in ('enterprise','market','port'):
                raise ValueError('invalid_source_type')
            sid=item.get('source_enterprise_id')
            if typ=='enterprise':
                _int(sid,1)
                if sid==enterprise_row[0]:
                    raise ValueError('self_supply')
                found=conn.execute('SELECT id,recipe_id FROM enterprises WHERE id=%s AND sold_at IS NULL',(sid,)).fetchone()
                if found is None:
                    raise ValueError('unknown_supplier')
                recipe_src=_recipe(found)
                if not recipe_src or product not in recipe_src['outputs']:
                    raise ValueError('supplier_does_not_produce_product')
            elif sid is not None:
                raise ValueError('unexpected_supplier_id')
            share=_int(item.get('share'),1,1000)
            priority=_int(item.get('priority'),1,3)
            max_price=_int(item.get('max_price'),0)
            min_quality=_int(item.get('min_quality'),0,100)
            if priority in priorities or (typ,sid) in sources:
                raise ValueError('duplicate_supplier_or_priority')
            priorities.add(priority);sources.add((typ,sid))
            shares+=share
            output.append((product,dict(slot=index,source_type=typ,source_enterprise_id=sid,share=share,
                                        priority=priority,max_price=max_price,min_quality=min_quality)))
        if shares>1000:
            raise ValueError('share_exceeds_1000')
    return output

def read_links(conn,eid):
    rows=conn.execute('SELECT product_id,source_type,source_enterprise_id,share,priority,max_price,min_quality FROM supply_links WHERE enterprise_id=%s ORDER BY product_id,priority,slot',(eid,)).fetchall()
    result={}
    for product,typ,sid,share,priority,max_price,min_quality in rows:
        result.setdefault(product,[]).append(dict(source_type=typ,source_enterprise_id=sid,share=share,
                    priority=priority,max_price=max_price,min_quality=min_quality))
    return result

def _enterprises(conn):
    return conn.execute("""SELECT id,owner_id,recipe_id,city_id,stage,running,storage_capacity
        FROM enterprises WHERE sold_at IS NULL ORDER BY id""").fetchall()

def _wallet(conn,owner):
    return conn.execute("""SELECT l.id,l.balance FROM ledger_accounts l
        JOIN accounts a ON l.account_key='player:'||lower(a.username)
        WHERE a.id=%s FOR UPDATE""",(owner,)).fetchone()

def _free(conn,eid,capacity):
    return max(0,capacity-enterprise.stock_total(conn,eid)-
               int(conn.execute("SELECT COALESCE(sum(quantity),0) FROM shipments WHERE buyer_enterprise_id=%s AND status<>'delivered'",(eid,)).fetchone()[0]))

def _need(conn,row):
    eid,_,recipe_id,_,stage,running,capacity=row
    recipe=enterprise.catalog().index['recipes'].get(recipe_id) if recipe_id else None
    if not recipe or stage!=4 or not running:
        return {}
    if conn.execute('SELECT 1 FROM enterprise_arrears WHERE enterprise_id=%s AND paid_at IS NULL LIMIT 1',(eid,)).fetchone():
        return {}
    items=enterprise.stock(conn,eid)
    # Full one-day recipe input buffer, replenished after each production day.
    free=_free(conn,eid,capacity)
    result={}
    for product,volume in recipe['inputs'].items():
        current=items.get(product,{}).get('quantity',0)
        target=max(volume,recipe['inputs'][product])
        needed=max(0,target-current)
        quantity=min(needed,free)
        result[product]=quantity
        free-=quantity
    return result

def _travel(source_city,dest_city,qty,transport_rate):
    if not source_city or not dest_city or source_city==dest_city:
        return 0,0
    route=world.routes(source_city,dest_city)
    # ceil(game_minutes/1440) >= one day for intercity transport
    days=max(1,(route['game_minutes']+1439)//1440)
    # Distance rounding floor, charged once for the batch.
    transport=route['distance_meters']*qty*transport_rate//1000
    return days,_int(transport)

def _payment(conn,request_id,payer_id,seller_account,amount):
    if amount==0:return None
    return transfer(conn,request_id,payer_id,seller_account,_int(amount,1))

def _shipment(conn,request_id,buyer,seller,typ,product,qty,quality,price,transport,day,arrival,tid):
    conn.execute("""INSERT INTO shipments(request_id,buyer_enterprise_id,seller_enterprise_id,source_type,product_id,quantity,quality,unit_price,transport_cost,dispatched_day,arrival_day,status,transfer_id)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT(request_id) DO NOTHING""",
        (request_id,buyer,seller,typ,product,qty,quality,price,transport,day,arrival,
         'delivered' if arrival==day else 'transit',tid))
    if arrival==day:
        enterprise.adjust(conn,buyer,product,qty,quality)

def _buy(conn,day,row,product,qty,source_type,source_id,unit_price,min_quality,flags,sequence):
    """One atomic goods + ledger movement. Insufficient funds do not abort the day."""
    eid,owner,_,city,_,_,capacity=row
    qty=min(qty,_free(conn,eid,capacity))
    if qty<=0:return 0
    buyer=_wallet(conn,owner)
    if buyer is None:return 0
    seller_city=None
    quality=50
    if source_type=='enterprise':
        src=conn.execute('SELECT owner_id,city_id FROM enterprises WHERE id=%s AND sold_at IS NULL FOR UPDATE',(source_id,)).fetchone()
        if not src:return 0
        seller_owner,seller_city=src
        stock=enterprise.stock(conn,source_id).get(product,{'quantity':0,'quality':0})
        if stock['quality']<min_quality:return 0
        qty=min(qty,stock['quantity'])
        quality=stock['quality']
        if qty<=0:return 0
        payee=_wallet(conn,seller_owner)
        if payee is None:return 0
        seller=payee[0]
        if seller==buyer[0]:
            unit_price=0
    else:
        if min_quality>quality:return 0
        seller=account(conn,'system:market')
        if source_type=='port':
            seller_city=flags['supply_port_city_draft']
    days,transport=_travel(seller_city,city,qty,flags['supply_transport_rub_per_km_unit_draft'])
    if source_type=='port':days=max(1,days)
    total=_int(qty*unit_price+transport)
    if total>buyer[1]:return 0
    request_id=f'supply:{eid}:{product}:{day}:{source_type}-{source_id or "system"}:{sequence}'
    if len(request_id)>128:raise ValueError('request_id too long')
    with conn.transaction():
        if source_type=='enterprise':
            enterprise.adjust(conn,source_id,product,-qty)
        purchase=qty*unit_price
        tid=_payment(conn,request_id,buyer[0],seller,purchase) if purchase else None
        if transport:
            _payment(conn,request_id+':transport',buyer[0],account(conn,'system:market'),transport)
        _shipment(conn,request_id,eid,source_id,source_type,product,qty,quality,unit_price,transport,day,day+days,tid)
    return qty

def _record_need(conn,row,product,day,requested):
    conn.execute("""INSERT INTO supply_daily_needs(enterprise_id,product_id,day_index,requested,unfilled)
        VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",(row[0],product,day,requested,requested))

def _deliver_arrivals(conn,day):
    due=conn.execute("""SELECT id,buyer_enterprise_id,product_id,quantity,quality FROM shipments
        WHERE arrival_day<=%s AND status<>'delivered' ORDER BY id FOR UPDATE""",(day,)).fetchall()
    for sid,eid,product,qty,quality in due:
        row=conn.execute('SELECT storage_capacity FROM enterprises WHERE id=%s AND sold_at IS NULL FOR UPDATE',(eid,)).fetchone()
        if not row or enterprise.stock_total(conn,eid)+qty>row[0]:
            conn.execute("UPDATE shipments SET status='waiting_capacity' WHERE id=%s",(sid,))
            continue
        enterprise.adjust(conn,eid,product,qty,quality)
        conn.execute("UPDATE shipments SET status='delivered' WHERE id=%s",(sid,))

def links_day(conn,day,flags):
    _int(day)
    if conn.execute("SELECT 1 FROM supply_receipts WHERE day_index=%s AND phase='links'",(day,)).fetchone():
        return
    _deliver_arrivals(conn,day)
    rows=_enterprises(conn)
    for row in rows:
        eid=row[0]
        for product,requested in sorted(_need(conn,row).items()):
            _record_need(conn,row,product,day,requested)
            remaining=requested
            linked=0
            links=conn.execute("""SELECT source_type,source_enterprise_id,share,priority,max_price,min_quality FROM supply_links
                WHERE enterprise_id=%s AND product_id=%s ORDER BY priority,slot""",(eid,product)).fetchall()
            for index,(source,sid,share,priority,max_price,min_quality) in enumerate(links,1):
                if remaining==0:break
                if source!='enterprise':continue
                quoted=enterprise.catalog().index['products'][product]['reference_price']
                if quoted>max_price:continue
                allocated=requested*share//1000
                if allocated<=0:continue
                try:
                    filled=_buy(conn,day,row,product,min(remaining,allocated),source,sid,quoted,min_quality,flags,index)
                except ValueError as exc:
                    if str(exc)=='insufficient balance':
                        filled=0
                    else:raise
                linked+=filled
                remaining-=filled
            conn.execute("""UPDATE supply_daily_needs SET linked=%s,unfilled=%s
                WHERE enterprise_id=%s AND product_id=%s AND day_index=%s""",(linked,remaining,eid,product,day))
    conn.execute("INSERT INTO supply_receipts(day_index,phase) VALUES(%s,'links')",(day,))

def market_day(conn,day,flags):
    from server.market.core import clearing_price
    if conn.execute("SELECT 1 FROM supply_receipts WHERE day_index=%s AND phase='market'",(day,)).fetchone():return
    if not conn.execute("SELECT 1 FROM supply_receipts WHERE day_index=%s AND phase='links'",(day,)).fetchone():
        raise ValueError('links_phase_missing')
    rows={r[0]:r for r in _enterprises(conn)}
    # Residual offers are drawn from producer stock only, not raw NPC minting.
    offers=defaultdict(list)
    for eid,owner,recipe,city,stage,running,capacity in rows.values():
        if stage!=4 or not city or not running or not recipe:continue
        for product in enterprise.catalog().index['recipes'][recipe]['outputs']:
            stock=enterprise.stock(conn,eid).get(product,{'quantity':0,'quality':50})
            if stock['quantity']>0:offers[(city,product)].append([eid,stock['quantity'],stock['quality']])
    demands=defaultdict(list)
    for eid,product,quantity in conn.execute("""SELECT enterprise_id,product_id,unfilled FROM supply_daily_needs
       WHERE day_index=%s AND unfilled>0 ORDER BY enterprise_id,product_id""",(day,)).fetchall():
        city=rows[eid][3]
        if city:demands[(city,product)].append([eid,quantity])
    for city,product in sorted(set(offers)|set(demands)):
        bid=demands[(city,product)]
        ask=offers[(city,product)]
        demand=sum(q for _,q in bid);supply=sum(q for _,q,_ in ask)
        reference=enterprise.catalog().index['products'][product]['reference_price']
        price=clearing_price(reference,demand,supply)
        volume=0
        for eid,requested in bid:
            buyer=rows[eid];remaining=requested
            links=conn.execute("""SELECT source_type,share,max_price,min_quality,priority FROM supply_links
                WHERE enterprise_id=%s AND product_id=%s ORDER BY priority""",(eid,product)).fetchall()
            market_links=[l for l in links if l[0]=='market']
            market_limit=min(remaining,sum(requested*l[1]//1000 for l in market_links)) if market_links else remaining
            price_cap=max((l[2] for l in market_links),default=MAX)
            quality_min=min((l[3] for l in market_links),default=0)
            if price<=price_cap:
                for offer in ask:
                    if market_limit<=0:break
                    seller_id,available,quality=offer
                    if seller_id==eid or available==0 or quality<quality_min:continue
                    try:
                        filled=_buy(conn,day,buyer,product,min(market_limit,available), 'enterprise',seller_id,price,quality_min,flags,100000+seller_id)
                    except ValueError as exc:
                        if str(exc)=='insufficient balance':filled=0
                        else:raise
                    offer[1]-=filled;market_limit-=filled;remaining-=filled;volume+=filled
            market_filled=requested-remaining
            # Unsold or unfunded residual can route to the port, explicitly only.
            port_links=[l for l in links if l[0]=='port']
            if remaining>0 and (port_links or flags['supply_port_fallback_draft']):
                cap=max((l[2] for l in port_links),default=MAX)
                quality=max((l[3] for l in port_links),default=0)
                port_ref=reference*flags['supply_port_price_permille_draft']//1000
                duty=port_ref*flags['supply_port_duty_bp_draft']//10000
                quote=port_ref+duty
                if quote<=cap and quality<=50:
                    for portion in [remaining]:
                        try:
                            bought=_buy(conn,day,buyer,product,portion,'port',None,quote,50,flags,900000)
                        except ValueError as exc:
                            if str(exc)=='insufficient balance':bought=0
                            else:raise
                        remaining-=bought
                        conn.execute("UPDATE supply_daily_needs SET port_ordered=port_ordered+%s WHERE enterprise_id=%s AND product_id=%s AND day_index=%s",(bought,eid,product,day))
            conn.execute("""UPDATE supply_daily_needs SET market_filled=%s,unfilled=%s WHERE enterprise_id=%s AND product_id=%s AND day_index=%s""",
                (market_filled,remaining,eid,product,day))
        conn.execute("""INSERT INTO market_prices(city_id,product_id,day_index,price,demand,supply,volume)
            VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",(city,product,day,price,demand,supply,volume))
    conn.execute("INSERT INTO supply_receipts(day_index,phase) VALUES(%s,'market')",(day,))
