"""V2-05 PostgreSQL integration, all test fixtures rolled back."""
import os
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from server import db
from server.game_server import create_app, build_registry
from server.enterprises import core as enterprises
from server.ledger.api import account, transfer, reconcile
from server.supply import core as supply, api as supply_api
from server.market import api as market_api
from server.world import core as world

DSN = os.getenv('LUNEX_TEST_DATABASE_URL')
FLAGS = {
    'supply_transport_rub_per_km_unit_draft': 1,
    'supply_port_city_draft': 'ufa',
    'supply_port_price_permille_draft': 1000,
    'supply_port_duty_bp_draft': 500,
    'supply_port_fallback_draft': False,
}


@unittest.skipUnless(DSN, 'Requires isolated PostgreSQL 16 test DSN')
class SupplyPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app(DSN)

    @classmethod
    def tearDownClass(cls):
        cls.app.close()

    def setUp(self):
        self.conn = db.connect(DSN)
        self.fixture = uuid4().hex
        self.serial = 0
        # Daily receipt is global per day. Earlier integration tests may have
        # completed day 0 before this isolated fixture is created.
        self.day = int(self.conn.execute(
            "SELECT GREATEST(COALESCE((SELECT max(day_index) FROM supply_receipts),-1),"
            " COALESCE((SELECT max(day_index) FROM game_ticks),-1))"
        ).fetchone()[0]) + 100
        self.treasury = account(self.conn, 'system:treasury')

    def tearDown(self):
        self.conn.rollback()
        self.conn.close()

    def owner(self, money=1000000):
        name = 'su' + uuid4().hex[:12]
        actor = self.conn.execute(
            """INSERT INTO accounts(username,email,password_hash,role)
            VALUES(%s,%s,'test-hash','player') RETURNING id""",
            (name, name + '@example.test')
        ).fetchone()[0]
        wallet = account(self.conn, 'player:' + name, 'player', actor)
        capital = transfer(
            self.conn, 'supply:fixture:' + uuid4().hex,
            self.treasury, wallet, max(1, money))
        if money == 0:
            transfer(self.conn, 'supply:empty:' + uuid4().hex,
                     wallet, self.treasury, 1)
        return {'id': actor, 'username': name,
                'wallet': wallet, 'capital': capital}

    def enterprise(self, owner, building, recipe=None, city='ufa',
                   stock=None, capacity=4000):
        self.serial += 1
        px = 900000000 + owner['id'] * 10000 + self.serial
        py = 900000000 + owner['id'] * 10000 + self.serial
        self.conn.execute(
            """INSERT INTO world_parcels(px,py,city_id,owner_kind,owner_ref)
            VALUES(%s,%s,%s,'player',%s)""",
            (px, py, city, str(owner['id'])))
        if recipe is None and building != 'warehouse':
            recipes = [r for r in enterprises.catalog().data['recipes']
                       if r['building'] == building]
            recipe = recipes[0]['id'] if recipes else None
        coords = world.CITIES[city] if city else world.CITIES['ufa']
        eid = self.conn.execute(
            """INSERT INTO enterprises
            (owner_id,building_id,px,py,x,y,width,height,city_id,name,
             build_cost,build_days,upkeep_month,jobs,storage_capacity,
             started_day,stage,running,recipe_id,build_request_id,build_transfer_id)
            VALUES(%s,%s,%s,%s,%s,%s,1,1,%s,'supply test',1,1,0,0,%s,
                   0,4,true,%s,%s,%s) RETURNING id""",
            (owner['id'], building, px, py, coords['x'], coords['y'],
             city, capacity, recipe,
             'supply:build:' + uuid4().hex, owner['capital'])
        ).fetchone()[0]
        for product, amount, quality in stock or ():
            enterprises.adjust(self.conn, eid, product, amount, quality)
        return eid

    def link(self, buyer, product, source, slot=1, share=1000, priority=1,
             cap=1000000, quality=0, kind='enterprise'):
        self.conn.execute(
            """INSERT INTO supply_links
            (enterprise_id,product_id,slot,source_type,source_enterprise_id,
             share,priority,max_price,min_quality)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (buyer, product, slot, kind, source if kind == 'enterprise' else None,
             share, priority, cap, quality))

    def run_day(self, day):
        supply.links_day(self.conn, day, FLAGS)
        supply.market_day(self.conn, day, FLAGS)
        enterprises.advance_day(self.conn, day)

    def qty(self, eid, product):
        return enterprises.stock(self.conn, eid).get(
            product, {'quantity': 0})['quantity']

    def balance(self, owner):
        return self.conn.execute(
            'SELECT balance FROM ledger_accounts WHERE id=%s',
            (owner['wallet'],)).fetchone()[0]

    def test_link_validation_and_owner_api(self):
        a, b = self.owner(), self.owner()
        buyer = self.enterprise(a, 'mill', recipe='mill_flour')
        suppliers = [
            self.enterprise(a, 'field', recipe='field_grain'),
            self.enterprise(b, 'field', recipe='field_grain'),
            self.enterprise(a, 'warehouse')]
        link = lambda source, priority, share: {
            'source_type': 'enterprise', 'source_enterprise_id': source,
            'priority': priority, 'share': share,
            'max_price': 25, 'min_quality': 50}
        valid = {'grain': [link(suppliers[0], 1, 400),
                           link(suppliers[1], 2, 300),
                           link(suppliers[2], 3, 300)]}
        with patch('server.supply.api.authenticate', return_value=a):
            ctx = {'conn': self.conn, 'path_params': {'id': str(buyer)}}
            code, data = supply_api.put({'inputs': valid}, ctx)
            self.assertEqual(code, 200, data)
            self.assertEqual(len(supply_api.get({}, ctx)[1]['inputs']['grain']), 3)
            for broken in (
                {'grain': valid['grain'] + [link(suppliers[0], 1, 1)]},
                {'grain': [link(suppliers[0], 1, 700),
                           link(suppliers[1], 2, 400)]},
                {'grain': [link(suppliers[0], 1, 500),
                           link(suppliers[1], 1, 500)]},
                {'flour': [link(suppliers[0], 1, 1000)]},
                {'grain': [link(999999999999, 1, 1000)]},
                {'grain': [link(suppliers[0], 1, 1000) |
                           {'min_quality': 101}]},
                {'grain': [link(suppliers[0], 1, 1000) |
                           {'max_price': -1}]}):
                self.assertEqual(supply_api.put({'inputs': broken}, ctx)[0], 400)
            self.assertEqual(supply_api.get({}, ctx)[1]['inputs'],
                             supply_api.put({'inputs': valid}, ctx)[1]['inputs'])
        with patch('server.supply.api.authenticate', return_value=b):
            self.assertEqual(supply_api.get({}, ctx)[0], 404)
            self.assertEqual(supply_api.put({'inputs': valid}, ctx)[0], 404)
        with patch('server.supply.api.authenticate', return_value=None):
            self.assertEqual(supply_api.get({}, ctx)[0], 401)
        registry = build_registry()
        self.assertEqual([name for _,name,_ in sorted(registry.tick_handlers['daily'])][0:2],
                         ['supply_links', 'supply_market'])
        self.assertIn(('PUT', '/enterprises/{id}/supply'), registry.routes)

    def test_internal_transfer_and_repeat_no_phantom_revenue(self):
        owner = self.owner()
        field = self.enterprise(owner, 'field', stock=[('grain', 100, 65)])
        mill = self.enterprise(owner, 'mill', recipe='mill_flour')
        self.link(mill, 'grain', field, quality=60)
        before = self.balance(owner)
        supply.links_day(self.conn, self.day, FLAGS)
        self.assertEqual(self.qty(mill, 'grain'), 100)
        self.assertEqual(self.qty(field, 'grain'), 0)
        self.assertEqual(enterprises.stock(self.conn, mill)['grain']['quality'], 65)
        self.assertEqual(self.balance(owner), before)
        count = self.conn.execute('SELECT count(*) FROM ledger_transfers').fetchone()[0]
        supply.links_day(self.conn, self.day, FLAGS)
        self.assertEqual(self.balance(owner), before)
        self.assertEqual(self.conn.execute(
            'SELECT count(*) FROM ledger_transfers').fetchone()[0], count)
        supply.market_day(self.conn, self.day, FLAGS)
        supply.market_day(self.conn, self.day, FLAGS)
        self.assertTrue(reconcile(self.conn)['ok'])

    def test_max_price_quality_and_city_market_settlement(self):
        seller = self.owner()
        buyer = self.owner()
        field = self.enterprise(seller, 'field', stock=[('grain', 70, 40)])
        mill = self.enterprise(buyer, 'mill')
        self.link(mill, 'grain', field, cap=24, quality=50)
        supply.links_day(self.conn, self.day, FLAGS)
        self.assertEqual(self.qty(mill, 'grain'), 0)
        initial_buyer, initial_seller = self.balance(buyer), self.balance(seller)
        supply.market_day(self.conn, self.day, FLAGS)
        # Residual city order is permissive; the explicit supplier link is not.
        self.assertEqual(self.qty(mill, 'grain'), 70)
        quote = self.conn.execute(
            """SELECT price,demand,supply,volume FROM market_prices
            WHERE city_id='ufa' AND product_id='grain' AND day_index=%s"""
        ,(self.day,)).fetchone()
        self.assertEqual(quote, (35, 100, 70, 70))
        self.assertEqual(self.balance(buyer), initial_buyer - 70 * 35)
        self.assertEqual(self.balance(seller), initial_seller + 70 * 35)
        self.assertEqual(market_api.city_for('ufa')({}, {'conn': self.conn})[0], 200)
        self.assertEqual(market_api.history(
            {}, {'conn': self.conn, 'query': {
                'city': ['ufa'], 'product': ['grain']}})[1]['history'][0]['price'], 35)
        self.assertTrue(reconcile(self.conn)['ok'])

    def test_port_transit_and_no_duplicate_purchase(self):
        owner = self.owner(5000000)
        mill = self.enterprise(owner, 'mill', city='sterlitamak')
        self.link(mill, 'grain', None, kind='port', quality=50)
        supply.links_day(self.conn, self.day, FLAGS)
        supply.market_day(self.conn, self.day, FLAGS)
        shipped = self.conn.execute(
            """SELECT quantity,arrival_day,status FROM shipments
            WHERE buyer_enterprise_id=%s""", (mill,)).fetchone()
        self.assertEqual(shipped[0], 100)
        self.assertGreater(shipped[1], self.day)
        self.assertEqual(shipped[2], 'transit')
        self.assertEqual(self.qty(mill, 'grain'), 0)
        payments = self.conn.execute(
            "SELECT count(*) FROM ledger_transfers WHERE request_id LIKE %s",
            (f'supply:{mill}:grain:{self.day}:%',)).fetchone()[0]
        supply.links_day(self.conn, self.day, FLAGS)
        supply.market_day(self.conn, self.day, FLAGS)
        self.assertEqual(self.conn.execute(
            "SELECT count(*) FROM ledger_transfers WHERE request_id LIKE %s",
            (f'supply:{mill}:grain:{self.day}:%',)).fetchone()[0], payments)
        for day in range(self.day + 1, shipped[1] + 1):
            supply.links_day(self.conn, day, FLAGS)
            supply.market_day(self.conn, day, FLAGS)
        self.assertEqual(self.qty(mill, 'grain'), 100)
        self.assertEqual(self.conn.execute(
            'SELECT status FROM shipments WHERE buyer_enterprise_id=%s',
            (mill,)).fetchone()[0], 'delivered')
        self.assertEqual(self.conn.execute(
            'SELECT count(*) FROM shipments WHERE buyer_enterprise_id=%s',
            (mill,)).fetchone()[0], 1)
        self.assertTrue(reconcile(self.conn)['ok'])

    def test_insolvent_buyer_does_not_block_others(self):
        seller = self.owner()
        broke = self.owner(0)
        solvent = self.owner()
        field = self.enterprise(seller, 'field', stock=[('grain', 200, 50)])
        first = self.enterprise(broke, 'mill')
        second = self.enterprise(solvent, 'mill')
        self.link(first, 'grain', field)
        self.link(second, 'grain', field)
        supply.links_day(self.conn, self.day, FLAGS)
        supply.market_day(self.conn, self.day, FLAGS)
        self.assertEqual(self.qty(first, 'grain'), 0)
        self.assertEqual(self.qty(second, 'grain'), 100)
        self.assertEqual(self.balance(broke), 0)
        self.assertEqual(self.conn.execute(
            'SELECT unfilled FROM supply_daily_needs WHERE enterprise_id=%s',
            (first,)).fetchone()[0], 100)
        self.assertTrue(reconcile(self.conn)['ok'])

    def test_m1_field_mill_bakery_ten_days(self):
        owner = self.owner()
        field = self.enterprise(owner, 'field', recipe='field_grain')
        mill = self.enterprise(owner, 'mill', recipe='mill_flour')
        bakery = self.enterprise(owner, 'bakery', recipe='bakery_bread')
        self.link(mill, 'grain', field)
        self.link(bakery, 'flour', mill)
        for day in range(self.day, self.day + 10):
            self.run_day(day)
        self.assertGreaterEqual(self.qty(bakery, 'bread'), 700)
        self.assertEqual(self.qty(field, 'grain'), 100)
        self.assertTrue(reconcile(self.conn)['ok'])

    def test_two_hundred_links_benchmark_and_ledger(self):
        seller = self.owner()
        buyer = self.owner(10000000)
        suppliers = [
            self.enterprise(seller, 'field', stock=[('grain', 100, 50)])
            for _ in range(200)]
        customers = [self.enterprise(buyer, 'mill') for _ in range(67)]
        for index, supplier in enumerate(suppliers):
            self.link(customers[index // 3], 'grain', supplier,
                      slot=index % 3 + 1, priority=index % 3 + 1,
                      share=334 if index % 3 == 0 else 333)
        started = time.monotonic()
        supply.links_day(self.conn, self.day, FLAGS)
        supply.market_day(self.conn, self.day, FLAGS)
        duration = time.monotonic() - started
        self.assertEqual(self.conn.execute(
            'SELECT count(*) FROM supply_links').fetchone()[0], 200)
        self.assertTrue(reconcile(self.conn)['ok'])
        self.assertTrue(all(self.qty(e, 'grain') > 0 for e in customers[:66]))
        # Very generous CI watchdog, not a performance claim.
        self.assertLess(duration, 90, f'200-link clearing took {duration:.2f}s')
        print(f'V2-05 BENCHMARK: 200 links, {duration:.3f} s')
