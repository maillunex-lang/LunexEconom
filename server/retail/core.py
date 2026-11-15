"""Server-authoritative retail demand, stock and VAT (draft).

All quantities, money, competition and ratings use integer arithmetic.
Daily processing is transactionally atomic under the game's clock worker.
"""
from collections import defaultdict
from server.enterprises.core import catalog, adjust
from server.ledger.api import account, transfer
from server.world.core import nearest_city

MAX = 2**63 - 1
DRAFT_VAT_BP = 1000


def integer(value, low=0, high=MAX):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('invalid_integer')
    return value


def building_details(building_id):
    building = catalog().index['buildings'].get(building_id)
    if not building or building.get('role') != 'retail' or building.get('category') != 'retail':
        raise ValueError('not_retail_store')
    return building


def validate_cells(building, entries):
    if type(entries) is not list or len(entries) > building['retail_cells']:
        raise ValueError('invalid_cells')
    chosen = {}
    for cell in entries:
        if type(cell) is not dict or set(cell) != {'cell_index','product_id','price','min_stock','supply_link_slot'}:
            raise ValueError('invalid_cell_fields')
        idx = integer(cell['cell_index'],0,building['retail_cells']-1)
        good = cell['product_id']
        if type(good) is not str or good not in building['allowed_goods']:
            raise ValueError('not_allowed_good')
        integer(cell['price'],1)
        integer(cell['min_stock'],0)
        slot = cell['supply_link_slot']
        if slot is not None:
            integer(slot,1,3)
        if idx in chosen:
            raise ValueError('duplicate_cell_index')
        chosen[idx] = dict(cell)
    return [chosen[i] for i in sorted(chosen)]


def replenishment_targets(conn, eid):
    """Public link for V2-05 supply; SKU targets respect shared warehouse stock."""
    rows = conn.execute('SELECT product_id,sum(min_stock) FROM retail_cells WHERE enterprise_id=%s GROUP BY product_id',(eid,)).fetchall()
    return {good:int(qty) for good,qty in rows}


def rating(product, price, quality, brand=50):
    integer(price,1)
    integer(quality,0,100)
    integer(brand,0,100)
    w = product.get('rating_weights',{'brand':30,'quality':40,'price':30})
    if set(w) != {'brand','quality','price'} or any(type(v) is not int or v < 0 for v in w.values()) or sum(w.values()) != 100:
        raise ValueError('invalid_rating_weights')
    ref = integer(product['reference_price'],1)
    p = min(100,100*ref*1000//(price*1000))
    return (w['brand']*brand+w['quality']*quality+w['price']*p)//100


def attractiveness(rating_value, traffic_bonus=0, store_appeal=1000):
    integer(rating_value,0,100)
    integer(traffic_bonus,0,100000)
    integer(store_appeal,0,100000)
    return rating_value*(1000+traffic_bonus)//1000*store_appeal//1000


def price_factor(price, ref, elasticity):
    integer(price,1)
    integer(ref,1)
    integer(elasticity,0,1000)
    delta_bp = (price-ref)*10000//ref
    return max(300,min(1500,1000-elasticity*delta_bp//100))


def city_demand(population, product, weighted_price, weighted_rating):
    integer(population)
    per = integer(product.get('base_demand_per_capita',0))
    base = integer(population*per)
    if not base:
        return 0
    factor = price_factor(weighted_price, product['reference_price'], product.get('elasticity',1))
    rating_factor = 700+300*integer(weighted_rating,0,100)//100
    # Single district and single layer: price and rating modifiers are draft.
    return integer((base*factor//1000)*rating_factor//1000)


def split_demand(demand, weighted_cells):
    """Largest remainder with stable (enterprise_id,cell_index) ordering."""
    integer(demand)
    if not weighted_cells:
        return {}
    weighted_cells = sorted(weighted_cells)
    weights = {key: max(0,appeal)**2 for key,appeal in weighted_cells}
    total=sum(weights.values())
    if not total:
        return {key:0 for key in weights}
    result={key:demand*weight//total for key,weight in weights.items()}
    remainder=demand-sum(result.values())
    ordered=sorted(weights,key=lambda key:(-(demand*weights[key]%total),key))
    for key in ordered[:remainder]:
        result[key]+=1
    return result


def vat_parts(revenue, vat_bp=DRAFT_VAT_BP):
    integer(revenue)
    integer(vat_bp,0,10000)
    base = revenue*10000//(10000+vat_bp)
    return base,revenue-base


def _active_cells(conn):
    rows=conn.execute("""
      SELECT e.id,e.owner_id,e.city_id,e.x,e.y,c.cell_index,c.product_id,
             c.price,c.min_stock,c.supply_link_slot,
             COALESCE(i.quantity,0),COALESCE(i.quality,50)
      FROM retail_cells c JOIN enterprises e ON e.id=c.enterprise_id
      LEFT JOIN enterprise_inventory i ON i.enterprise_id=e.id AND i.product_id=c.product_id
      WHERE e.stage=4 AND e.running=true AND e.sold_at IS NULL
      AND NOT EXISTS(SELECT 1 FROM enterprise_arrears a
                     WHERE a.enterprise_id=e.id AND a.paid_at IS NULL)
      ORDER BY e.id,c.cell_index
    """).fetchall()
    return rows


def _grouped(rows):
    groups=defaultdict(list)
    products=catalog().index['products']
    for eid,owner,city,x,y,idx,good,price,min_stock,slot,stock,quality in rows:
        if not products[good].get('consumer',False):
            continue
        city_id=city or nearest_city(x,y)['id']
        r=rating(products[good],price,quality)
        groups[(city_id,good)].append(dict(
            eid=eid,owner=owner,city=city_id,idx=idx,good=good,
            price=price,minimum=min_stock,stock=stock,quality=quality,
            rating=r,appeal=attractiveness(r)))
    return groups


def evaluate_group(population, product, cells):
    """Compute one city's demand once and award stock-constrained shelf shares."""
    weighted=sum(c['price']*c['appeal']**2 for c in cells)
    total=sum(c['appeal']**2 for c in cells)
    avg_price=weighted//total if total else product['reference_price']
    avg_rating=sum(c['rating']*c['appeal']**2 for c in cells)//total if total else 0
    demand=city_demand(population, product, avg_price, avg_rating)
    shares=split_demand(demand,[((c['eid'],c['idx']),c['appeal']) for c in cells])
    # One common SKU warehouse; multiple cells never sell the same stock twice.
    available={}
    sold=[]
    for cell in sorted(cells,key=lambda c:(c['eid'],c['idx'])):
        key=(cell['eid'],cell['good'])
        available.setdefault(key,cell['stock'])
        quantity=min(shares[cell['eid'],cell['idx']],available[key])
        available[key]-=quantity
        sold.append((cell,quantity))
    return sold


def advance_day(conn, day, vat_bp=DRAFT_VAT_BP):
    integer(day)
    integer(vat_bp,0,10000)
    if conn.execute('SELECT 1 FROM retail_receipts WHERE day_index=%s',(day,)).fetchone():
        return
    # The tick transaction serializes the world; lock inventory rows to protect
    # against concurrent API stock adjustments on other connections.
    # Serialize retail days independently of the clock's advisory lock.
    # This also protects replayed manual day calls.
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('retail:day:'||%s::text,0))",(day,))
    if conn.execute('SELECT 1 FROM retail_receipts WHERE day_index=%s',(day,)).fetchone():
        return
    # Lock warehouse rows first, then read the stock snapshot, so another
    # concurrent inventory update cannot invalidate quantities used for sales.
    conn.execute('SELECT enterprise_id,product_id FROM enterprise_inventory '
                 'WHERE enterprise_id IN (SELECT enterprise_id FROM retail_cells) '
                 'ORDER BY enterprise_id,product_id FOR UPDATE')
    rows=_active_cells(conn)
    populations=dict(conn.execute('SELECT id,population FROM world_cities').fetchall())
    products=catalog().index['products']
    for (city,good),cells in sorted(_grouped(rows).items()):
        for cell,quantity in evaluate_group(populations[city],products[good],cells):
            eid=cell['eid']
            revenue=integer(quantity*cell['price'])
            if quantity:
                adjust(conn,eid,good,-quantity)
                wallet=conn.execute("""SELECT l.id FROM ledger_accounts l
                   JOIN accounts a ON l.account_key='player:'||lower(a.username)
                   WHERE a.id=%s""",(cell['owner'],)).fetchone()
                if wallet is None:
                    raise ValueError('missing_retail_wallet')
                transfer(conn,f"retail:{eid}:{good}:{day}:cell{cell['idx']}",
                         account(conn,'system:market'),wallet[0],revenue)
            conn.execute("""INSERT INTO retail_sales_daily
                 (enterprise_id,cell_index,product_id,day_index,city_id,district_id,
                  income_layer,quantity,price,revenue,rating,vat_bp)
                 VALUES(%s,%s,%s,%s,%s,NULL,0,%s,%s,%s,%s,%s)""",
                 (eid,cell['idx'],good,day,city,quantity,cell['price'],revenue,
                  cell['rating'],vat_bp))
    # Alert on all configured goods, including nonconsumer shelves and empty shops.
    rows=conn.execute("""SELECT c.enterprise_id,c.product_id,
         sum(c.min_stock),COALESCE(i.quantity,0)
         FROM retail_cells c JOIN enterprises e ON e.id=c.enterprise_id
         LEFT JOIN enterprise_inventory i ON i.enterprise_id=c.enterprise_id AND i.product_id=c.product_id
         WHERE e.stage=4 AND e.running AND e.sold_at IS NULL
         GROUP BY c.enterprise_id,c.product_id,i.quantity""").fetchall()
    for eid,good,target,onhand in rows:
        if onhand<int(target):
            kind='out_of_stock' if onhand==0 else 'low_stock'
            conn.execute("""INSERT INTO retail_alerts(enterprise_id,product_id,day_index,alert_type)
                            VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                         (eid,good,day,kind))
    conn.execute('INSERT INTO retail_receipts(day_index) VALUES(%s)',(day,))


def settle_prior_vat(conn, before_month):
    """Try unpaid older monthly invoices oldest-first without an overdraft."""
    rows=conn.execute("""SELECT enterprise_id,month_index,vat
        FROM retail_month_receipts
        WHERE paid=false AND month_index<%s ORDER BY month_index,enterprise_id""",
        (before_month,)).fetchall()
    for eid,old_month,vat in rows:
        with conn.transaction():
            receipt=conn.execute("""SELECT paid,vat FROM retail_month_receipts
                 WHERE enterprise_id=%s AND month_index=%s FOR UPDATE""",
                 (eid,old_month)).fetchone()
            if not receipt or receipt[0]:
                continue
            owner=conn.execute('SELECT owner_id FROM enterprises WHERE id=%s',(eid,)).fetchone()[0]
            wallet=conn.execute("""SELECT l.id,l.balance FROM ledger_accounts l
                 JOIN accounts a ON l.account_key='player:'||lower(a.username)
                 WHERE a.id=%s FOR UPDATE""",(owner,)).fetchone()
            if wallet and wallet[1]>=receipt[1]:
                transfer(conn,f'retail:vat:{eid}:{old_month}',wallet[0],
                         account(conn,'system:treasury'),receipt[1])
                conn.execute("""UPDATE retail_month_receipts SET paid=true
                    WHERE enterprise_id=%s AND month_index=%s""",
                    (eid,old_month))


def close_month(conn, month, vat_bp=DRAFT_VAT_BP):
    integer(month)
    integer(vat_bp, 0, 10000)
    settle_prior_vat(conn,month)
    first = max(0, (month-1)*30+1)
    last = month*30
    rows = conn.execute("""SELECT enterprise_id,COALESCE(sum(revenue),0)
       FROM retail_sales_daily WHERE day_index BETWEEN %s AND %s
       GROUP BY enterprise_id ORDER BY enterprise_id""",(first,last)).fetchall()
    for eid, revenue in rows:
        revenue=integer(int(revenue))
        # Use the actual VAT rates recorded at checkout, rather than silently
        # changing old receipts when a future approved rate changes.
        breakdown=conn.execute("""SELECT vat_bp,sum(revenue) FROM retail_sales_daily
           WHERE enterprise_id=%s AND day_index BETWEEN %s AND %s
           GROUP BY vat_bp""",(eid,first,last)).fetchall()
        vat=sum(vat_parts(integer(int(gross)),rate)[1] for rate,gross in breakdown)
        with conn.transaction():
            previous=conn.execute("""SELECT revenue,vat,paid FROM retail_month_receipts
                WHERE enterprise_id=%s AND month_index=%s FOR UPDATE""",
                (eid,month)).fetchone()
            if previous and previous[2]:
                continue
            if previous and previous[:2]!=(revenue,vat):
                raise ValueError('retail_month_amount_changed')
            paid=(vat==0)
            if vat:
                owner=conn.execute('SELECT owner_id FROM enterprises WHERE id=%s',(eid,)).fetchone()[0]
                wallet=conn.execute("""SELECT l.id,l.balance FROM ledger_accounts l
                  JOIN accounts a ON l.account_key='player:'||lower(a.username)
                  WHERE a.id=%s FOR UPDATE""",(owner,)).fetchone()
                if wallet and wallet[1]>=vat:
                    transfer(conn,f'retail:vat:{eid}:{month}',wallet[0],
                             account(conn,'system:treasury'),vat)
                    paid=True
            conn.execute("""INSERT INTO retail_month_receipts
                  (enterprise_id,month_index,revenue,vat,paid)
                  VALUES(%s,%s,%s,%s,%s)
                  ON CONFLICT(enterprise_id,month_index) DO UPDATE SET
                  paid=EXCLUDED.paid WHERE retail_month_receipts.paid=false""",
                  (eid,month,revenue,vat,paid))
            conn.execute("""INSERT INTO enterprise_month_reports
                  (enterprise_id,month_index,revenue,expenses,average_load_bp,inventory,wear)
                  SELECT id,%s,%s,0,0,'{}'::jsonb,wear FROM enterprises WHERE id=%s
                  ON CONFLICT(enterprise_id,month_index) DO UPDATE
                  SET revenue=EXCLUDED.revenue""",(month,revenue,eid))
