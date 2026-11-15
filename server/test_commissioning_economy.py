"""Commissioning regression tests with realistic staging (not fast legacy fixtures)."""
import os
import tempfile
import unittest
import uuid
from unittest import mock

import game_server
import economy

T0 = 1_800_000_000
MONTH = 86400
STEP = 8400


class CommissioningEconomyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = game_server.DB
        game_server.DB = os.path.join(self.tmp.name, 'world.sqlite3')
        self.now = T0
        patch_time = mock.patch.object(game_server.time, 'time', side_effect=lambda: self.now)
        patch_time.start()
        self.addCleanup(patch_time.stop)
        patch_env = mock.patch.dict(os.environ, {
            'LUNEX_CONSTRUCTION_STEP_SECONDS': str(STEP),
            'LUNEX_MONTH_SECONDS': str(MONTH),
        })
        patch_env.start()
        self.addCleanup(patch_env.stop)

    def tearDown(self):
        game_server.DB = self.old
        self.tmp.cleanup()

    def build(self):
        status, data = game_server.build('alice', {'kind':'farm', 'x':8,'y':10,'request_id':str(uuid.uuid4())})
        self.assertEqual(status, 201, data)
        return data['object_id']

    def test_production_starts_at_commissioning_not_purchase(self):
        oid = self.build()
        with game_server.connect() as db:
            month, permille = db.execute('SELECT start_month,start_permille FROM building_ops WHERE object_id=?', (oid,)).fetchone()
            self.assertEqual(month, 0)
            self.assertEqual(permille, STEP * 2 * 1000 // MONTH)
            self.assertEqual(db.execute('SELECT stage FROM construction_stages WHERE object_id=?', (oid,)).fetchone()[0], 'foundation')
        self.now += STEP
        game_server.wallet('alice')
        with game_server.connect() as db:
            self.assertEqual(db.execute('SELECT stage FROM construction_stages WHERE object_id=?', (oid,)).fetchone()[0], 'frame')
        self.now += STEP
        game_server.wallet('alice')
        with game_server.connect() as db:
            self.assertEqual(db.execute('SELECT stage FROM construction_stages WHERE object_id=?', (oid,)).fetchone()[0], 'complete')
        self.now = T0 + MONTH + 5
        game_server.wallet('alice')
        with game_server.connect() as db:
            row=db.execute("SELECT supply FROM market_prices WHERE product='honey' AND month_index=0").fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], economy.PRODUCTION["farm"]["output"] * (1000 - permille) // 1000)
            bad=db.execute('SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount) <> 0').fetchall()
            self.assertEqual(bad, [])

    def test_late_construction_does_not_produce_before_completion_month(self):
        game_server.clock_state()
        self.now = T0 + MONTH - 6000
        oid=self.build()
        with game_server.connect() as db:
            start_month, permille=db.execute('SELECT start_month,start_permille FROM building_ops WHERE object_id=?', (oid,)).fetchone()
            self.assertEqual(start_month, 1)
            self.assertGreater(permille, 0)
        self.now = T0 + MONTH + 5
        game_server.wallet('alice')
        with game_server.connect() as db:
            self.assertEqual(db.execute("SELECT supply FROM market_prices WHERE product='honey' AND month_index=0").fetchone(), (0,))
            self.assertEqual(db.execute('SELECT stage FROM construction_stages WHERE object_id=?', (oid,)).fetchone()[0], 'foundation')
        self.now = T0 + 2 * MONTH + 5
        game_server.wallet('alice')
        with game_server.connect() as db:
            supply=db.execute("SELECT supply FROM market_prices WHERE product='honey' AND month_index=1").fetchone()
            self.assertIsNotNone(supply)
            self.assertGreater(supply[0], 0)
            self.assertEqual(db.execute('SELECT stage FROM construction_stages WHERE object_id=?', (oid,)).fetchone()[0], 'complete')

    def test_company_forecast_and_jobs_stay_inactive_until_commissioned(self):
        oid=self.build()
        pending=game_server.wallet('alice')[1]
        self.assertEqual(pending['labor']['jobs'], 0)
        self.assertEqual(pending['market']['honey']['supply'], 0)
        self.assertEqual(pending['forecast']['buildings'], 0)
        self.now = T0 + 2*STEP
        active=game_server.wallet('alice')[1]
        self.assertGreater(active['labor']['jobs'], 0)
        self.assertGreater(active['market']['honey']['supply'], 0)
        self.assertEqual(active['forecast']['buildings'], 1)
        with game_server.connect() as db:
            self.assertEqual(db.execute('SELECT stage FROM construction_stages WHERE object_id=?',(oid,)).fetchone()[0], 'complete')