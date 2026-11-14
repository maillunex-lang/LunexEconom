"""City economies and inter-city shipments on the disposable PostgreSQL 16 database lunex_ci (docs/CITY_ECONOMY.md)."""
import os
import unittest
import uuid
from unittest import mock

ENABLED = os.environ.get("LUNEX_DB_ENGINE") == "postgres" and os.environ.get("LUNEX_PG_DB") == "lunex_ci"

if ENABLED:
    import economy
    import game_server
    import postgres_db
    import postgres_world
    import regions

DAY = 86400
T0 = 1_800_000_000


@unittest.skipUnless(ENABLED, "requires isolated lunex_ci PostgreSQL database")
class PostgresRegionTests(unittest.TestCase):
    def setUp(self):
        postgres_db.init()
        with postgres_db.connect() as db:
            names = [r[0] for r in db.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'").fetchall()]
            keep = {"users", "sessions", "auth_attempts", "auth_tokens", "email_verified", "schema_migrations"}
            db.execute("TRUNCATE TABLE " + ",".join(sorted(n for n in names if n not in keep)) + " RESTART IDENTITY CASCADE")
        self.now = T0
        p = mock.patch.object(game_server.time, "time", side_effect=lambda: self.now)
        p.start()
        self.addCleanup(p.stop)
        self.cursor = {}

    def build(self, who, kind, cx, cy):
        for _ in range(400):
            n = self.cursor.get((cx, cy), 0)
            self.cursor[(cx, cy)] = n + 1
            status, _ = postgres_world.build(who, {"kind": kind, "x": cx + 9 * (n % 8), "y": cy + 7 * (n // 8), "request_id": str(uuid.uuid4())})
            if status == 201:
                return
        self.fail("no site")

    def rich(self, who):
        postgres_world.wallet(who)
        with postgres_db.connect() as db:
            db.execute("UPDATE wallets SET balance=%s WHERE account=%s", (50_000_000, economy.player_account(who)))
            db.execute("UPDATE wallets SET balance=balance-%s WHERE account=%s", (49_000_000, economy.TREASURY))

    def test_shipments_arrive_after_the_transit_time(self):
        self.rich("alice")
        self.rich("bob")
        for _ in range(6):
            self.build("alice", "farm", -3, 380)
        self.build("bob", "mine", 8, 10)
        self.build("bob", "factory", 8, 60)
        self.now += 8 * DAY + 5
        postgres_world.wallet("alice")
        with postgres_db.connect() as db:
            ships = db.execute("SELECT origin,destination,depart_month,arrive_month FROM trade_shipments").fetchall()
            bad = db.execute("SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0").fetchall()
            pops = db.execute("SELECT COUNT(*) FROM region_population WHERE region='sterlitamak'").fetchone()[0]
            view = regions.overview(db, "%s")
        self.assertTrue(ships)
        for origin, destination, depart, arrive in ships:
            self.assertEqual((origin, destination), ("sterlitamak", "ufa"))
            self.assertEqual(arrive - depart, regions.transit_months("sterlitamak", "ufa"))
        self.assertEqual(bad, [])
        self.assertGreater(pops, 0)
        self.assertIn("sterlitamak", [c["id"] for c in view["cities"]])


if __name__ == "__main__":
    unittest.main()
