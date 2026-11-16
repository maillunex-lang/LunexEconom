"""City gas utility integration on a dedicated PostgreSQL 16 test database."""
import os
import unittest

from server.game_server import build_registry
from server.ledger.api import reconcile
from server.market import city_gas
from server.platform.settings import read_settings
from server.tests.test_supply_postgres import SupplyPostgresTests

DSN = os.getenv('LUNEX_TEST_DATABASE_URL')


@unittest.skipUnless(DSN, 'Requires isolated PostgreSQL 16 test DSN')
class CityGasTests(SupplyPostgresTests):
    def setUp(self):
        super().setUp()
        self.registry = build_registry()
        self.gas_tick = next(fn for _, name, fn in
                             self.registry.tick_handlers['daily']
                             if name == 'city_gas')
        self.city = 'ufa'
        self.conn.execute('UPDATE world_cities SET population=0')
        self.conn.execute(
            'UPDATE world_cities SET population=1150000 WHERE id=%s',
            (self.city,))

    def seller(self, amount=200, owner=None, city='ufa'):
        owner = owner or self.owner(1)
        eid = self.enterprise(owner, 'gas_well', recipe='gas_well_gas',
                              city=city, stock=[('gas', amount, 50)] if amount else [])
        return owner, eid

    def result(self, city='ufa'):
        return next(row for row in city_gas.report(self.conn, self.day)
                    if row['city_id'] == city)

    def run_tick(self, enabled):
        from psycopg.types.json import Jsonb
        self.conn.execute(
            """INSERT INTO runtime_config(key,value) VALUES('city_gas_utility',%s)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
            (Jsonb(enabled),))
        self.gas_tick(self.conn, self.day)

    def test_flag_default_and_order(self):
        self.assertEqual(self.registry.flags['city_gas_utility'], 0)
        self.assertEqual(self.registry.flag_constraints['city_gas_utility'], [0, 1])
        self.assertEqual(
            [name for _, name, _ in sorted(self.registry.tick_handlers['daily'])
             if name in ('supply_market', 'city_gas', 'enterprise_production')],
            ['supply_market', 'city_gas', 'enterprise_production'])
        self.assertEqual(read_settings(self.conn, self.registry.flags,
                                       self.registry.flag_constraints)['city_gas_utility'], 0)
        self.assertEqual(city_gas.required_gas(1150000), 115)
        self.assertEqual(city_gas.required_gas(1), 1)
        self.assertEqual(city_gas.required_gas(0), 0)
        with self.assertRaises(ValueError):
            city_gas.required_gas(1.5)

    def test_disabled_is_noop(self):
        owner, eid = self.seller()
        before = self.balance(owner)
        self.run_tick(0)
        self.assertEqual(self.qty(eid, 'gas'), 200)
        self.assertEqual(self.balance(owner), before)
        self.assertEqual(city_gas.report(self.conn, self.day), [])
        self.assertEqual(self.conn.execute(
            "SELECT count(*) FROM ledger_transfers WHERE request_id LIKE 'city_gas:%'"
        ).fetchone()[0], 0)

    def test_gdd_quantity_and_market_price_and_reconcile(self):
        owner, eid = self.seller()
        self.conn.execute("""INSERT INTO market_prices
            (city_id,product_id,day_index,price,demand,supply,volume)
            VALUES(%s,'gas',%s,53,0,200,0)""", (self.city, self.day))
        before = self.balance(owner)
        self.run_tick(1)
        row = self.result()
        self.assertEqual((row['needed_m3'], row['bought_m3'],
                          row['spent_rub'], row['short_m3'], row['seller_enterprise_id']),
                         (115, 115, 115 * 53, 0, eid))
        self.assertEqual(self.qty(eid, 'gas'), 85)
        self.assertEqual(self.balance(owner), before + 115 * 53)
        self.assertEqual(self.conn.execute(
            "SELECT sum(amount) FROM ledger_entries e JOIN ledger_transfers t ON e.transfer_id=t.id "
            "WHERE t.request_id=%s", (f'city_gas:ufa:{self.day}:{eid}',)
        ).fetchone()[0], 0)
        self.assertTrue(reconcile(self.conn)['ok'])

    def test_minimum_one_and_reference_fallback(self):
        self.conn.execute("UPDATE world_cities SET population=1 WHERE id='ufa'")
        owner, eid = self.seller(amount=2)
        self.run_tick(1)
        self.assertEqual((self.result()['needed_m3'], self.result()['bought_m3'],
                          self.result()['spent_rub']),
                         (1, 1, 40))
        self.assertEqual(self.qty(eid, 'gas'), 1)

    def test_short_supply_and_no_second_purchase(self):
        owner, eid = self.seller(amount=25)
        self.run_tick(1)
        self.assertEqual((self.result()['bought_m3'], self.result()['short_m3'],
                          self.result()['spent_rub']), (25, 90, 1000))
        self.assertEqual(self.qty(eid, 'gas'), 0)
        self.run_tick(1)
        self.assertEqual(self.qty(eid, 'gas'), 0)
        self.assertEqual(self.conn.execute(
            "SELECT count(*) FROM ledger_transfers WHERE request_id=%s",
            (f'city_gas:ufa:{self.day}:{eid}',)
        ).fetchone()[0], 1)
        self.assertTrue(reconcile(self.conn)['ok'])

    def test_no_producer_and_zero_population(self):
        self.run_tick(1)
        self.assertEqual((self.result()['needed_m3'], self.result()['bought_m3'],
                          self.result()['short_m3'], self.result()['spent_rub']),
                         (115, 0, 115, 0))
        self.assertEqual((self.result('sterlitamak')['needed_m3'],
                          self.result('sterlitamak')['short_m3']), (0, 0))
        self.assertEqual(self.conn.execute(
            "SELECT count(*) FROM ledger_transfers WHERE request_id LIKE 'city_gas:%'"
        ).fetchone()[0], 0)
        self.assertTrue(reconcile(self.conn)['ok'])

    def test_deterministic_seller_selection(self):
        first_owner, first_eid = self.seller(amount=10)
        other_owner, other_eid = self.seller(amount=300)
        self.assertLess(first_eid, other_eid)
        self.run_tick(1)
        self.assertEqual(self.result()['seller_enterprise_id'], first_eid)
        self.assertEqual(self.qty(first_eid, 'gas'), 0)
        self.assertEqual(self.qty(other_eid, 'gas'), 300)
        self.assertEqual((self.result()['bought_m3'], self.result()['short_m3']), (10, 105))
        self.assertTrue(reconcile(self.conn)['ok'])

    def test_empty_first_producer_skipped(self):
        _, empty = self.seller(amount=0)
        _, filled = self.seller(amount=140)
        self.run_tick(1)
        self.assertEqual(self.qty(empty, 'gas'), 0)
        self.assertEqual(self.qty(filled, 'gas'), 25)
        self.assertEqual(self.result()['bought_m3'], 115)

    def test_wrong_flag_rejected(self):
        from server.platform.settings import validate
        for invalid in (-1, 2, False, 1.5):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                validate('city_gas_utility', invalid, self.registry.flags,
                         self.registry.flag_constraints)
