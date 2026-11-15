"""Key industry scenarios on disposable PostgreSQL 16 (lunex_ci): catalog chain and deposits."""
import os
import unittest
import uuid
from unittest import mock

DAY = 86400
T0 = 1_800_000_000
ENABLED = os.environ.get("LUNEX_DB_ENGINE") == "postgres" and os.environ.get("LUNEX_PG_DB") == "lunex_ci"

if ENABLED:
    import deposits
    import economy
    import game_server
    import postgres_db
    import postgres_world


def rid():
    return str(uuid.uuid4())


@unittest.skipUnless(ENABLED, "requires isolated lunex_ci PostgreSQL database")
class PostgresIndustryTests(unittest.TestCase):
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
        self.cursor = 0

    def build(self, who, kind, x=None, y=None):
        if x is None:
            for _ in range(400):
                self.cursor += 1
                status, res = postgres_world.build(who, {"kind": kind, "x": 8, "y": 10 + 7 * self.cursor, "request_id": rid()})
                if status == 201:
                    return res
                self.assertIn(res.get("error"), ("water", "road_overlap", "occupied", "no_road_access", "no_deposit"), res)
            self.fail("no free site for %s" % kind)
        status, res = postgres_world.build(who, {"kind": kind, "x": x, "y": y, "request_id": rid()})
        self.assertEqual(status, 201, res)
        return res

    def month(self, who="alice", n=1):
        self.now += DAY * n + 5
        return postgres_world.wallet(who)[1]

    def sql(self, query, params=()):
        with postgres_db.connect() as db:
            return db.execute(query, params).fetchall()

    def grant(self, who, amount):
        postgres_world.wallet(who)
        with postgres_db.connect() as db:
            db.execute("UPDATE wallets SET balance=balance+%s WHERE account=%s", (amount, economy.player_account(who)))
            db.execute("UPDATE wallets SET balance=balance-%s WHERE account=%s", (amount, economy.TREASURY))

    def test_catalog_kinds_match_and_deposits_are_created(self):
        self.assertEqual(set(postgres_world.KINDS), set(game_server.KINDS))
        self.assertIn("bread_plant", postgres_world.KINDS)
        with postgres_db.connect() as db:
            created = deposits.ensure(db, "%s")
        expected = 20 * sum(deposits.COUNTS.values())
        self.assertEqual(self.sql("SELECT COUNT(*) FROM deposits")[0][0], expected)
        self.assertEqual(created, expected)

    def test_agro_chain_sells_bread_and_balances(self):
        self.grant("alice", 500_000)
        for kind in ("grain_field", "elevator", "mill", "bread_plant", "shop"):
            self.build("alice", kind)
        wallet = self.month("alice")
        bread = self.sql("SELECT supply,price FROM market_prices WHERE product='bread' AND month_index=0")[0]
        grain = self.sql("SELECT supply FROM market_prices WHERE product='grain' AND month_index=0")[0][0]
        self.assertGreater(bread[0], 0)
        self.assertEqual(grain, 0)
        self.assertGreater(wallet["reports"][0]["revenue"], bread[0] * bread[1])
        self.assertEqual(wallet["reports"][0]["input_cost"], 0)
        bad = self.sql("SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0")
        total = self.sql("SELECT COALESCE(SUM(balance),0) FROM wallets")[0][0]
        self.assertEqual((bad, total), ([], 0))

    def test_well_on_deposit_depletes_legacy_mine_does_not(self):
        with postgres_db.connect() as db:
            deposits.ensure(db, "%s")
            x, y, dep_id = deposits.open_origins(db, "%s", "oil")[0]
            before_all = db.execute("SELECT COALESCE(SUM(remaining),0) FROM deposits").fetchone()[0]
        off = None
        for i in range(40):
            status, res = postgres_world.build("alice", {"kind": "oil_well", "x": 8, "y": 40 + 7 * i, "request_id": rid()})
            if res.get("error") == "no_deposit":
                off = res
                break
            if status == 201:
                postgres_world.sell("alice", {"object_id": res["object_id"], "request_id": rid()})
                continue
            self.assertIn(res.get("error"), ("water", "road_overlap", "occupied", "no_road_access"), res)
        self.assertEqual(off["error"], "no_deposit")
        well = self.build("alice", "oil_well", x, y)
        self.month("alice")
        left = self.sql("SELECT remaining FROM deposits WHERE id=%s", (dep_id,))[0][0]
        supply = self.sql("SELECT supply FROM market_prices WHERE product='oil' AND month_index=0")[0][0]
        self.assertEqual(deposits.INITIAL["oil"] - left, supply)
        self.assertGreater(supply, 0)
        self.build("bob", "mine")
        self.month("bob")
        left2 = self.sql("SELECT remaining FROM deposits WHERE id=%s", (dep_id,))[0][0]
        after = self.sql("SELECT COALESCE(SUM(remaining),0) FROM deposits")[0][0]
        self.assertEqual(before_all - after, deposits.INITIAL["oil"] - left2)
        self.assertLess(left2, left)
        self.assertNotEqual(well["object_id"], "")


if __name__ == "__main__":
    unittest.main()
