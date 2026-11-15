"""Lorries, research and a cement chain on disposable PostgreSQL 16 (lunex_ci)."""
import os
import unittest
import uuid
from unittest import mock

DAY = 86400
T0 = 1_800_000_000
ENABLED = os.environ.get("LUNEX_DB_ENGINE") == "postgres" and os.environ.get("LUNEX_PG_DB") == "lunex_ci"

if ENABLED:
    import economy
    import game_server
    import goods_catalog
    import postgres_db
    import postgres_world
    import quality


def rid():
    return str(uuid.uuid4())


@unittest.skipUnless(ENABLED, "requires isolated lunex_ci PostgreSQL database")
class PostgresExpansionTests(unittest.TestCase):
    def setUp(self):
        postgres_db.init()
        with postgres_db.connect() as db:
            names = [r[0] for r in db.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'").fetchall()]
            keep = {"users", "sessions", "auth_attempts", "auth_tokens", "email_verified", "schema_migrations"}
            db.execute("TRUNCATE TABLE " + ",".join(sorted(n for n in names if n not in keep)) + " RESTART IDENTITY CASCADE")
        self.now = T0
        patch = mock.patch.object(game_server.time, "time", side_effect=lambda: self.now)
        patch.start()
        self.addCleanup(patch.stop)

    def sql(self, query, params=()):
        with postgres_db.connect() as db:
            return db.execute(query, params).fetchall()

    def test_truck_research_and_cement_keep_the_ledger(self):
        self.assertIn("company_trucks", {r[0] for r in self.sql("SELECT tablename FROM pg_tables WHERE schemaname='public'")})
        status, body = game_server.trucks_buy("alice", {"count": 1, "request_id": rid()})
        self.assertEqual(status, 201, body)
        self.assertEqual(body["capacity_each"], balance_cap())
        status, body = game_server.research_start("alice", {"track": "thrift", "request_id": rid()})
        self.assertEqual(status, 201, body)
        import deposits
        with postgres_db.connect() as db:
            deposits.ensure(db, "%s")
            stone = deposits.open_origins(db, "%s", "stone")
            gas = deposits.open_origins(db, "%s", "gas")
        self.assertTrue(stone and gas)
        region = None
        import regions
        sx, sy = stone[0][0], stone[0][1]
        region = regions.region_of(sx, sy)
        gas_site = next((item for item in gas if regions.region_of(item[0], item[1]) == region), gas[0])
        status, _res = postgres_world.build("alice", {"kind": "stone_pit", "x": sx, "y": sy, "request_id": rid()})
        self.assertEqual(status, 201, _res)
        status, _res = postgres_world.build("alice", {"kind": "gas_well", "x": gas_site[0], "y": gas_site[1], "request_id": rid()})
        self.assertEqual(status, 201, _res)
        placed = False
        for i in range(40):
            status, res = postgres_world.build("alice", {"kind": "cement_plant", "x": sx + 4, "y": sy + 4 * i, "request_id": rid()})
            if status == 201:
                placed = True
                break
            self.assertIn(res.get("error"), ("water", "road_overlap", "occupied", "no_road_access", "insufficient_funds"), res)
            if status == 402:
                break
        self.assertTrue(placed)
        self.now += DAY + 5
        postgres_world.wallet("alice")
        cement = self.sql("SELECT supply, price FROM market_prices WHERE product='cement' AND month_index=0")
        self.assertTrue(cement and cement[0][0] > 0)
        bad = self.sql("SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0")
        total = self.sql("SELECT COALESCE(SUM(balance),0) FROM wallets")[0][0]
        self.assertEqual(bad, [])
        self.assertEqual(int(total), 0)
        self.assertEqual(quality.score(1, 3, 0), 3)
        self.assertIn("cement", {g.id for g in goods_catalog.GOODS})


def balance_cap():
    import balance
    return balance.DEFAULTS["TRUCK_CAPACITY"]


if __name__ == "__main__":
    unittest.main()
