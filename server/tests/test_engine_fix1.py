"""V2-ENGINE-FIX1: supplier share remainders and staffing-scaled upkeep.

Unit tests run without a database. PostgreSQL tests use an isolated DSN and
roll every fixture back.
"""
import os
import unittest
from uuid import uuid4

from server import db
from server.game_server import build_registry, create_app
from server.enterprises import core as enterprises
from server.ledger.api import account, reconcile, transfer
from server.supply import core as supply
from server.world import core as world

DSN = os.getenv('LUNEX_TEST_DATABASE_URL')
FLAGS = {
    'supply_transport_rub_per_km_unit_draft': 1,
    'supply_port_city_draft': 'ufa',
    'supply_port_price_permille_draft': 1000,
    'supply_port_duty_bp_draft': 500,
    'supply_port_fallback_draft': False,
}


class SplitSharesUnitTests(unittest.TestCase):
    def test_three_suppliers_fifteen_units_no_loss(self):
        # Defect example: plain floors gave 5+4+4=13 of 15.
        self.assertEqual(supply.split_shares(15, [334, 333, 333]), [5, 5, 5])
        # 7.5/3.75/3.75: largest remainders win the two rounding units.
        self.assertEqual(supply.split_shares(15, [500, 250, 250]), [7, 4, 4])
        self.assertEqual(supply.split_shares(1, [334, 333, 333]), [1, 0, 0])
        self.assertEqual(supply.split_shares(2, [333, 333, 334]), [1, 0, 1])

    def test_sum_equals_need_for_full_share_sets(self):
        cases = ([1000], [500, 500], [334, 333, 333], [1, 999], [998, 1, 1],
                 [700, 200, 100], [333, 667], [100, 450, 450])
        for shares in cases:
            for needed in range(0, 260):
                quotas = supply.split_shares(needed, shares)
                self.assertEqual(sum(quotas), needed, (needed, shares))
                for quota, share in zip(quotas, shares):
                    # Every quota is floor or ceil of the exact share.
                    self.assertIn(quota * 1000 - needed * share,
                                  range(-999, 1000), (needed, shares))
                    self.assertGreaterEqual(quota, needed * share // 1000)

    def test_partial_share_sets_leave_market_remainder(self):
        # 800 permille of 15 is 12; the rest stays for the city market.
        self.assertEqual(supply.split_shares(15, [500, 300]), [8, 4])
        self.assertEqual(sum(supply.split_shares(15, [333, 333, 333])), 14)
        self.assertEqual(supply.split_shares(7, []), [])
        self.assertEqual(supply.split_shares(0, [334, 333, 333]), [0, 0, 0])

    def test_deterministic_ties_follow_link_order(self):
        for _ in range(3):
            self.assertEqual(supply.split_shares(4, [334, 333, 333]), [2, 1, 1])
            self.assertEqual(supply.split_shares(1, [500, 500]), [1, 0])
            self.assertEqual(supply.split_shares(2, [250, 250, 500]), [1, 0, 1])
            self.assertEqual(supply.split_shares(5, [200, 400, 400]), [1, 2, 2])

    def test_integer_only_validation(self):
        for bad in ((-1, [1000]), (1.5, [1000]), (True, [1000]),
                    (10, [1001]), (10, [-1]), (10, [0.5])):
            with self.assertRaises(ValueError):
                supply.split_shares(*bad)
        big = 2**40
        self.assertEqual(sum(supply.split_shares(big, [334, 333, 333])), big)


class UpkeepUnitTests(unittest.TestCase):
    def test_flag_off_is_previous_behaviour(self):
        for staff in (0, 1, 5000, 9999, 10000):
            for fixed in (0, 4000, 10000):
                self.assertEqual(
                    enterprises.monthly_upkeep(241300, staff, False, fixed),
                    241300)
        self.assertEqual(enterprises.monthly_upkeep(241300, 5000), 241300)

    def test_flag_on_with_default_fixed_share_is_unchanged(self):
        for staff in (0, 5000, 10000):
            self.assertEqual(
                enterprises.monthly_upkeep(241300, staff, True, 10000), 241300)

    def test_flag_on_scales_variable_part_floor(self):
        # fixed 60%: 600 always, variable 400 * 50% = 200.
        self.assertEqual(enterprises.monthly_upkeep(1000, 5000, True, 6000), 800)
        self.assertEqual(enterprises.monthly_upkeep(1000, 0, True, 6000), 600)
        self.assertEqual(enterprises.monthly_upkeep(1000, 10000, True, 6000), 1000)
        self.assertEqual(enterprises.monthly_upkeep(1000, 5000, True, 0), 500)
        # 7 * 3333 // 10000 = 2 (floor, payer keeps the fraction).
        self.assertEqual(enterprises.monthly_upkeep(7, 3333, True, 0), 2)
        self.assertEqual(enterprises.monthly_upkeep(0, 5000, True, 0), 0)

    def test_never_exceeds_catalog_upkeep_and_monotonic(self):
        for upkeep in (0, 1, 7, 999, 241300):
            for fixed in (0, 1, 3333, 9999, 10000):
                previous = -1
                for staff in range(0, 10001, 625):
                    due = enterprises.monthly_upkeep(upkeep, staff, True, fixed)
                    self.assertLessEqual(due, upkeep)
                    self.assertGreaterEqual(due, upkeep * fixed // 10000)
                    self.assertGreaterEqual(due, previous)
                    previous = due
                self.assertEqual(
                    enterprises.monthly_upkeep(upkeep, 10000, True, fixed), upkeep)

    def test_invalid_inputs_rejected(self):
        for args in ((-1, 5000, True, 0), (100, 10001, True, 0),
                     (100, 5000, True, 10001), (100.0, 5000, True, 0),
                     (100, -1, True, 0)):
            with self.assertRaises(ValueError):
                enterprises.monthly_upkeep(*args)

    def test_registry_defaults_keep_old_behaviour(self):
        registry = build_registry()
        self.assertIs(registry.flags['upkeep_scales_with_staffing'], False)
        self.assertEqual(registry.flags['enterprise_upkeep_fixed_bp_draft'], 10000)
        self.assertEqual(registry.flag_constraints['enterprise_upkeep_fixed_bp_draft'],
                         [0, 10000])


@unittest.skipUnless(DSN, 'Requires isolated PostgreSQL 16 test DSN')
class EngineFix1PostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app(DSN)

    @classmethod
    def tearDownClass(cls):
        cls.app.close()

    def setUp(self):
        self.conn = db.connect(DSN)
        self.serial = 0
        self.day = int(self.conn.execute(
            "SELECT GREATEST(COALESCE((SELECT max(day_index) FROM supply_receipts),-1),"
            " COALESCE((SELECT max(day_index) FROM game_ticks),-1))"
        ).fetchone()[0]) + 200
        self.treasury = account(self.conn, 'system:treasury')
        self.price = enterprises.catalog().index['products']['grain']['reference_price']

    def tearDown(self):
        self.conn.rollback()
        self.conn.close()

    # fixtures -----------------------------------------------------------
    def owner(self, money=1000000):
        name = 'ef' + uuid4().hex[:12]
        actor = self.conn.execute(
            """INSERT INTO accounts(username,email,password_hash,role)
            VALUES(%s,%s,'test-hash','player') RETURNING id""",
            (name, name + '@example.test')).fetchone()[0]
        wallet = account(self.conn, 'player:' + name, 'player', actor)
        capital = transfer(self.conn, 'fix1:fixture:' + uuid4().hex,
                           self.treasury, wallet, max(1, money))
        if money == 0:
            transfer(self.conn, 'fix1:empty:' + uuid4().hex,
                     wallet, self.treasury, 1)
        return {'id': actor, 'username': name, 'wallet': wallet,
                'capital': capital}

    def enterprise(self, owner, building, recipe, stock=(), upkeep=0, jobs=0,
                   staffing=10000, city='ufa'):
        self.serial += 1
        px = 910000000 + owner['id'] * 10000 + self.serial
        py = px
        self.conn.execute(
            """INSERT INTO world_parcels(px,py,city_id,owner_kind,owner_ref)
            VALUES(%s,%s,%s,'player',%s)""", (px, py, city, str(owner['id'])))
        coords = world.CITIES[city]
        eid = self.conn.execute(
            """INSERT INTO enterprises
            (owner_id,building_id,px,py,x,y,width,height,city_id,name,
             build_cost,build_days,upkeep_month,jobs,storage_capacity,
             started_day,stage,running,recipe_id,build_request_id,
             build_transfer_id,staffing_bp)
            VALUES(%s,%s,%s,%s,%s,%s,1,1,%s,'fix1 test',1,1,%s,%s,4000,
                   0,4,true,%s,%s,%s,%s) RETURNING id""",
            (owner['id'], building, px, py, coords['x'], coords['y'], city,
             upkeep, jobs, recipe, 'fix1:build:' + uuid4().hex,
             owner['capital'], staffing)).fetchone()[0]
        for product, amount, quality in stock:
            enterprises.adjust(self.conn, eid, product, amount, quality)
        return eid

    def publish(self, eid):
        self.conn.execute(
            """INSERT INTO supply_seller_policy
            (enterprise_id,allow_direct_sales,allow_city_market)
            VALUES(%s,true,false)""", (eid,))

    def link(self, buyer, source, slot, share, priority, cap=10**9, quality=0):
        self.conn.execute(
            """INSERT INTO supply_links
            (enterprise_id,product_id,slot,source_type,source_enterprise_id,
             share,priority,max_price,min_quality)
            VALUES(%s,'grain',%s,'enterprise',%s,%s,%s,%s,%s)""",
            (buyer, slot, source, share, priority, cap, quality))

    def qty(self, eid, product='grain'):
        return enterprises.stock(self.conn, eid).get(
            product, {'quantity': 0})['quantity']

    def balance(self, wallet):
        return self.conn.execute(
            'SELECT balance FROM ledger_accounts WHERE id=%s',
            (wallet,)).fetchone()[0]

    def need_row(self, eid):
        return self.conn.execute(
            """SELECT requested,linked,unfilled FROM supply_daily_needs
            WHERE enterprise_id=%s AND product_id='grain' AND day_index=%s""",
            (eid, self.day)).fetchone()

    def chain(self, stocks, shares=(334, 333, 333), caps=None, qualities=None):
        """Mill short of 15 grain, up to three foreign suppliers."""
        buyer = self.owner()
        mill = self.enterprise(buyer, 'mill', 'mill_flour',
                               stock=[('grain', 85, 50)])
        sellers, fields = [], []
        for index, (amount, share) in enumerate(zip(stocks, shares), 1):
            seller = self.owner()
            field = self.enterprise(
                seller, 'field', 'field_grain',
                stock=[('grain', amount, 50)] if amount else ())
            self.publish(field)
            self.link(mill, field, index, share, index,
                      cap=(caps or {}).get(index, 10**9),
                      quality=(qualities or {}).get(index, 0))
            sellers.append(seller)
            fields.append(field)
        return buyer, mill, sellers, fields

    # supply ------------------------------------------------------------
    def test_three_suppliers_deliver_full_need_and_balance_ledger(self):
        buyer, mill, sellers, fields = self.chain([100, 100, 100])
        before = self.balance(buyer['wallet'])
        supply.links_day(self.conn, self.day, FLAGS)
        self.assertEqual(self.need_row(mill), (15, 15, 0))
        self.assertEqual(self.qty(mill), 100)
        self.assertEqual([self.qty(f) for f in fields], [95, 95, 95])
        paid = before - self.balance(buyer['wallet'])
        self.assertEqual(paid, 15 * self.price)
        self.assertEqual(sum(self.balance(s['wallet']) - 1000000 for s in sellers),
                         15 * self.price)
        self.assertTrue(reconcile(self.conn)['ok'])

    def test_shortfall_moves_to_other_suppliers_by_priority(self):
        # Priority 1 has only 2 of its 5; priorities 2 and 3 cover 3 more,
        # priority 2 first and up to its own stock (6), then priority 3.
        buyer, mill, _, fields = self.chain([2, 6, 100])
        supply.links_day(self.conn, self.day, FLAGS)
        self.assertEqual(self.need_row(mill), (15, 15, 0))
        self.assertEqual([self.qty(f) for f in fields], [0, 0, 93])
        self.assertTrue(all(self.qty(f) >= 0 for f in fields))
        self.assertTrue(reconcile(self.conn)['ok'])

    def test_insufficient_total_stock_never_overdraws_suppliers(self):
        buyer, mill, _, fields = self.chain([3, 0, 4])
        supply.links_day(self.conn, self.day, FLAGS)
        self.assertEqual(self.need_row(mill), (15, 7, 8))
        self.assertEqual([self.qty(f) for f in fields], [0, 0, 0])
        self.assertEqual(self.qty(mill), 92)
        negative = self.conn.execute(
            'SELECT count(*) FROM enterprise_inventory WHERE quantity<0'
        ).fetchone()[0]
        self.assertEqual(negative, 0)
        self.assertTrue(reconcile(self.conn)['ok'])

    def test_price_and_quality_rejections_are_covered_by_others(self):
        # Link 1 caps price below reference, link 2 needs higher quality.
        buyer, mill, _, fields = self.chain(
            [100, 100, 100], caps={1: self.price - 1}, qualities={2: 90})
        supply.links_day(self.conn, self.day, FLAGS)
        self.assertEqual(self.need_row(mill), (15, 15, 0))
        self.assertEqual([self.qty(f) for f in fields], [100, 100, 85])

    def test_partial_share_set_leaves_market_part_unfilled(self):
        # 500+300 permille of 15 is 12 linked; 3 stay for the market phase.
        buyer, mill, _, fields = self.chain([100, 1], shares=(500, 300))
        supply.links_day(self.conn, self.day, FLAGS)
        self.assertEqual(self.need_row(mill), (15, 12, 3))
        self.assertEqual([self.qty(f) for f in fields], [89, 0])

    def test_repeat_day_is_idempotent_with_unique_request_ids(self):
        buyer, mill, _, fields = self.chain([2, 6, 100])
        supply.links_day(self.conn, self.day, FLAGS)
        keys = [r[0] for r in self.conn.execute(
            'SELECT request_id FROM shipments WHERE buyer_enterprise_id=%s',
            (mill,)).fetchall()]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(len(keys), 5)  # three quotas plus two redistributions
        transfers = self.conn.execute(
            'SELECT count(*) FROM ledger_transfers').fetchone()[0]
        wallet = self.balance(buyer['wallet'])
        supply.links_day(self.conn, self.day, FLAGS)
        self.assertEqual(self.conn.execute(
            'SELECT count(*) FROM ledger_transfers').fetchone()[0], transfers)
        self.assertEqual(self.balance(buyer['wallet']), wallet)
        self.assertEqual(self.qty(mill), 100)
        self.assertTrue(reconcile(self.conn)['ok'])

    # upkeep ------------------------------------------------------------
    def month(self):
        return int(self.conn.execute(
            'SELECT COALESCE(max(last_month),0) FROM enterprises').fetchone()[0]) + 50

    def upkeep_case(self, staffing, **flags):
        owner = self.owner(100000)
        eid = self.enterprise(owner, 'field', 'field_grain',
                              upkeep=1000, jobs=2, staffing=staffing)
        sink = account(self.conn, 'system:upkeep')
        month = self.month()
        enterprises.close_month(self.conn, month, 100, 1, **flags)
        paid = 100000 - self.balance(owner['wallet'])
        # Exactly the payer's debit reaches system:upkeep in one journal.
        credited = self.conn.execute(
            'SELECT COALESCE(sum(e.amount),0) FROM ledger_entries e '
            'JOIN ledger_transfers t ON t.id=e.transfer_id '
            'WHERE t.request_id=%s AND e.account_id=%s',
            (f'enterprise:upkeep:{eid}:{month}', sink)).fetchone()[0]
        self.assertEqual(int(credited), paid)
        report = self.conn.execute(
            'SELECT expenses FROM enterprise_month_reports '
            'WHERE enterprise_id=%s AND month_index=%s', (eid, month)).fetchone()[0]
        self.assertEqual(report, paid)
        return owner, eid, month, paid

    def test_upkeep_flag_off_keeps_full_upkeep_at_half_staff(self):
        # Salary 2*100*50% = 100, upkeep 1000 unchanged.
        _, _, _, paid = self.upkeep_case(5000)
        self.assertEqual(paid, 1100)
        _, _, _, paid = self.upkeep_case(
            5000, upkeep_scales_with_staffing=False, upkeep_fixed_bp=0)
        self.assertEqual(paid, 1100)
        _, _, _, paid = self.upkeep_case(
            5000, upkeep_scales_with_staffing=True, upkeep_fixed_bp=10000)
        self.assertEqual(paid, 1100)
        self.assertTrue(reconcile(self.conn)['ok'])

    def test_upkeep_flag_on_scales_with_staffing_and_is_idempotent(self):
        owner, eid, month, paid = self.upkeep_case(
            5000, upkeep_scales_with_staffing=True, upkeep_fixed_bp=6000)
        self.assertEqual(paid, 600 + 200 + 100)
        enterprises.close_month(self.conn, month, 100, 1,
                                upkeep_scales_with_staffing=True,
                                upkeep_fixed_bp=6000)
        self.assertEqual(100000 - self.balance(owner['wallet']), paid)
        self.assertEqual(self.conn.execute(
            'SELECT count(*) FROM ledger_transfers WHERE request_id=%s',
            (f'enterprise:upkeep:{eid}:{month}',)).fetchone()[0], 1)
        _, _, _, paid = self.upkeep_case(
            0, upkeep_scales_with_staffing=True, upkeep_fixed_bp=6000)
        self.assertEqual(paid, 600)
        # Global staffing draft caps effective staffing as in production.
        _, _, _, paid = self.upkeep_case(
            10000, upkeep_scales_with_staffing=True, upkeep_fixed_bp=0,
            default_staffing_bp=2500)
        self.assertEqual(paid, 250 + 200)
        self.assertTrue(reconcile(self.conn)['ok'])

    def test_upkeep_arrears_use_scaled_amount(self):
        owner = self.owner(0)
        eid = self.enterprise(owner, 'field', 'field_grain',
                              upkeep=1000, jobs=0, staffing=5000)
        month = self.month()
        enterprises.close_month(self.conn, month, 100, 1,
                                upkeep_scales_with_staffing=True,
                                upkeep_fixed_bp=6000)
        self.assertEqual(self.balance(owner['wallet']), 0)
        self.assertEqual(self.conn.execute(
            'SELECT amount FROM enterprise_arrears WHERE enterprise_id=%s',
            (eid,)).fetchone()[0], 800)
        with self.assertRaises(ValueError):
            enterprises.close_month(self.conn, month + 1, 100, 1,
                                    upkeep_scales_with_staffing=1)
        self.assertTrue(reconcile(self.conn)['ok'])


if __name__ == '__main__':
    unittest.main()
