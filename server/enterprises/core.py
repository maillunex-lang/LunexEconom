"""Server-authoritative enterprise construction and production, integer-only."""
from __future__ import annotations

from server.catalog import Catalog
from server.ledger.api import account, transfer
from server.world import core as world

BP = 10000
MAX = 2**63 - 1
STAGES = ('foundation','frame','finishing','commissioning','operational')
# balance: draft (D-10, D-53). Four payments sum to exactly build_cost.
COST_SHARES_PERMILLE = (300, 400, 200, 100)
TIME_SHARES_PERMILLE = (250, 350, 300, 100)

def stage_costs(total):
    """Floor each of the first three shares; final payment takes remainder."""
    integer(total, 1)
    result = [total * share // 1000 for share in COST_SHARES_PERMILLE[:3]]
    result.append(total - sum(result))
    return tuple(result)

def stage_day_lengths(days):
    """Cumulative floor boundaries, as tools.sim.formulas.split_by_bp."""
    integer(days, 1)
    previous = 0
    result = []
    cumulative = 0
    for share in TIME_SHARES_PERMILLE:
        cumulative += share
        end = days * cumulative // 1000
        result.append(end - previous)
        previous = end
    return tuple(result)

def payment_status(conn, eid, stage, cost):
    """Owner-only API projection; ledger rows are the source of payment truth."""
    entries = conn.execute(
        'SELECT stage,amount,legacy_prepaid FROM enterprise_stage_payments '
        'WHERE enterprise_id=%s ORDER BY stage', (eid,)
    ).fetchall()
    paid = [{'stage_index': i, 'stage': STAGES[i], 'amount': amount,
             'legacy_prepaid': legacy} for i,amount,legacy in entries]
    paid_index = {r[0] for r in entries}
    upcoming = next((i for i in range(4) if i not in paid_index), None)
    if stage == 4:
        upcoming = None
    waiting = conn.execute(
        'SELECT stage,amount,waiting_days,first_wait_day '
        'FROM enterprise_build_waits WHERE enterprise_id=%s', (eid,)
    ).fetchone()
    amounts = stage_costs(cost)
    return {'paid_stages': paid, 'paid_amount': sum(item['amount'] for item in paid),
            'next_payment': None if upcoming is None else
                {'stage_index': upcoming, 'stage': STAGES[upcoming],
                 'amount': amounts[upcoming]},
            'waiting_for_payment': waiting is not None,
            'waiting_days': waiting[2] if waiting else 0}

_CATALOG = None

def catalog():
    global _CATALOG
    if _CATALOG is None:
        _CATALOG = Catalog()
    return _CATALOG

def integer(value, low=0, high=MAX):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('invalid_integer')
    return value

def today(conn):
    return max(0, conn.execute("SELECT COALESCE(MAX(day_index),-1)+1 FROM game_ticks WHERE completed=true").fetchone()[0])

def cells_for(x,y,building):
    return {(a,b) for a in range(x,x+building['size']['width']) for b in range(y,y+building['size']['height'])}

def placement(conn, actor_id, px, py, x, y, building):
    row=conn.execute('SELECT owner_kind,owner_ref FROM world_parcels WHERE px=%s AND py=%s FOR UPDATE',(px,py)).fetchone()
    if row != ('player',str(actor_id)):
        return 'parcel_not_owned',None,None
    cells=cells_for(x,y,building)
    if not all(px*6<=a<px*6+6 and py*6<=b<py*6+6 for a,b in cells):
        return 'outside_parcel',None,None
    ok,reason=world.placement_valid(conn,building['id'],x,y)
    if not ok:
        return reason,None,None
    states=world.city_states(conn)
    city=world.city_at(x,y,states)
    return None,cells,city['id'] if city else None

def place(conn, actor, request_id, building_id, px, py, x, y):
    building=catalog().index['buildings'].get(building_id)
    if building is None:
        return 404,{'error':'unknown_building'}
    conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('enterprise:order:'+request_id,))
    previous=conn.execute('SELECT id,owner_id,building_id,px,py,x,y FROM enterprises WHERE build_request_id=%s',(request_id,)).fetchone()
    if previous:
        if previous[1:] != (actor['id'],building_id,px,py,x,y):
            return 409,{'error':'request_id_conflict'}
        return 200,{'id':previous[0],'idempotent':True}
    reason,cells,city_id=placement(conn,actor['id'],px,py,x,y,building)
    if reason:
        return 409,{'error':reason}
    payer=account(conn,'player:'+actor['username'].lower(),'player',actor['id'])
    treasury=account(conn,'system:treasury')
    wallet_balance=conn.execute('SELECT balance FROM ledger_accounts WHERE id=%s',(payer,)).fetchone()[0]
    initial_payment = stage_costs(building['build_cost'])[0]
    if wallet_balance < initial_payment:
        return 409,{'error':'insufficient_funds'}
    try:
        transfer_id=transfer(conn,'enterprise:build:'+request_id,payer,treasury,initial_payment)
    except ValueError as exc:
        if str(exc)=='insufficient balance':
            return 409,{'error':'insufficient_funds'}
        raise
    recipes=[r for r in catalog().data['recipes'] if r['building']==building_id]
    recipe_id=recipes[0]['id'] if recipes else None
    eid=conn.execute("""INSERT INTO enterprises(owner_id,building_id,px,py,x,y,width,height,city_id,name,build_cost,build_days,upkeep_month,jobs,storage_capacity,started_day,recipe_id,build_request_id,build_transfer_id)
      VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
      (actor['id'],building_id,px,py,x,y,building['size']['width'],building['size']['height'],city_id,building['name'],building['build_cost'],building['build_days'],building['upkeep_month'],building['jobs'],building['storage_capacity'],today(conn),recipe_id,request_id,transfer_id)).fetchone()[0]
    # First installment and the enterprise are committed in the same transaction.
    # Stage 0 preserves the old order-level ledger idempotency key.
    conn.execute("""INSERT INTO enterprise_stage_payments
      (enterprise_id,stage,amount,request_id,transfer_id)
      VALUES(%s,0,%s,%s,%s)""",
      (eid,initial_payment,'enterprise:build:'+request_id,transfer_id))
    # World mark_occupied currently rejects free land; preserve world tables
    # and use the same sparse occupancy and chunk-event contract for both zones.
    if city_id:
        event=world.mark_occupied(conn,city_id,'enterprise:'+str(eid),sorted(cells))
    else:
        for cx,cy in sorted(cells):
            nearest=world.nearest_city(cx,cy)['id']
            conn.execute('INSERT INTO world_occupied_cells(x,y,city_id,building_ref) VALUES(%s,%s,%s,%s)',
                         (cx,cy,nearest,'enterprise:'+str(eid)))
        event=world._touch(conn,world._chunks_for_cells(cells),'enterprise_construction',None,
                           {'enterprise_id':eid,'stage_index':0,'stage':'foundation'})
    return 201,{'id':eid,'build_cost':building['build_cost'],
                'initial_payment':initial_payment,'transfer_id':transfer_id,
                'event_version':event,'idempotent':False,'balance':'draft'}

def stock(conn,eid):
    rows=conn.execute('SELECT product_id,quantity,quality FROM enterprise_inventory WHERE enterprise_id=%s ORDER BY product_id',(eid,)).fetchall()
    return {p:{'quantity':qty,'quality':quality} for p,qty,quality in rows}

def stock_total(conn,eid):
    return conn.execute('SELECT COALESCE(sum(quantity),0) FROM enterprise_inventory WHERE enterprise_id=%s',(eid,)).fetchone()[0]

def adjust(conn,eid,product,delta,quality=50):
    integer(quality,1,100)
    if product not in catalog().index['products']:
        raise ValueError('unknown_product')
    if type(delta) is not int or not -MAX<=delta<=MAX:
        raise ValueError('invalid_delta')
    conn.execute('INSERT INTO enterprise_inventory(enterprise_id,product_id,quantity,quality) VALUES(%s,%s,0,%s) ON CONFLICT DO NOTHING',(eid,product,quality))
    qty,prior=conn.execute('SELECT quantity,quality FROM enterprise_inventory WHERE enterprise_id=%s AND product_id=%s FOR UPDATE',(eid,product)).fetchone()
    result=integer(qty+delta)
    weighted=(qty*prior+delta*quality)//result if delta>0 and result>0 else (quality if delta>0 else prior)
    conn.execute('UPDATE enterprise_inventory SET quantity=%s,quality=%s WHERE enterprise_id=%s AND product_id=%s',(result,weighted,eid,product))

def load_bp(items,recipe,capacity,staff_bp):
    integer(staff_bp,0,BP)
    occupied=sum(v['quantity'] for v in items.values())
    free=max(0,capacity-occupied)
    ratio=staff_bp
    for product,volume in recipe['inputs'].items():
        ratio=min(ratio,items.get(product,{}).get('quantity',0)*BP//volume)
    total_output=sum(recipe['outputs'].values())
    if total_output:
        # Inputs consumed during this tick release space before outputs arrive.
        consumed=sum(recipe['inputs'].values())
        required_net=max(0,total_output-consumed)
        if required_net:
            ratio=min(ratio,free*BP//required_net)
    return max(0,min(BP,ratio))

def production(conn,eid,day,default_staffing_bp=10000):
    row=conn.execute('SELECT recipe_id,stage,running,staffing_bp,storage_capacity,last_production_day FROM enterprises WHERE id=%s AND sold_at IS NULL FOR UPDATE',(eid,)).fetchone()
    if row is None or row[5]>=day:
        return
    recipe_id,stage,running,staff,capacity,_=row
    has_arrears=conn.execute('SELECT 1 FROM enterprise_arrears WHERE enterprise_id=%s AND paid_at IS NULL LIMIT 1',(eid,)).fetchone()
    if stage!=4 or not running or recipe_id is None or has_arrears:
        conn.execute('UPDATE enterprises SET load_bp=0,last_production_day=%s WHERE id=%s',(day,eid))
        return
    recipe=catalog().index['recipes'][recipe_id]
    items=stock(conn,eid)
    load=load_bp(items,recipe,capacity,min(staff,default_staffing_bp))
    # Incomplete integer quantities are conserved across days via carry in bp.
    for product,volume in recipe['inputs'].items():
        old=conn.execute('SELECT input_carry FROM enterprise_inventory WHERE enterprise_id=%s AND product_id=%s',(eid,product)).fetchone()
        carry=old[0] if old else 0
        used,new_carry=divmod(volume*load+carry,BP)
        if used:adjust(conn,eid,product,-used)
        conn.execute('UPDATE enterprise_inventory SET input_carry=%s WHERE enterprise_id=%s AND product_id=%s',(new_carry,eid,product))
    for product,volume in recipe['outputs'].items():
        conn.execute('INSERT INTO enterprise_inventory(enterprise_id,product_id,quantity,quality) VALUES(%s,%s,0,50) ON CONFLICT DO NOTHING',(eid,product))
        old=conn.execute('SELECT output_carry FROM enterprise_inventory WHERE enterprise_id=%s AND product_id=%s',(eid,product)).fetchone()[0]
        made,new_carry=divmod(volume*load+old,BP)
        if made:
            weights=[(items[p]['quality'],amount) for p,amount in recipe['inputs'].items()]
            quality=sum(q*amount for q,amount in weights)//sum(amount for _,amount in weights) if weights else 50
            adjust(conn,eid,product,made,quality)
        conn.execute('UPDATE enterprise_inventory SET output_carry=%s WHERE enterprise_id=%s AND product_id=%s',(new_carry,eid,product))
    if stock_total(conn,eid)>capacity:
        raise ValueError('warehouse_full')
    conn.execute('UPDATE enterprises SET load_bp=%s,last_production_day=%s WHERE id=%s',(load,day,eid))
    conn.execute('INSERT INTO enterprise_daily_load(enterprise_id,day_index,load_bp) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',(eid,day,load))

def _record_build_wait(conn, eid, stage, amount, day):
    """A missed installment is not debt and never generates a debit journal."""
    conn.execute("""INSERT INTO enterprise_build_waits
      (enterprise_id,stage,amount,first_wait_day,last_wait_day,waiting_days)
      VALUES(%s,%s,%s,%s,%s,1)
      ON CONFLICT(enterprise_id) DO UPDATE SET
        stage=EXCLUDED.stage,amount=EXCLUDED.amount,
        waiting_days=enterprise_build_waits.waiting_days
          + CASE WHEN EXCLUDED.last_wait_day > enterprise_build_waits.last_wait_day
                 THEN 1 ELSE 0 END,
        last_wait_day=GREATEST(enterprise_build_waits.last_wait_day,EXCLUDED.last_wait_day)""",
      (eid,stage,amount,day,day))


def _pay_build_stage(conn, eid, owner, stage, amount, day):
    """Try exactly once per stage (ledger and payment row are transactional)."""
    if conn.execute('SELECT 1 FROM enterprise_stage_payments WHERE enterprise_id=%s '
                    'AND stage=%s',(eid,stage)).fetchone():
        conn.execute('DELETE FROM enterprise_build_waits WHERE enterprise_id=%s',(eid,))
        return True
    payer=conn.execute("""SELECT l.id FROM ledger_accounts l JOIN accounts a
      ON l.account_key='player:'||lower(a.username) WHERE a.id=%s""",(owner,)).fetchone()
    if payer is None:
        _record_build_wait(conn,eid,stage,amount,day)
        return False
    request_id=f'enterprise:build:{eid}:{stage}'
    transfer_id=None
    if amount:
        try:
            transfer_id=transfer(conn,request_id,payer[0],
                                 account(conn,'system:treasury'),amount)
        except ValueError as exc:
            if str(exc) != 'insufficient balance':
                raise
            _record_build_wait(conn,eid,stage,amount,day)
            return False
    conn.execute("""INSERT INTO enterprise_stage_payments
      (enterprise_id,stage,amount,request_id,transfer_id)
      VALUES(%s,%s,%s,%s,%s) ON CONFLICT(enterprise_id,stage) DO NOTHING""",
      (eid,stage,amount,request_id,transfer_id))
    conn.execute('DELETE FROM enterprise_build_waits WHERE enterprise_id=%s',(eid,))
    return True


def _advance_build(conn, eid, day, info):
    owner,cost,days,stage,progress,x,y,width,height,city=info
    durations=stage_day_lengths(days)
    amounts=stage_costs(cost)
    footprint={(a,b) for a in range(x,x+width) for b in range(y,y+height)}
    # Zero-day stages are allowed for short catalogue build_days. The loop
    # advances through them in one daily tick, as the reference simulator does.
    while stage<4:
        duration=durations[stage]
        if duration:
            # Advance time only while the current installment is not stalled.
            if progress < duration:
                progress += 1
            if progress < duration:
                break
        new_stage=stage+1
        if new_stage<4 and not _pay_build_stage(
                conn,eid,owner,new_stage,amounts[new_stage],day):
            # Progress is frozen at the boundary until the installment clears.
            progress=duration
            break
        stage=new_stage
        progress=0
        world._touch(conn,world._chunks_for_cells(footprint),'enterprise_stage',city,
                     {'enterprise_id':eid,'stage_index':stage,
                      'stage':STAGES[stage],'day_index':day})
    conn.execute('UPDATE enterprises SET stage=%s,stage_progress_days=%s '
                 'WHERE id=%s',(stage,progress,eid))


def advance_day(conn,day,default_staffing_bp=10000):
    integer(day)
    integer(default_staffing_bp,0,BP)
    rows=conn.execute('SELECT id FROM enterprises WHERE sold_at IS NULL '
                      'AND last_production_day<%s ORDER BY id',(day,)).fetchall()
    for (eid,) in rows:
        # Each construction and production step is an isolated savepoint.
        # An underfunded owner cannot block construction for others.
        with conn.transaction():
            info=conn.execute("""SELECT owner_id,build_cost,build_days,stage,
              stage_progress_days,x,y,width,height,city_id,last_production_day
              FROM enterprises WHERE id=%s AND sold_at IS NULL FOR UPDATE""",
              (eid,)).fetchone()
            if info is None or info[-1]>=day:
                continue
            # Match simulator: production precedes end-of-day construction.
            production(conn,eid,day,default_staffing_bp)
            if info[3]<4:
                _advance_build(conn,eid,day,info[:-1])


def close_month(conn,month,salary_per_worker=100,monthly_wear=1):
    """Draft: settle cumulative arrears atomically per enterprise, never block other owners."""
    from psycopg.types.json import Jsonb
    integer(month)
    integer(salary_per_worker,0,1000000)
    integer(monthly_wear,0,100)
    rows=conn.execute('SELECT id FROM enterprises WHERE sold_at IS NULL ORDER BY id').fetchall()
    for (eid,) in rows:
        # The caller's monthly transaction remains intact. This savepoint isolates
        # each enterprise's state and ledger postings from other enterprises.
        with conn.transaction():
            row=conn.execute('SELECT owner_id,jobs,upkeep_month,stage,last_month,wear,staffing_bp FROM enterprises WHERE id=%s AND sold_at IS NULL FOR UPDATE',(eid,)).fetchone()
            if row is None:continue
            owner,jobs,upkeep,stage,last,wear,staff=row
            if last>=month:continue
            expenses=0
            avg=0
            if stage==4 and month>0:
                loads=conn.execute('SELECT load_bp FROM enterprise_daily_load WHERE enterprise_id=%s AND day_index BETWEEN %s AND %s',(eid,(month-1)*30+1,month*30)).fetchall()
                avg=sum(r[0] for r in loads)//len(loads) if loads else 0
                expenses=upkeep+jobs*salary_per_worker*staff//BP
                prior=conn.execute('SELECT COALESCE(sum(amount),0),COALESCE(max(consecutive_months),0) FROM enterprise_arrears WHERE enterprise_id=%s AND paid_at IS NULL',(eid,)).fetchone()
                debt,streak=prior
                # PostgreSQL SUM(bigint) returns NUMERIC (Decimal), not int.
                due=integer(int(debt)+expenses)
                payer=conn.execute("SELECT l.id,l.balance FROM ledger_accounts l JOIN accounts a ON l.account_key='player:'||lower(a.username) WHERE a.id=%s FOR UPDATE",(owner,)).fetchone()
                if due and payer is not None and payer[1]>=due:
                    destination=account(conn,'system:upkeep')
                    # One journal for accumulated arrears and the current month.
                    # Idempotency is keyed by enterprise/month, not by retry count.
                    transfer(conn,f'enterprise:upkeep:{eid}:{month}',payer[0],destination,due)
                    conn.execute('UPDATE enterprise_arrears SET paid_at=now() WHERE enterprise_id=%s AND paid_at IS NULL',(eid,))
                elif expenses or debt:
                    # Current month's obligation is recorded once. Zero-expense
                    # months keep the previous debt without fabricating a charge.
                    if expenses:
                        conn.execute("""INSERT INTO enterprise_arrears
                          (enterprise_id,month_index,amount,consecutive_months)
                          VALUES(%s,%s,%s,%s) ON CONFLICT(enterprise_id,month_index) DO NOTHING""",
                          (eid,month,expenses,streak+1))
                wear=min(100,wear+monthly_wear)
                conn.execute('UPDATE enterprises SET wear=%s WHERE id=%s',(wear,eid))
            conn.execute("""INSERT INTO enterprise_month_reports(enterprise_id,month_index,revenue,expenses,average_load_bp,inventory,wear)
              VALUES(%s,%s,0,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
              (eid,month,expenses,avg,Jsonb(stock(conn,eid)),wear))
            conn.execute('UPDATE enterprises SET last_month=%s WHERE id=%s',(month,eid))
