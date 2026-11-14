"""Real PostgreSQL 16 integration tests; never run against a production database."""
import os
import time
import unittest
import uuid
from unittest.mock import patch

import postgres_db
import postgres_world


@unittest.skipUnless(
    os.environ.get("LUNEX_DB_ENGINE") == "postgres"
    and os.environ.get("LUNEX_PG_DB") == "lunex_ci",
    "requires isolated lunex_ci PostgreSQL database",
)
class PostgreSQLWorldTests(unittest.TestCase):
    def setUp(self):
        # The CI database is disposable and has no live player data.
        with postgres_db.connect() as db:
            db.execute(
                "TRUNCATE TABLE ledger_entries,ledger_tx,wallets,inventory,"
                "company_reports,monthly_reports,company_state,market_prices,"
                "building_ops,cells,roads,buildings,events,chunks,commands,"
                "world_state,world_clock RESTART IDENTITY CASCADE"
            )

    def test_build_persists_events_and_idempotent_charge(self):
        owner = "ci_" + uuid.uuid4().hex
        request_id = str(uuid.uuid4())
        payload = {"kind": "farm", "x": 8, "y": 10, "request_id": request_id}
        status, result = postgres_world.build(owner, payload)
        self.assertEqual(status, 201, result)
        self.assertTrue(result["ok"])
        self.assertGreater(result["cost"], 0)
        self.assertEqual(result["balance"], 1_000_000 - result["cost"])
        status2, repeated = postgres_world.build(owner, payload)
        self.assertEqual(status2, 200)
        self.assertEqual(repeated, result)
        self.assertEqual(postgres_world.wallet(owner)[1]["balance"], result["balance"])
        events = postgres_world.events(0)[1]["events"]
        self.assertTrue(any(e["kind"] == "building_created" for e in events))
        self.assertTrue(any(c["kind"] == "building_created" for c in postgres_world.chunk(0, 0)[1]["cells"]))
        with postgres_db.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM buildings").fetchone()[0], 1)
            self.assertFalse(db.execute("SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0").fetchall())
            self.assertEqual(db.execute("SELECT COALESCE(SUM(balance),0) FROM wallets").fetchone()[0], 0)

    def test_occupied_footprint_has_no_extra_charge(self):
        first = postgres_world.build("ci_alice", {"kind": "farm", "x": 8, "y": 10, "request_id": str(uuid.uuid4())})
        self.assertEqual(first[0], 201, first)
        second = postgres_world.build("ci_bob", {"kind": "farm", "x": 8, "y": 10, "request_id": str(uuid.uuid4())})
        self.assertEqual(second[0], 409, second)
        with postgres_db.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM buildings").fetchone()[0], 1)

    def test_market_clock_and_monthly_settlement(self):
        t0 = 1_800_000_000
        with patch.object(postgres_world.time, "time", return_value=t0):
            clock = postgres_world.clock_state()
            self.assertEqual(clock["month_seconds"], 86400)
            self.assertEqual(postgres_world.market_state()[0], 200)
            owner = "ci_month"
            result = postgres_world.build(owner, {"kind": "farm", "x": 8, "y": 10, "request_id": str(uuid.uuid4())})
            self.assertEqual(result[0], 201, result)
        with patch.object(postgres_world.time, "time", return_value=t0 + 86405):
            status, wallet = postgres_world.wallet(owner)
            self.assertEqual(status, 200, wallet)
            self.assertIn("balance", wallet)
            status, market = postgres_world.market_state()
            self.assertEqual(status, 200, market)
            self.assertIn("products", market)
            self.assertIn("honey", market["products"])
            with postgres_db.connect() as db:
                self.assertTrue(db.execute("SELECT 1 FROM market_prices LIMIT 1").fetchone())
                self.assertFalse(db.execute("SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0").fetchall())


if __name__ == "__main__":
    unittest.main()
