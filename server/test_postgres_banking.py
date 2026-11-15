"""NPC bank loan on disposable PostgreSQL 16 (lunex_ci). Does not use the legacy loans table."""
import os
import unittest
import uuid

import balance

ENABLED = os.environ.get("LUNEX_DB_ENGINE") == "postgres" and os.environ.get("LUNEX_PG_DB") == "lunex_ci"
if ENABLED:
    import banking
    import economy
    import postgres_db


@unittest.skipUnless(ENABLED, "requires isolated lunex_ci PostgreSQL database")
class PostgresBankingTests(unittest.TestCase):
    def setUp(self):
        postgres_db.init()
        with postgres_db.connect() as db:
            names = [r[0] for r in db.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'").fetchall()]
            keep = {"users", "sessions", "auth_attempts", "auth_tokens", "email_verified", "schema_migrations"}
            db.execute("TRUNCATE TABLE " + ",".join(sorted(n for n in names if n not in keep)) + " RESTART IDENTITY CASCADE")
        os.environ["LUNEX_BAL_BANKS_ENABLED"] = "1"
        balance.reload()
        self.addCleanup(self._off)

    def _off(self):
        os.environ.pop("LUNEX_BAL_BANKS_ENABLED", None)
        balance.reload()

    def test_share_purchase_balances_and_skips_the_legacy_table(self):
        request_id = str(uuid.uuid4())
        with postgres_db.connect() as db:
            banking.ensure(db, "%s")
            economy.ensure_wallet(db, "%s", "alice", 1)
            status, body = banking.buy_shares(db, "%s", "alice", {
                "company": "acme", "shares": 4, "price": 1000, "request_id": request_id}, 1, 0)
            again = banking.buy_shares(db, "%s", "alice", {
                "company": "acme", "shares": 4, "price": 1000, "request_id": request_id}, 1, 0)
            bad = db.execute("SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0").fetchall()
            total = db.execute("SELECT COALESCE(SUM(balance),0) FROM wallets").fetchone()[0]
            legacy = db.execute("SELECT COUNT(*) FROM loans").fetchone()[0]
            db.commit()
        self.assertEqual(status, 201, body)
        self.assertEqual(again[0], 200)
        self.assertEqual(bad, [])
        self.assertEqual(int(total), 0)
        self.assertEqual(int(legacy), 0)


if __name__ == "__main__":
    unittest.main()
