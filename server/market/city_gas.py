"""Optional city gas utility: one atomic, ledger-backed sink per game day."""
from __future__ import annotations

from server.enterprises import core as enterprises
from server.ledger.api import account, transfer, MAX_INT
from server.world import core as world
from server.supply import core as supply


def required_gas(population):
    """Floor division, with a one-cubic-metre minimum for inhabited cities."""
    if type(population) is not int or not 0 <= population <= MAX_INT:
        raise ValueError('invalid_population')
    return max(1, population // 10000) if population else 0


def report(conn, day):
    """Stable admin-readable daily projection, including all shortages."""
    return [dict(city_id=city, day_index=index, needed_m3=needed,
                 bought_m3=bought, spent_rub=spent, short_m3=short,
                 seller_enterprise_id=seller)
            for city, index, needed, bought, spent, short, seller in conn.execute(
                """SELECT city_id,day_index,needed_m3,bought_m3,spent_rub,short_m3,
                          seller_enterprise_id
                   FROM city_gas_daily WHERE day_index=%s ORDER BY city_id""",
                (day,)).fetchall()]


def day(conn, day_index):
    """Purchase only local producer stock; never import or invent gas.

    Caller runs this in the same transaction as the daily clock. A persisted
    receipt is inserted for every city, even for zero stock or population.
    """
    if type(day_index) is not int or not 0 <= day_index <= MAX_INT:
        raise ValueError('invalid_day')
    with conn.transaction():
        # Prevent concurrent repeats from selecting the same inventory.
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',
                     ('city_gas:day:' + str(day_index),))
        states = world.city_states(conn)
        reference = enterprises.catalog().index['products']['gas']['reference_price']
        if type(reference) is not int or not 1 <= reference <= MAX_INT:
            raise ValueError('invalid_reference_price')
        for city_id in sorted(states):
            if conn.execute('SELECT 1 FROM city_gas_daily WHERE city_id=%s AND day_index=%s',
                            (city_id, day_index)).fetchone():
                continue
            needed = required_gas(states[city_id]['population'])
            bought = spent = 0
            seller = None
            if needed:
                # Use the same city-id semantics as the supply market; free-land
                # enterprises get their nearest city from x/y coordinates.
                for eid, owner, recipe, city, stage, running, _ in supply._enterprises(conn):
                    if city != city_id or stage != 4 or not running:
                        continue
                    product_recipe = enterprises.catalog().index['recipes'].get(recipe)
                    if not product_recipe or 'gas' not in product_recipe['outputs']:
                        continue
                    # This loop is already ordered by enterprise id.
                    stock = conn.execute(
                        """SELECT quantity FROM enterprise_inventory
                           WHERE enterprise_id=%s AND product_id='gas' FOR UPDATE""",
                        (eid,)).fetchone()
                    if stock and stock[0] > 0:
                        seller = eid, owner, int(stock[0])
                        break
            if seller:
                eid, owner, available = seller
                bought = min(needed, available)
                quote = conn.execute(
                    """SELECT price FROM market_prices
                       WHERE city_id=%s AND product_id='gas' AND day_index=%s""",
                    (city_id, day_index)).fetchone()
                unit_price = int(quote[0]) if quote else reference
                spent = bought * unit_price
                if spent > MAX_INT:
                    raise ValueError('city_gas_payment_overflow')
                wallet = conn.execute(
                    """SELECT l.id FROM ledger_accounts l JOIN accounts a
                       ON l.account_key='player:'||lower(a.username)
                       WHERE a.id=%s""", (owner,)).fetchone()
                if wallet is None:
                    raise ValueError('city_gas_owner_wallet_missing')
                transfer(conn, f'city_gas:{city_id}:{day_index}:{eid}',
                         account(conn, 'system:market'), wallet[0], spent)
                conn.execute(
                    """UPDATE enterprise_inventory SET quantity=quantity-%s
                       WHERE enterprise_id=%s AND product_id='gas'""",
                    (bought, eid))
            conn.execute(
                """INSERT INTO city_gas_daily
                   (city_id,day_index,needed_m3,bought_m3,spent_rub,short_m3,
                    seller_enterprise_id)
                   VALUES(%s,%s,%s,%s,%s,%s,%s)""",
                (city_id, day_index, needed, bought, spent,
                 needed-bought, seller[0] if seller else None))
    return report(conn, day_index)
