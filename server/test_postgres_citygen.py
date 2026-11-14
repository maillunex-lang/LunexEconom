"""Initial city generation on a disposable PostgreSQL 16 database named lunex_ci. Never point this at production."""
import os
import unittest

ENABLED = os.environ.get("LUNEX_DB_ENGINE") == "postgres" and os.environ.get("LUNEX_PG_DB") == "lunex_ci"

if ENABLED:
    import citygen
    import geo
    import postgres_db
    import postgres_world
    import production

NOW = 1_800_000_000


@unittest.skipUnless(ENABLED, "requires isolated lunex_ci PostgreSQL database")
class PostgresCityGenTests(unittest.TestCase):
    def setUp(self):
        postgres_db.init()
        with postgres_db.connect() as db:
            names = [r[0] for r in db.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'").fetchall()]
            keep = {"users", "sessions", "auth_attempts", "auth_tokens", "email_verified", "schema_migrations"}
            db.execute("TRUNCATE TABLE " + ",".join(sorted(n for n in names if n not in keep)) + " RESTART IDENTITY CASCADE")
            db.execute("INSERT INTO world_clock(id,epoch,month_seconds,base_index) VALUES(1,1800000000,86400,0)")

    def scalar(self, sql):
        with postgres_db.connect() as db:
            return db.execute(sql).fetchone()[0]

    def seed(self, ids, dry=False):
        with postgres_db.connect() as db:
            db.execute("SELECT pg_advisory_xact_lock(20261114)")
            return citygen.seed(db, "%s", ids, NOW, dry_run=dry)

    def test_dry_run_then_real_run_then_idempotent(self):
        dry = self.seed(["ufa"], dry=True)
        self.assertEqual(dry[0]["placed"], 25)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM buildings"), 0)
        self.assertEqual(self.seed(["ufa"])[0]["placed"], 25)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM buildings WHERE owner='town:ufa' AND kind='house'"), 25)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM cells"), 100)
        events = self.scalar("SELECT COUNT(*) FROM events WHERE kind='building_created'")
        self.assertEqual(self.seed(["ufa"])[0]["placed"], 0)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM events WHERE kind='building_created'"), events)

    def test_all_cities_leave_the_economy_untouched(self):
        result = self.seed("all")
        self.assertEqual(len(result), 20)
        self.assertEqual(sum(r["placed"] for r in result), self.scalar("SELECT COUNT(*) FROM buildings WHERE kind='house'"))
        for table in ("wallets", "ledger_tx", "ledger_entries", "building_ops"):
            self.assertEqual(self.scalar("SELECT COUNT(*) FROM " + table), 0, table)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM cells c LEFT JOIN buildings b ON b.id=c.object_id WHERE b.id IS NULL"), 0)

    def test_chunk_snapshot_carries_the_houses(self):
        self.seed(["ufa"])
        x, y = citygen.plan("ufa")[0]
        status, data = postgres_world.chunk(x // 12, y // 12)
        self.assertEqual(status, 200)
        self.assertIn(("house", "town:ufa"), {(c["building_kind"], c["owner"]) for c in data["cells"] if c["kind"] == "building_created"})

    def test_monthly_growth_after_generation(self):
        self.seed(["ufa"])
        with postgres_db.connect() as db:
            db.execute("SELECT pg_advisory_xact_lock(20261114)")
            db.execute("INSERT INTO population(month_index,population,labor_force,jobs,wage,staffing_permille,demand_permille,next_population) VALUES(0,200,100,0,1500,1000,1000,600)")
            production.step_month(db, "%s", 1, NOW)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM buildings WHERE owner='town:ufa'"), 25 + citygen.GROW_PER_MONTH)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM (SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0) x"), 0)

    def test_admin_route_on_postgres(self):
        ctx = {"actor": "pg-test", "ip": "198.51.100.1"}
        status, data = postgres_world.admin_request("POST", "/admin/cities/seed", {}, {"city_id": "ufa"}, ctx)
        self.assertEqual((status, data["dry_run"]), (200, True))
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM buildings"), 0)
        status, data = postgres_world.admin_request("POST", "/admin/cities/seed", {}, {"city_id": "ufa", "dry_run": False}, ctx)
        self.assertEqual((status, data["cities"][0]["placed"]), (200, 25))
        status, data = postgres_world.admin_request("GET", "/admin/cities", {}, {}, ctx)
        self.assertEqual(next(c for c in data["cities"] if c["city_id"] == "ufa")["houses"], 25)


if __name__ == "__main__":
    unittest.main()
