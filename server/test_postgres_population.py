"""Households on disposable PostgreSQL 16 (lunex_ci)."""
import os
import unittest

import balance

ENABLED = os.environ.get("LUNEX_DB_ENGINE") == "postgres" and os.environ.get("LUNEX_PG_DB") == "lunex_ci"
if ENABLED:
    import households
    import postgres_db


@unittest.skipUnless(ENABLED, "requires isolated lunex_ci PostgreSQL database")
class PostgresPopulationTests(unittest.TestCase):
    def setUp(self):
        postgres_db.init()
        with postgres_db.connect() as db:
            names = [r[0] for r in db.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'").fetchall()]
            keep = {"users", "sessions", "auth_attempts", "auth_tokens", "email_verified", "schema_migrations"}
            db.execute("TRUNCATE TABLE " + ",".join(sorted(n for n in names if n not in keep)) + " RESTART IDENTITY CASCADE")
        os.environ["LUNEX_BAL_HOUSEHOLDS_ENABLED"] = "1"
        balance.reload()
        self.addCleanup(self._off)

    def _off(self):
        os.environ.pop("LUNEX_BAL_HOUSEHOLDS_ENABLED", None)
        balance.reload()

    def test_month_is_idempotent_and_keeps_twenty_cities(self):
        with postgres_db.connect() as db:
            households.ensure(db, "%s")
            households.monthly(db, "%s", 0, 1)
            households.monthly(db, "%s", 0, 1)
            count = db.execute("SELECT COUNT(*) FROM household_cities").fetchone()[0]
            months = db.execute("SELECT COUNT(*) FROM household_months").fetchone()[0]
            flows = db.execute("SELECT COALESCE(SUM(migrants_in),0), COALESCE(SUM(migrants_out),0) FROM household_cities").fetchone()
            db.commit()
        self.assertEqual(count, 20)
        self.assertEqual(months, 1)
        self.assertEqual(int(flows[0]), int(flows[1]))


if __name__ == "__main__":
    unittest.main()
