"""A2 economic diagnostics and immutable end-of-day snapshots."""
from server.ledger.api import reconcile
from server.platform import admin


def _day(conn):
    return int(conn.execute("SELECT COALESCE(MAX(day_index), -1) FROM game_ticks WHERE completed").fetchone()[0])


def _scalar(conn, sql, args=()):
    return int(conn.execute(sql, args).fetchone()[0] or 0)


def _vat(conn, where, args):
    # Calculate per sale: flooring each receipt matters. Cast to numeric to avoid overflow.
    return _scalar(conn, 'SELECT COALESCE(sum(revenue - floor(revenue::numeric * 10000 / (10000+vat_bp))),0) FROM retail_sales_daily WHERE '+where,args)



def _reconstitute_output(volume, load_bp, output_carry):
    """Exact integer output from the production tick's post-state carry."""
    output = int(volume) * int(load_bp)
    carry_before = (int(output_carry) - output) % 10000
    return (output + carry_before) // 10000


def capture_production(conn, day):
    """Runs directly after enterprise production, before any next-day inventory change.

    The production handler stores new output carry and day load, which uniquely
    determine produced units. No enterprise module changes or synthetic estimates.
    """
    from server.enterprises.core import catalog
    if conn.execute('SELECT 1 FROM admin_production_receipts WHERE day_index=%s',(day,)).fetchone():
        return
    recipes = catalog().index['recipes']
    rows = conn.execute("""SELECT e.id,e.recipe_id,l.load_bp,i.product_id,i.output_carry
       FROM enterprise_daily_load l JOIN enterprises e ON e.id=l.enterprise_id
       JOIN enterprise_inventory i ON i.enterprise_id=e.id
       WHERE l.day_index=%s AND e.recipe_id IS NOT NULL ORDER BY e.id,i.product_id""",(day,)).fetchall()
    produced={}
    for _,recipe_id,load,product,carry in rows:
        volume=recipes[recipe_id]['outputs'].get(product)
        if volume is None:
            continue
        units=_reconstitute_output(volume,load,carry)
        produced[product]=produced.get(product,0)+units
    for product,quantity in sorted(produced.items()):
        conn.execute("""INSERT INTO admin_production_daily(day_index,product_id,quantity)
            VALUES(%s,%s,%s) ON CONFLICT (day_index,product_id) DO NOTHING""",
            (day,product,quantity))
    conn.execute('INSERT INTO admin_production_receipts(day_index) VALUES(%s) ON CONFLICT DO NOTHING',(day,))

def snapshot(conn, day):
    """Tick handler runs last, but before the final day receipt. Conflict never changes history."""
    players = _scalar(conn, 'SELECT count(*) FROM accounts')
    enterprises = _scalar(conn, 'SELECT count(*) FROM enterprises WHERE sold_at IS NULL')
    money = _scalar(conn, "SELECT COALESCE(sum(balance),0) FROM ledger_accounts WHERE kind='player'")
    retail = _scalar(conn, 'SELECT COALESCE(sum(revenue),0) FROM retail_sales_daily WHERE day_index=%s', (day,))
    vat = _vat(conn,'day_index=%s',(day,))
    conn.execute('''INSERT INTO admin_daily_stats(day_index,players,enterprises,player_money,retail_revenue,vat)
                    VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT (day_index) DO NOTHING''',
                 (day, players, enterprises, money, retail, vat))


def economy(body, ctx):
    actor, err = admin_a2.guard(ctx)
    if err: return err
    conn = ctx['conn']
    day = _day(conn)
    accounts = [{'account': row[0], 'balance': int(row[1])} for row in conn.execute(
        "SELECT account_key,balance FROM ledger_accounts WHERE kind='system' ORDER BY account_key").fetchall()]
    by_building = [{'building': r[0], 'count': int(r[1])} for r in conn.execute(
        'SELECT building_id,count(*) FROM enterprises WHERE sold_at IS NULL GROUP BY building_id ORDER BY building_id').fetchall()]
    by_stage = [{'stage': int(r[0]), 'count': int(r[1])} for r in conn.execute(
        'SELECT stage,count(*) FROM enterprises WHERE sold_at IS NULL GROUP BY stage ORDER BY stage').fetchall()]
    sales = [{'product': r[0], 'quantity': int(r[1]), 'revenue': int(r[2])} for r in conn.execute(
        '''SELECT product_id,sum(quantity),sum(revenue) FROM retail_sales_daily
           WHERE day_index BETWEEN %s AND %s GROUP BY product_id ORDER BY product_id''', (max(0, day-6), day)).fetchall()]
    production = [{'product':r[0],'quantity':int(r[1])} for r in conn.execute(
        """SELECT product_id,COALESCE(sum(quantity),0) FROM admin_production_daily
           WHERE day_index BETWEEN %s AND %s GROUP BY product_id ORDER BY product_id""",
        (max(0,day-6),day)).fetchall()]
    money_top = [{'name': r[0], 'money': int(r[1])} for r in conn.execute(
        '''SELECT a.username,l.balance FROM ledger_accounts l JOIN accounts a ON a.id=l.owner_id
           WHERE l.kind='player' ORDER BY l.balance DESC,a.id LIMIT 10''').fetchall()]
    enterprise_top = [{'name': r[0], 'count': int(r[1])} for r in conn.execute(
        '''SELECT a.username,count(*) FROM enterprises e JOIN accounts a ON a.id=e.owner_id
           WHERE e.sold_at IS NULL GROUP BY a.id,a.username ORDER BY count(*) DESC,a.id LIMIT 10''').fetchall()]
    return 200, {
        'day_index': day, 'player_money': _scalar(conn, "SELECT COALESCE(sum(balance),0) FROM ledger_accounts WHERE kind='player'"),
        'system_accounts': accounts, 'treasury': next((r['balance'] for r in accounts if r['account']=='system:treasury'),0),
        'ledger_total': _scalar(conn, 'SELECT COALESCE(sum(amount),0) FROM ledger_entries'),
        'reconcile': admin._json_value(reconcile(conn)),
        'players': _scalar(conn,'SELECT count(*) FROM accounts'),
        'active_24h': _scalar(conn, "SELECT count(DISTINCT account_id) FROM sessions WHERE created_at>=now()-interval '24 hours'"),
        'active_7d': _scalar(conn, "SELECT count(DISTINCT account_id) FROM sessions WHERE created_at>=now()-interval '7 days'"),
        'enterprises_by_building': by_building, 'enterprises_by_stage': by_stage,
        'revenue_7d': sum(x['revenue'] for x in sales), 'tax_7d': _vat(conn,'day_index BETWEEN %s AND %s',(max(0,day-6),day)),
        'sales_7d': sales, 'production_7d': production,
        'production_metric': 'daily_factory_output',
        'top_money': money_top, 'top_enterprises': enterprise_top,
    }


def history(body, ctx):
    actor, err = admin_a2.guard(ctx)
    if err: return err
    try:
        days = admin_a2.integer(admin._query(ctx,'days','30'),1,90)
        cursor = admin_a2.integer(admin._query(ctx,'after','0'),0,2**63-1)
        limit = admin_a2.integer(admin._query(ctx,'limit',str(min(days,90))),1,90)
    except ValueError: return 400, {'error':'invalid_pagination'}
    end = _day(ctx['conn'])
    start = max(0,end-days+1)
    rows = ctx['conn'].execute('''SELECT day_index,players,enterprises,player_money,retail_revenue,vat
          FROM admin_daily_stats WHERE day_index BETWEEN %s AND %s AND day_index >= %s
          ORDER BY day_index ASC LIMIT %s''', (start,end,cursor,limit)).fetchall()
    items = [{'day_index':int(r[0]), 'players':int(r[1]), 'enterprises':int(r[2]),
              'player_money':int(r[3]), 'retail_revenue':int(r[4]),'vat':int(r[5])} for r in rows]
    return 200, {'items':items, 'days':days, 'limit':limit,
                 'next_after':items[-1]['day_index']+1 if len(items)==limit else None}


# Avoid a runtime dependency loop during module initialization.
from . import admin_server as admin_a2
