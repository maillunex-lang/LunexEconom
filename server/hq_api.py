"""One bounded, read-only dashboard snapshot, shared across SQLite/Postgres."""
import json
import time
import threading

import alerts
import bank
import clock
import economy
import goods_catalog
import holding
import production
import regions

MAX_BYTES = 65536
TTL = 4
_cache = {}
_cache_lock = threading.Lock()


def _q(sql, ph):
    return sql.replace('%s', ph)


def _read(db, ph, owner, now):
    clk = clock.state(db, ph, now)
    month = clk['month_index']
    name_row = db.execute(_q('SELECT name,founded_month FROM holdings WHERE owner=%s', ph), (owner,)).fetchone()
    finance = holding.overview(db, ph, owner)
    latest = db.execute(_q('SELECT revenue,input_cost,upkeep,profit FROM company_reports WHERE owner=%s ORDER BY month_index DESC LIMIT 1', ph), (owner,)).fetchone()
    income, inputs, upkeep, profit = [int(x) for x in latest] if latest else (0, 0, 0, 0)
    cash = finance['cash']
    try:
        # Use the existing authoritative estimator, not a fabricated number.
        quotes = production.quote(db, ph, clk)
        labor_forecast = production.labor_view(db, ph, clk)
        predicted = int(production.forecast(db, ph, owner, quotes, labor_forecast)['profit_after_tax'])
    except (KeyError, ValueError, TypeError, ZeroDivisionError):
        predicted = None
    rows = db.execute(_q('''SELECT b.id,b.kind,b.x,b.y,o.start_month,cs.stage,cs.next_at,
                 COALESCE(d.width,0),COALESCE(d.height,0),COALESCE(es.name,''),COALESCE(es.price_rule,'market')
                 FROM buildings b LEFT JOIN building_ops o ON o.object_id=b.id
                 LEFT JOIN construction_stages cs ON cs.object_id=b.id
                 LEFT JOIN building_dimensions d ON d.object_id=b.id
                 LEFT JOIN enterprise_settings es ON es.object_id=b.id
                 WHERE b.owner=%s ORDER BY b.created DESC,b.id LIMIT 180''', ph), (owner,)).fetchall()
    stock = {good: int(qty) for good, qty in db.execute(_q('SELECT product,qty FROM inventory WHERE owner=%s', ph), (owner,)).fetchall()}
    labor = db.execute('SELECT staffing_permille FROM population ORDER BY month_index DESC LIMIT 1').fetchone()
    staffing = (int(labor[0]) / 1000 if labor else 1.0)
    enterprises, projects = [], []
    active = [row for row in rows if row[5] in (None,'complete')]
    # Existing company_reports are company-wide, NOT per-building records.
    # Allocate by each building's reference cost only as a display estimate.
    weights = [max(1,economy.BUILD_COST.get(row[1],1)) for row in active]
    weight_total = sum(weights)
    projections = {}
    allocated = 0
    for idx, row in enumerate(active):
        part = (profit * weights[idx] // weight_total) if idx < len(active)-1 else profit - allocated
        projections[row[0]] = part
        allocated += part
    for bid, kind, x, y, start, stage, next_at, width, height, name, rule in rows:
        import building_dimensions
        spec = production._spec(kind) or {}
        w,h = (width,height) if width and height else building_dimensions.LEGACY_FOOTPRINTS.get(kind,(1,1))
        working = (stage is None or stage == 'complete') and start is not None
        status = 'working' if working else 'building' if stage in ('foundation','frame') else 'idle'
        if working and projections.get(bid,0) < 0: status = 'loss'
        obj = {'id':bid,'kind':kind,'name':name or kind,'city':regions.region_of(x,y),
               'x':int(x),'y':int(y),'w':int(w),'h':int(h),'status':status,
               'construction_stage':stage or 'complete','profit_month':projections.get(bid,0),
               'jobs':int(spec.get('jobs',0)),'staffing':staffing if working else 0.0,
               'stock':{},'alerts':[],'recipe':{'inputs':dict(spec.get('inputs',{})),
               'output':int(spec.get('output',0)),'product':spec.get('product')}}
        # Company inventory has no per-building location. Expose it only on the
        # company-level aggregated view, not a fabricated building allocation.
        enterprises.append(obj)
        if stage and stage != 'complete':
            total = max(1, __import__('construction_stages').step_seconds())
            projects.append({'id':bid,'kind':kind,'city':obj['city'],'stage':stage,
                             'percent':0 if stage == 'foundation' else 50,
                             'ready_in_seconds':max(0,int(next_at)-now)+(total if stage=='foundation' else 0)})
    st = production.company_view(db, ph, owner)
    loan = bank.view(db, ph, owner, in_default=st['missed']>0 or st['arrears']>0)
    loan_items = ([{'id':owner,'balance':int(loan['balance']),'rate':float(loan['interest_rate']),
                    'next_payment':int(loan['monthly_interest']),'due_month':month+1}] if loan['balance'] else [])
    tc_rows = db.execute(_q("SELECT id,end_month FROM trade_contracts WHERE status='active' AND (supplier=%s OR buyer=%s) ORDER BY end_month LIMIT 30",ph), (owner,owner)).fetchall()
    contracts = [{'id':bid,'end_month':int(end)} for bid,end in tc_rows]
    open_count = int(db.execute(_q("SELECT COUNT(*) FROM trade_offers WHERE supplier=%s AND status='open'",ph), (owner,)).fetchone()[0])
    order_count = int(db.execute(_q("SELECT COUNT(*) FROM soc_orders WHERE owner=%s AND status='open'",ph), (owner,)).fetchone()[0])
    quotes = db.execute('SELECT product,price,month_index FROM market_prices ORDER BY month_index DESC,product LIMIT 120').fetchall()
    seen, market = set(), []
    for good, price, m in quotes:
        if good in seen: continue
        seen.add(good)
        previous = db.execute(_q('SELECT price FROM market_prices WHERE product=%s AND month_index<%s ORDER BY month_index DESC LIMIT 1',ph), (good,m)).fetchone()
        market.append({'good':good,'price':int(price),'change_permille':round(1000*(int(price)-int(previous[0]))/int(previous[0])) if previous and previous[0] else 0})
        if len(market) >= 20: break
    city_id = enterprises[0]['city'] if enterprises else regions.HOME
    pop_row = db.execute('SELECT next_population FROM population ORDER BY month_index DESC LIMIT 1').fetchone()
    rating = db.execute('SELECT total_permille FROM mayor_rating ORDER BY month_index DESC LIMIT 1').fetchone()
    mayor = db.execute('SELECT mayor FROM city_state WHERE id=1').fetchone()
    from geo import get_city
    geo_city = get_city(city_id) or get_city(regions.HOME)
    rank = None
    # The current leaderboard rank is computed separately; rating here is the city's approval.
    if rating: rank = int(rating[0])//10
    capacity = sum(int((production._spec(obj['kind']) or {}).get('capacity',0)) for obj in enterprises)
    warnings = alerts.collect(owner, enterprises, st, loan['balance'], contracts, month, stock, capacity)
    enterprise_public = [{k:v for k,v in item.items() if k not in ('recipe','recently_completed')} for item in enterprises]
    result = {
        'version':1,'server_time':now,
        'clock':{k:clk[k] for k in ('month_index','year','month','day','seconds_to_next_month')},
        'company':{'owner':owner,'name':name_row[0] if name_row else owner,'rating':rank,
                   'founded_month':int(name_row[1]) if name_row else 0},
        'money':{'cash':cash,'income_month':income,'expenses_month':inputs+upkeep,
                 'profit_month':profit,'forecast_next_month':predicted},
        'enterprises':enterprise_public,'projects':projects,
        'finance':{'loans':loan_items,'arrears':st['arrears'],'taxes_due':st['tax_owed'],
                   'next_payments':[{'month':month+1,'kind':'loan','amount':int(loan['monthly_interest'])}] if loan_items else [],
                   'credit_available':int(loan['available'])},
        'city':{'id':city_id,'name':geo_city['name'],'population':int(pop_row[0]) if pop_row else 0,
                'rating':rank,'budget':int(economy.balance(db,ph,economy.CITY) or 0),
                'mayor':mayor[0] if mayor else ''},
        'market':market,'contracts':{'active':len(contracts),'open':open_count},
        'exchange':{'open_orders':order_count},'alerts':warnings,'dev':False,
        'inventory':stock,'consolidated':{'assets':finance['assets'],'debts':finance['debts'],
                                         'subsidiaries':finance['subsidiaries']},
        'profit_allocation':'estimated_by_reference_cost',
    }
    return result


def snapshot(db, ph, owner, now=None, cache=False, scope=None):
    if not owner: return 401, {'error':'unauthorized'}
    now = int(time.time()) if now is None else int(now)
    if cache:
        with _cache_lock:
            row = _cache.get((owner,ph,scope))
            if row and row[0] >= time.monotonic(): return 200, row[1]
    result = _read(db,ph,owner,now)
    raw = json.dumps(result,ensure_ascii=False,separators=(',',':')).encode('utf-8')
    if len(raw)>MAX_BYTES:
        result['enterprises'] = result['enterprises'][:60]
        result['projects'] = result['projects'][:30]
        result['alerts'] = result['alerts'][:20]
        raw = json.dumps(result,ensure_ascii=False,separators=(',',':')).encode('utf-8')
    if len(raw)>MAX_BYTES:
        return 413, {'error':'hq_too_large'}
    if cache:
        with _cache_lock:
            if len(_cache)>1000: _cache.clear()
            _cache[(owner,ph,scope)] = (time.monotonic()+TTL,result)
    return 200,result


def enterprise(db,ph,owner,bid):
    if not isinstance(bid,str) or not bid or len(bid)>100: return 400,{'error':'invalid_id'}
    row=db.execute(_q("SELECT b.id,b.owner,b.kind,b.x,b.y,COALESCE(es.name,''),es.price,COALESCE(es.price_rule,'market'),COALESCE(es.min_stock,'{}'),COALESCE(es.buy_limit,0),COALESCE(es.managers,'{}') FROM buildings b LEFT JOIN enterprise_settings es ON es.object_id=b.id WHERE b.id=%s",ph),(bid,)).fetchone()
    if row is None: return 404,{'error':'not_found'}
    if row[1]!=owner: return 403,{'error':'not_owner'}
    spec=production._spec(row[2]) or {}
    history=db.execute(_q('SELECT month_index,revenue,input_cost,upkeep,profit FROM company_reports WHERE owner=%s ORDER BY month_index DESC LIMIT 12',ph),(owner,)).fetchall()
    stock=dict(db.execute(_q('SELECT product,qty FROM inventory WHERE owner=%s',ph),(owner,)).fetchall())
    return 200,{'id':row[0],'owner':row[1],'kind':row[2],'x':row[3],'y':row[4],
                'name':row[5] or row[2],'price':row[6],'price_rule':row[7],
                'min_stock':json.loads(row[8]),'buy_limit':row[9],
                'auto_managers':json.loads(row[10]),'recipe':spec,'stock_company_total':stock,
                'history_company_total':[{'month_index':m,'revenue':r,'input_cost':i,'upkeep':u,'profit':p} for m,r,i,u,p in history],
                'accounting_scope':'company'}