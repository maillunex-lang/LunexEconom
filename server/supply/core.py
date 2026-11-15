"""Deterministic daily wholesale clearing for V2-05.

No floating point, no inventory creation except explicitly funded port imports.
All stock and ledger movements participate in the caller's daily transaction.
"""
from __future__ import annotations

from collections import defaultdict
from server.enterprises import core as enterprise
from server.ledger.api import account, transfer
from server.world import core as world

MAX = 2**63 - 1


def integer(value, minimum=0, maximum=MAX):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('invalid_integer')
    return value


# Preserve the original helper for compatible callers/tests.
_int = integer


def _recipe(recipe_id):
    return enterprise.catalog().index['recipes'].get(recipe_id) if recipe_id else None


def validate_links(conn, row, inputs):
    """Validate the replacement set, using only inputs of the current recipe."""
    if not isinstance(inputs, dict):
        raise ValueError('invalid_inputs')
    recipe = _recipe(row[2])
    if not set(inputs).issubset(recipe['inputs'] if recipe else {}):
        raise ValueError('not_own_input')
    result = []
    for product, links in sorted(inputs.items()):
        if not isinstance(links, list) or len(links) > 3:
            raise ValueError('too_many_suppliers')
        shares, priorities, sources = 0, set(), set()
        for slot, link in enumerate(links, 1):
            if not isinstance(link, dict) or set(link) != {
                    'source_type', 'source_enterprise_id', 'share',
                    'priority', 'max_price', 'min_quality'}:
                raise ValueError('invalid_link_fields')
            kind, supplier = link['source_type'], link['source_enterprise_id']
            if kind not in ('enterprise', 'market', 'port'):
                raise ValueError('invalid_source_type')
            if kind == 'enterprise':
                integer(supplier, 1)
                if supplier == row[0]:
                    raise ValueError('self_supply')
                found = conn.execute(
                    'SELECT building_id,recipe_id FROM enterprises '
                    'WHERE id=%s AND sold_at IS NULL', (supplier,)
                ).fetchone()
                if found is None:
                    raise ValueError('unknown_supplier')
                # A warehouse may ship any catalog good it actually stocks.
                if found[0] != 'warehouse' and product not in (
                        _recipe(found[1]) or {'outputs': {}})['outputs']:
                    raise ValueError('supplier_does_not_produce_product')
            elif supplier is not None:
                raise ValueError('unexpected_supplier_id')
            share = integer(link['share'], 1, 1000)
            priority = integer(link['priority'], 1, 3)
            price = integer(link['max_price'])
            quality = integer(link['min_quality'], 0, 100)
            if priority in priorities or (kind, supplier) in sources:
                raise ValueError('duplicate_supplier_or_priority')
            priorities.add(priority)
            sources.add((kind, supplier))
            shares += share
            result.append((product, {
                'slot': slot, 'source_type': kind, 'source_enterprise_id': supplier,
                'share': share, 'priority': priority, 'max_price': price,
                'min_quality': quality,
            }))
        if shares > 1000:
            raise ValueError('share_exceeds_1000')
    return result


def read_links(conn, eid):
    rows = conn.execute(
        'SELECT product_id,source_type,source_enterprise_id,share,priority,'
        'max_price,min_quality FROM supply_links WHERE enterprise_id=%s '
        'ORDER BY product_id,priority,slot', (eid,)
    ).fetchall()
    result = {}
    for product, kind, supplier, share, priority, price, quality in rows:
        result.setdefault(product, []).append({
            'source_type': kind, 'source_enterprise_id': supplier,
            'share': share, 'priority': priority, 'max_price': price,
            'min_quality': quality,
        })
    return result


def _city(city_id, x, y):
    return city_id or world.nearest_city(x, y)['id']


def _enterprises(conn):
    # City lookup for free-land farms is deterministic, read-only world logic.
    rows = conn.execute(
        'SELECT id,owner_id,recipe_id,city_id,stage,running,'
        'storage_capacity,x,y FROM enterprises WHERE sold_at IS NULL ORDER BY id'
    ).fetchall()
    return [(eid, owner, recipe, _city(city, x, y), stage, running, capacity)
            for eid, owner, recipe, city, stage, running, capacity, x, y in rows]


def _wallet(conn, owner):
    return conn.execute(
        "SELECT l.id,l.balance FROM ledger_accounts l JOIN accounts a "
        "ON l.account_key='player:'||lower(a.username) "
        'WHERE a.id=%s FOR UPDATE', (owner,)
    ).fetchone()


def _in_transit(conn, eid):
    rows = conn.execute(
        "SELECT product_id,COALESCE(sum(quantity),0) FROM shipments "
        "WHERE buyer_enterprise_id=%s AND status<>'delivered' GROUP BY product_id",
        (eid,)
    ).fetchall()
    return {p: int(q) for p, q in rows}


def _free(conn, eid, capacity):
    reserved = sum(_in_transit(conn, eid).values())
    return max(0, capacity - enterprise.stock_total(conn, eid) - reserved)


def _need(conn, row):
    eid, _, recipe_id, _, stage, running, capacity = row
    recipe = _recipe(recipe_id)
    if not recipe or stage != 4 or not running:
        return {}
    if conn.execute(
            'SELECT 1 FROM enterprise_arrears '
            'WHERE enterprise_id=%s AND paid_at IS NULL LIMIT 1',
            (eid,)).fetchone():
        return {}
    stored = enterprise.stock(conn, eid)
    pending = _in_transit(conn, eid)
    free = max(0, capacity - sum(v['quantity'] for v in stored.values())
               - sum(pending.values()))
    result = {}
    for product, target in recipe['inputs'].items():
        missing = max(0, target - stored.get(product, {}).get('quantity', 0)
                      - pending.get(product, 0))
        result[product] = min(missing, free)
        free -= result[product]
    return result


def _travel(source_city, dest_city, quantity, per_km_unit):
    if not source_city or not dest_city or source_city == dest_city:
        return 0, 0
    route = world.routes(source_city, dest_city)
    days = max(1, (route['game_minutes'] + 1439) // 1440)
    cost = integer(route['distance_meters'] * quantity * per_km_unit // 1000)
    return days, cost


def _port(flags, destination):
    raw = flags['supply_port_city_draft']
    if type(raw) is not str:
        raise ValueError('invalid_port_setting')
    ports = [s.strip() for s in raw.split(',') if s.strip()]
    if not ports or any(port not in world.CITIES for port in ports):
        raise ValueError('invalid_port_setting')
    return min(set(ports), key=lambda port: (
        world.routes(port, destination)['distance_meters'], port))


def _ship(conn, key, buyer, seller, kind, product, quantity, quality,
          unit_price, transport, day, arrival, transfer_id):
    conn.execute(
        """INSERT INTO shipments
        (request_id,buyer_enterprise_id,seller_enterprise_id,source_type,
         product_id,quantity,quality,unit_price,transport_cost,
         dispatched_day,arrival_day,status,transfer_id)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (key, buyer, seller, kind, product, quantity, quality, unit_price,
         transport, day, arrival,
         'delivered' if arrival == day else 'transit', transfer_id))
    if arrival == day:
        enterprise.adjust(conn, buyer, product, quantity, quality)


def _buy(conn, day, row, product, quantity, kind, supplier, price,
         min_quality, flags, sequence, via_market=False):
    """0 on unavailable seller, warehouse, quality or wallet; never an overdraft.

    A per-trade savepoint guarantees no half-applied inventory or journals.
    """
    buyer_id, owner, _, destination, _, _, capacity = row
    quantity = min(integer(quantity), _free(conn, buyer_id, capacity))
    if quantity == 0:
        return 0
    buyer_wallet = _wallet(conn, owner)
    if buyer_wallet is None:
        return 0
    buyer_account, buyer_balance = buyer_wallet
    quality, source_city, seller_account = 50, None, None
    if kind == 'enterprise':
        src = conn.execute(
            'SELECT owner_id,city_id,x,y FROM enterprises '
            'WHERE id=%s AND sold_at IS NULL FOR UPDATE', (supplier,)
        ).fetchone()
        if not src:
            return 0
        source_owner, source_city, x, y = src
        source_city = _city(source_city, x, y)
        goods = enterprise.stock(conn, supplier).get(
            product, {'quantity': 0, 'quality': 0})
        if goods['quality'] < min_quality:
            return 0
        quantity = min(quantity, goods['quantity'])
        if not quantity:
            return 0
        quality = goods['quality']
        seller = _wallet(conn, source_owner)
        if seller is None:
            return 0
        seller_account = seller[0]
        if seller_account == buyer_account:
            # No internal sales revenue is booked for the same owner.
            price = 0
    elif kind == 'port':
        source_city = _port(flags, destination)
        if min_quality > quality:
            return 0
        seller_account = account(conn, 'system:market')
    else:
        raise ValueError('invalid_purchase_source')

    days, freight = _travel(
        source_city, destination, quantity,
        flags['supply_transport_rub_per_km_unit_draft'])
    if kind == 'port':
        days = max(1, days)
    subtotal = integer(quantity * price)
    total = integer(subtotal + freight)
    if total > buyer_balance:
        return 0
    key = f'supply:{buyer_id}:{product}:{day}:{kind}-{supplier or "system"}:{sequence}'
    if len(key) > 128:
        raise ValueError('invalid_request_id')
    with conn.transaction():
        if kind == 'enterprise':
            enterprise.adjust(conn, supplier, product, -quantity)
        journal = None
        if subtotal:
            if via_market and seller_account != buyer_account:
                clearing_account = account(conn, 'system:market')
                journal = transfer(conn, key, buyer_account, clearing_account,
                                   subtotal)
                transfer(conn, key + ':payout', clearing_account,
                         seller_account, subtotal)
            else:
                journal = transfer(conn, key, buyer_account, seller_account,
                                   subtotal)
        if freight:
            transfer(conn, key + ':freight', buyer_account,
                     account(conn, 'system:market'), freight)
        _ship(conn, key, buyer_id, supplier if kind == 'enterprise' else None,
              kind, product, quantity, quality, price, freight, day,
              day + days, journal)
    return quantity


def _arrivals(conn, day):
    rows = conn.execute(
        """SELECT id,buyer_enterprise_id,product_id,quantity,quality
        FROM shipments WHERE arrival_day<=%s AND status<>'delivered'
        ORDER BY arrival_day,id FOR UPDATE""", (day,)
    ).fetchall()
    for shipment_id, eid, product, quantity, quality in rows:
        capacity_row = conn.execute(
            'SELECT storage_capacity FROM enterprises '
            'WHERE id=%s AND sold_at IS NULL FOR UPDATE', (eid,)
        ).fetchone()
        if capacity_row is None or (
                enterprise.stock_total(conn, eid) + quantity > capacity_row[0]):
            conn.execute(
                "UPDATE shipments SET status='waiting_capacity' WHERE id=%s",
                (shipment_id,))
            continue
        enterprise.adjust(conn, eid, product, quantity, quality)
        conn.execute(
            "UPDATE shipments SET status='delivered' WHERE id=%s",
            (shipment_id,))


def links_day(conn, day, flags):
    integer(day)
    if conn.execute(
            "SELECT 1 FROM supply_receipts WHERE day_index=%s AND phase='links'",
            (day,)).fetchone():
        return
    _arrivals(conn, day)
    prices = {p: item['reference_price']
              for p, item in enterprise.catalog().index['products'].items()}
    for row in _enterprises(conn):
        eid = row[0]
        for product, needed in sorted(_need(conn, row).items()):
            conn.execute(
                """INSERT INTO supply_daily_needs
                (enterprise_id,product_id,day_index,requested,unfilled)
                VALUES(%s,%s,%s,%s,%s)""",
                (eid, product, day, needed, needed))
            remaining, linked = needed, 0
            links = conn.execute(
                """SELECT source_type,source_enterprise_id,share,max_price,
                min_quality FROM supply_links WHERE enterprise_id=%s
                AND product_id=%s ORDER BY priority,slot""",
                (eid, product)
            ).fetchall()
            for index, (kind, supplier, share, max_price, quality) in enumerate(links, 1):
                if not remaining:
                    break
                if kind != 'enterprise' or prices[product] > max_price:
                    continue
                allotted = min(remaining, needed * share // 1000)
                if not allotted:
                    continue
                try:
                    received = _buy(conn, day, row, product, allotted, kind,
                                    supplier, prices[product], quality,
                                    flags, index)
                except ValueError as exc:
                    if str(exc) != 'insufficient balance':
                        raise
                    received = 0
                linked += received
                remaining -= received
            conn.execute(
                """UPDATE supply_daily_needs SET linked=%s,unfilled=%s
                WHERE enterprise_id=%s AND product_id=%s AND day_index=%s""",
                (linked, remaining, eid, product, day))
    conn.execute(
        "INSERT INTO supply_receipts(day_index,phase) VALUES(%s,'links')",
        (day,))


def _market_rules(links, need):
    """Priority-ordered explicit market links, plus automatic residual fallback."""
    selected = [link for link in links if link[0] == 'market']
    if not selected:
        return [(need, MAX, 0)]
    allocated = sum(need * link[1] // 1000 for link in selected)
    rules = [(need * share // 1000, cap, quality)
             for _, share, cap, quality, _ in sorted(selected, key=lambda x: x[4])]
    if allocated < need:
        rules.append((need - allocated, MAX, 0))
    return rules


def market_day(conn, day, flags):
    from server.market.core import clearing_price

    integer(day)
    if conn.execute(
            "SELECT 1 FROM supply_receipts WHERE day_index=%s AND phase='market'",
            (day,)).fetchone():
        return
    if not conn.execute(
            "SELECT 1 FROM supply_receipts WHERE day_index=%s AND phase='links'",
            (day,)).fetchone():
        raise ValueError('links_phase_missing')

    rows = {row[0]: row for row in _enterprises(conn)}
    bids, offers = defaultdict(list), defaultdict(list)
    for eid, product, missing in conn.execute(
            """SELECT enterprise_id,product_id,unfilled
            FROM supply_daily_needs WHERE day_index=%s AND unfilled>0
            ORDER BY enterprise_id,product_id""", (day,)).fetchall():
        bids[(rows[eid][3], product)].append((eid, missing))
    for eid, owner, recipe_id, city, stage, running, _ in rows.values():
        recipe = _recipe(recipe_id)
        if stage != 4 or not running or not recipe:
            continue
        for product in recipe['outputs']:
            item = enterprise.stock(conn, eid).get(product)
            if item and item['quantity'] > 0:
                offers[(city, product)].append([eid, item['quantity'], item['quality']])
    products = enterprise.catalog().index['products']
    # Daily quotes exist even for untraded products, as required by market API.
    for city in sorted(world.CITIES):
        for product in sorted(products):
            buying, selling = bids[(city, product)], offers[(city, product)]
            demand = sum(qty for _, qty in buying)
            supply = sum(qty for _, qty, _ in selling)
            reference = products[product]['reference_price']
            quote = clearing_price(reference, demand, supply)
            volume = 0
            for buyer_id, requested in buying:
                buyer, remaining = rows[buyer_id], requested
                links = conn.execute(
                    """SELECT source_type,share,max_price,min_quality,priority
                    FROM supply_links WHERE enterprise_id=%s AND product_id=%s
                    ORDER BY priority,slot""",
                    (buyer_id, product)).fetchall()
                for allocation, cap, minimum in _market_rules(links, requested):
                    capacity = min(allocation, remaining)
                    if not capacity or quote > cap:
                        continue
                    for offer in selling:
                        if not capacity:
                            break
                        seller_id, on_hand, quality = offer
                        if seller_id == buyer_id or not on_hand or quality < minimum:
                            continue
                        try:
                            qty = _buy(conn, day, buyer, product,
                                       min(capacity, on_hand), 'enterprise',
                                       seller_id, quote, minimum, flags,
                                       100000 + seller_id, via_market=True)
                        except ValueError as exc:
                            if str(exc) != 'insufficient balance':
                                raise
                            qty = 0
                        offer[1] -= qty
                        capacity -= qty
                        remaining -= qty
                        volume += qty
                market_filled = requested - remaining

                port_links = [item for item in links if item[0] == 'port']
                import_cap = MAX
                import_min_quality = 0
                import_qty = 0
                if port_links:
                    # Explicit quota is honored, and unsuccessful links may
                    # also fall back to the port up to the remaining share.
                    import_qty = min(remaining, sum(
                        requested * item[1] // 1000 for item in port_links))
                    import_cap = max(item[2] for item in port_links)
                    import_min_quality = min(item[3] for item in port_links)
                elif flags['supply_port_fallback_draft']:
                    import_qty = remaining
                ordered = 0
                if import_qty:
                    world_price = reference * flags[
                        'supply_port_price_permille_draft'] // 1000
                    duty = world_price * flags[
                        'supply_port_duty_bp_draft'] // 10000
                    import_price = integer(world_price + duty)
                    if import_price <= import_cap and import_min_quality <= 50:
                        try:
                            ordered = _buy(
                                conn, day, buyer, product, import_qty, 'port',
                                None, import_price, import_min_quality,
                                flags, 900000)
                        except ValueError as exc:
                            if str(exc) != 'insufficient balance':
                                raise
                remaining -= ordered
                conn.execute(
                    """UPDATE supply_daily_needs SET market_filled=%s,
                    port_ordered=%s,unfilled=%s
                    WHERE enterprise_id=%s AND product_id=%s AND day_index=%s""",
                    (market_filled, ordered, remaining, buyer_id, product, day))
            conn.execute(
                """INSERT INTO market_prices
                (city_id,product_id,day_index,price,demand,supply,volume)
                VALUES(%s,%s,%s,%s,%s,%s,%s)""",
                (city, product, day, quote, demand, supply, volume))
    conn.execute(
        "INSERT INTO supply_receipts(day_index,phase) VALUES(%s,'market')",
        (day,))
