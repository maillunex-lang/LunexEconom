"""Daily sales policy lifecycle and settlement, isolated behind the opt-in flag."""
from __future__ import annotations

from server.enterprises import core as enterprise
from server.supply import core as supply
from .model import allocate_fair, cap_requests_by_owner, supplier_score

MAX = enterprise.MAX
MODES = ('private', 'public', 'mixed', 'invited')


def current_policy(conn, eid, product, day):
    """Only applied versions are visible. Pending updates never leak into ticks."""
    row = conn.execute('''SELECT mode,reserve_bp,price,version,effective_day
        FROM sales_policy_changes WHERE enterprise_id=%s AND product_id=%s
        AND effective_day<=%s ORDER BY version DESC LIMIT 1''',
        (eid, product, day)).fetchone()
    return dict(zip(('mode','reserve_bp','price','version','effective_day'), row)) if row else None


def pending_policy(conn, eid, product):
    row = conn.execute('''SELECT mode,reserve_bp,price,version,effective_day
        FROM sales_policies WHERE enterprise_id=%s AND product_id=%s''',
        (eid, product)).fetchone()
    return dict(zip(('mode','reserve_bp','price','version','effective_day'), row)) if row else None


def seller_allowed(conn, seller, buyer_owner, product, day, *, via_market=False):
    policy = current_policy(conn, seller, product, day)
    row = conn.execute('SELECT owner_id FROM enterprises WHERE id=%s', (seller,)).fetchone()
    if row is None:
        return False
    if row[0] == buyer_owner:
        return True
    if policy is None:
        consent = conn.execute('''SELECT allow_direct_sales,allow_city_market
            FROM supply_seller_policy WHERE enterprise_id=%s''', (seller,)).fetchone()
        return bool(consent and consent[1 if via_market else 0])
    if policy['mode'] == 'private':
        # Existing binding contracts survive private policy switches.
        return bool(conn.execute("""SELECT 1 FROM sales_contract_reservations c
            JOIN enterprises b ON b.id=c.buyer_enterprise_id
            WHERE c.seller_enterprise_id=%s AND c.product_id=%s AND b.owner_id=%s
            AND c.status='active' AND c.reserved_remaining>0
            AND c.start_day<=%s AND c.end_day>=%s LIMIT 1""",
            (seller,product,buyer_owner,day,day)).fetchone())
    if policy['mode'] in ('public','mixed'):
        return True
    return bool(conn.execute('''SELECT 1 FROM sales_invites WHERE enterprise_id=%s
        AND product_id=%s AND buyer_owner_id=%s AND active''',
        (seller,product,buyer_owner)).fetchone() or conn.execute('''SELECT 1
        FROM sales_contract_reservations c JOIN enterprises b ON b.id=c.buyer_enterprise_id
        WHERE c.seller_enterprise_id=%s AND c.product_id=%s AND b.owner_id=%s
        AND c.status='active' AND c.start_day<=%s AND c.end_day>=%s LIMIT 1''',
        (seller,product,buyer_owner,day,day)).fetchone())


def reliability(conn, eid, product, day):
    row = conn.execute('''SELECT COALESCE(sum(ordered),0),COALESCE(sum(fulfilled),0)
        FROM sales_reliability_30d WHERE enterprise_id=%s AND product_id=%s
        AND day_index BETWEEN %s AND %s''',
        (eid,product,max(0,day-29),day)).fetchone()
    return min(1000,row[1]*1000//row[0]) if row[0] else 700


def quote_score(conn, seller, buyer, product, price, quality, day, flags):
    """Gate-price score using confirmed route distance and optional real port cap."""
    seller_city = conn.execute('SELECT city_id,x,y FROM enterprises WHERE id=%s', (seller,)).fetchone()
    buyer_city = conn.execute('SELECT city_id,x,y FROM enterprises WHERE id=%s', (buyer,)).fetchone()
    if not seller_city or not buyer_city:
        return None
    source = supply._city(*seller_city)
    target = supply._city(*buyer_city)
    route = 0 if source == target else supply.world.routes(source,target)['distance_meters']//1000
    reference = enterprise.catalog().index['products'][product]['reference_price']
    # Port comparison is meaningful only when port is an actual enabled option.
    port = None
    if flags.get('supply_port_fallback_draft'):
        port_city = supply._port(flags,target)
        port_distance = (0 if port_city == target else
                         supply.world.routes(port_city,target)['distance_meters']//1000)
        port_price = reference*flags['supply_port_price_permille_draft']//1000
        port_price += port_price*flags['supply_port_duty_bp_draft']//10000
        port = port_price + port_distance*flags['supply_transport_rub_per_km_unit_draft']
    cfg = {'reference_price_rub':reference,'port_price_rub':MAX//4,
           'min_acceptable_quality':45,'freight_rub_per_distance_unit':flags['supply_transport_rub_per_km_unit_draft'],
           'price_score_weight_bp':4000,'quality_score_weight_bp':2500,
           'reliability_score_weight_bp':2000,'distance_score_weight_bp':1500,
           'score_cutoff':flags.get('sales_score_cutoff',570)}
    # Unavailable ports have no pricing ceiling.
    return supplier_score(price,quality,reliability(conn,seller,product,day),route,cfg,
                          port_delivered=port if port is not None else MAX//4)


def reserve_for_contracts(conn, seller, product, day):
    return int(conn.execute('''SELECT COALESCE(sum(reserved_remaining),0)
        FROM sales_contract_reservations WHERE seller_enterprise_id=%s
        AND product_id=%s AND status='active' AND start_day<=%s AND end_day>=%s''',
        (seller,product,day,day)).fetchone()[0])


def offer_quantities(stock, mode, reserve_bp, contracts):
    enterprise.integer(stock); enterprise.integer(reserve_bp,0,10000)
    enterprise.integer(contracts)
    own = stock if mode == 'private' else (stock*reserve_bp//10000 if mode=='mixed' else 0)
    contracted = min(stock-own,contracts)
    spot = 0 if mode=='private' else stock-own-contracted
    return own, contracted, spot


def _inventory(conn,seller,product):
    row=conn.execute('''SELECT quantity,quality FROM enterprise_inventory
        WHERE enterprise_id=%s AND product_id=%s FOR UPDATE''',(seller,product)).fetchone()
    return row or (0,50)


def _purchase(conn, seller, buyer, product, quantity, day, price, flags, request_id,
              contract_id=None, lane='spot'):
    """Atomic stock/ledger/shipment with exact-once request receipt.

    Caller owns a transaction. Seller lock precedes inventory lock across all paths.
    """
    enterprise.integer(quantity,1)
    if not isinstance(request_id,str) or not 1<=len(request_id)<=100:
        raise ValueError('invalid_request_id')
    prior=conn.execute('''SELECT buyer_enterprise_id,seller_enterprise_id,product_id,
        quantity,unit_price,day_index FROM sales_purchase_receipts WHERE request_id=%s''',
        (request_id,)).fetchone()
    if prior:
        if prior!=(buyer,seller,product,quantity,price,day):
            raise ValueError('request_id_conflict')
        return quantity
    if seller==buyer:
        raise ValueError('self_trade')
    owners = conn.execute('''SELECT id,owner_id,city_id,x,y,storage_capacity FROM enterprises
        WHERE id IN (%s,%s) AND sold_at IS NULL ORDER BY id FOR UPDATE''',(seller,buyer)).fetchall()
    if len(owners)!=2:
        raise ValueError('unknown_enterprise')
    lookup={r[0]:r for r in owners}
    src,dst=lookup[seller],lookup[buyer]
    stock,quality=_inventory(conn,seller,product)
    if stock<quantity:
        raise ValueError('insufficient_stock')
    target_city=supply._city(dst[2],dst[3],dst[4])
    source_city=supply._city(src[2],src[3],src[4])
    days,freight=supply._travel(source_city,target_city,quantity,
                               flags['supply_transport_rub_per_km_unit_draft'])
    liters,fuel=supply.fuel_quote(source_city,target_city,quantity,flags)
    if supply._free(conn,buyer,dst[5])<quantity:
        raise ValueError('warehouse_full')
    subtotal=enterprise.integer(quantity*price)
    total=enterprise.integer(subtotal+freight+fuel)
    wallet=supply._wallet(conn,dst[1])
    if not wallet or wallet[1]<total:
        raise ValueError('insufficient_balance')
    if liters and not flags.get('logistics_fuel_autobuy',True):
        if enterprise.stock(conn,buyer).get('fuel',{}).get('quantity',0)<liters:
            raise ValueError('insufficient_fuel')
    from server.ledger.api import account,transfer
    own = src[1]==dst[1]
    if own and price:
        raise ValueError('self_trade_price')
    seller_wallet=supply._wallet(conn,src[1])
    if not seller_wallet:
        raise ValueError('unknown_wallet')
    enterprise.adjust(conn,seller,product,-quantity)
    if liters and not flags.get('logistics_fuel_autobuy',True):
        enterprise.adjust(conn,buyer,'fuel',-liters)
    transfer_id=None
    if subtotal:
        transfer_id=transfer(conn,'sales:'+request_id,wallet[0],seller_wallet[0],subtotal)
    if freight:
        transfer(conn,'sales:'+request_id+':freight',wallet[0],account(conn,'system:market'),freight)
    if fuel:
        transfer(conn,'sales:'+request_id+':fuel',wallet[0],account(conn,'system:market'),fuel)
    shipment_id='sales:'+request_id
    supply._ship(conn,shipment_id,buyer,seller,'enterprise',product,quantity,quality,
                 price,freight,day,day+days,transfer_id)
    conn.execute('''INSERT INTO sales_purchase_receipts
        (request_id,buyer_enterprise_id,seller_enterprise_id,product_id,quantity,
         unit_price,day_index,shipment_request_id,contract_id)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
        (request_id,buyer,seller,product,quantity,price,day,shipment_id,contract_id))
    return quantity


def _allocate(conn,seller,product,day,source,requests,stock,price,flags,
              contract_ids=None):
    result=allocate_fair(stock,requests)
    shipped_total=0
    for buyer_key,requested in sorted(requests.items()):
        buyer=int(buyer_key)
        planned=result[str(buyer_key)]
        shipped=0
        receipt=None
        if planned:
            receipt=f's{day}:{seller}:{product}:{buyer}:{source}'
            # Long SKUs can exceed the ledger id limit. Hash only the deterministic id.
            if len(receipt)>98:
                import hashlib
                receipt='s'+hashlib.sha256(receipt.encode()).hexdigest()
            try:
                with conn.transaction():
                    shipped=_purchase(conn,seller,buyer,product,planned,day,
                                      price,flags,receipt,
                                      (contract_ids or {}).get(buyer),source)
            except ValueError as exc:
                if str(exc) not in ('insufficient_balance','insufficient_stock','warehouse_full','insufficient_fuel'):
                    raise
                receipt=None
        conn.execute('''INSERT INTO sales_daily_allocations
            (seller_enterprise_id,buyer_enterprise_id,product_id,day_index,source,
             ordered,shipped,unfilled,receipt) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(seller_enterprise_id,buyer_enterprise_id,product_id,day_index,source)
            DO NOTHING''',(seller,buyer,product,day,source,requested,shipped,
                          requested-shipped,receipt if shipped else None))
        shipped_total+=shipped
        if shipped:
            conn.execute('''UPDATE supply_daily_needs SET linked=linked+%s,
                unfilled=GREATEST(0,unfilled-%s) WHERE enterprise_id=%s AND product_id=%s
                AND day_index=%s''',(shipped,shipped,buyer,product,day))
    return shipped_total


def clear_day(conn,day,flags):
    """Pre-link layer at order 15: complete exact daily requests, then legacy falls back.

    Phase stores a receipt even when empty. A day transaction rollback restores
    both inventory and ledger. Later supply phases exclude already-filled need.
    """
    enterprise.integer(day)
    if conn.execute('''SELECT 1 FROM sales_day_receipts WHERE day_index=%s''',
                    (day,)).fetchone():
        return
    supply._arrivals(conn,day)
    candidates=[]
    for eid,owner,recipe_id,city,stage,running,capacity in supply._enterprises(conn):
        if stage!=4 or not running:
            continue
        recipe=supply._recipe(recipe_id)
        if not recipe:
            continue
        for product in sorted(recipe['outputs']):
            policy=current_policy(conn,eid,product,day)
            if not policy:
                continue
            conn.execute('SELECT id FROM enterprises WHERE id=%s FOR UPDATE',(eid,))
            stock,quality=_inventory(conn,eid,product)
            own,contracted,spot=offer_quantities(stock,policy['mode'],policy['reserve_bp'],
                                                  reserve_for_contracts(conn,eid,product,day))
            conn.execute('''INSERT INTO sales_daily_offers
                (seller_enterprise_id,product_id,day_index,city_id,frozen_stock,
                 own_quota,contract_quota,spot_quota,mode,price,quality)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING''',
                (eid,product,day,city,stock,own,contracted,spot,
                 policy['mode'],policy['price'],quality))
            candidates.append((eid,owner,product,city,quality,policy,own,contracted,spot))
    # Freeze purchase requirements once. Legacy links_day must reuse these rows.
    buyers={r[0]:r for r in supply._enterprises(conn)}
    for row in buyers.values():
        for product,need in sorted(supply._need(conn,row).items()):
            conn.execute('''INSERT INTO supply_daily_needs
                (enterprise_id,product_id,day_index,requested,unfilled)
                VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
                (row[0],product,day,need,need))
    for seller,owner,product,city,quality,policy,own_limit,contract_limit,spot_limit in candidates:
        if own_limit:
            own_req={str(bid):need for bid,p,need in conn.execute('''SELECT enterprise_id,product_id,unfilled
                FROM supply_daily_needs WHERE product_id=%s AND day_index=%s AND unfilled>0''',
                (product,day)).fetchall() if bid!=seller and buyers[bid][1]==owner}
            _allocate(conn,seller,product,day,'own',own_req,own_limit,0,flags)
        contract_rows=conn.execute('''SELECT id,buyer_enterprise_id,reserved_remaining,price
            FROM sales_contract_reservations WHERE seller_enterprise_id=%s AND product_id=%s
            AND status='active' AND start_day<=%s AND end_day>=%s ORDER BY id FOR UPDATE''',
            (seller,product,day,day)).fetchall()
        used_contract=0
        for cid,bid,reserved,contract_price in contract_rows:
            need=conn.execute('''SELECT unfilled FROM supply_daily_needs
                WHERE enterprise_id=%s AND product_id=%s AND day_index=%s''',
                (bid,product,day)).fetchone()
            qty=min(reserved,need[0] if need else 0,contract_limit-used_contract)
            if qty<=0:
                continue
            shipped=_allocate(conn,seller,product,day,'contract',{str(bid):qty},qty,
                              contract_price,flags,{bid:cid})
            conn.execute('''UPDATE sales_contract_reservations SET reserved_remaining=reserved_remaining-%s,
                delivered=delivered+%s,status=CASE WHEN reserved_remaining=%s
                THEN 'fulfilled' ELSE status END WHERE id=%s''',
                (shipped,shipped,shipped,cid))
            used_contract+=shipped
        if spot_limit and policy['mode']!='private':
            requests={}
            owner_map={}
            for bid,bowner,_,buyer_city,_,_,_ in buyers.values():
                if bid==seller or bowner==owner or not seller_allowed(conn,seller,bowner,product,day):
                    continue
                need=conn.execute('''SELECT unfilled FROM supply_daily_needs
                    WHERE enterprise_id=%s AND product_id=%s AND day_index=%s''',
                    (bid,product,day)).fetchone()
                if not need or not need[0]:
                    continue
                score=quote_score(conn,seller,bid,product,policy['price'],quality,day,flags)
                if score is None:
                    continue
                requests[str(bid)]=need[0]
                owner_map[str(bid)]=bowner
            capped=cap_requests_by_owner(spot_limit,requests,owner_map,
                                         flags['sales_market_share_cap_bp'])
            _allocate(conn,seller,product,day,'spot',capped,spot_limit,
                      policy['price'],flags)
        alloc=conn.execute('''SELECT COALESCE(sum(ordered),0),COALESCE(sum(shipped),0),
            COALESCE(sum(unfilled),0)
            FROM sales_daily_allocations WHERE seller_enterprise_id=%s
            AND product_id=%s AND day_index=%s''',
            (seller,product,day)).fetchone()
        revenue = conn.execute('''SELECT COALESCE(sum(quantity*unit_price),0)
            FROM sales_purchase_receipts WHERE seller_enterprise_id=%s
            AND product_id=%s AND day_index=%s''',
            (seller,product,day)).fetchone()[0]
        conn.execute('''INSERT INTO sales_metrics_daily
            (seller_enterprise_id,product_id,day_index,offered,shipped,unfilled,revenue)
            VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
            (seller,product,day,own_limit+contract_limit+spot_limit,alloc[1],alloc[2],
             enterprise.integer(revenue)))
        conn.execute('''INSERT INTO sales_reliability_30d
            (enterprise_id,product_id,day_index,ordered,fulfilled)
            VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
            (seller,product,day,alloc[0],alloc[1]))

    conn.execute('INSERT INTO sales_day_receipts(day_index) VALUES(%s)', (day,))
