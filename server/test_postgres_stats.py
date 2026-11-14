"""Parity tests on disposable PostgreSQL 16; production database is forbidden."""
import os
import unittest

ENABLED = os.environ.get("LUNEX_DB_ENGINE") == "postgres" and os.environ.get("LUNEX_PG_DB") == "lunex_ci"
if ENABLED:
    import postgres_db
    import postgres_world
    import stats


@unittest.skipUnless(ENABLED, "requires isolated lunex_ci PostgreSQL database")
class StatsPostgreSQLTests(unittest.TestCase):
    def setUp(self):
        postgres_db.init()
        with postgres_db.connect() as db:
            db.execute("TRUNCATE TABLE ledger_entries,ledger_tx,company_taxes,company_reports,monthly_reports,"
                       "election_results,election_candidates,world_clock,building_ops,loans,wallets CASCADE")
            db.execute("INSERT INTO wallets VALUES('player:alice',200000),('player:bob',100000)")
            db.execute("INSERT INTO building_ops VALUES('b1','alice','mine',0,1000)")
            db.execute("INSERT INTO loans VALUES('alice',120000,0,0,0)")
            db.execute("INSERT INTO company_reports VALUES('alice',2,50000,0,0,40000,1)")
            db.execute("INSERT INTO world_clock VALUES(1,1800000000,86400,0)")

    def test_read_only_parity(self):
        with postgres_db.connect() as db:
            before = db.execute("SELECT COUNT(*) FROM ledger_tx").fetchone()[0]
            status, board = stats.leaderboard(db, "%s", "alice")
            self.assertEqual(status, 200)
            self.assertEqual(board["me"]["networth"], 380000)
            self.assertEqual(board["me"]["income"], 50000)
            code, feed = stats.feed(db, "%s", "alice")
            self.assertEqual(code, 200)
            self.assertIn("monthly_result", [item["kind"] for item in feed["events"]])
            self.assertEqual(before, db.execute("SELECT COUNT(*) FROM ledger_tx").fetchone()[0])

    def test_npc_names_and_buildings_sort(self):
        status, board = postgres_world.stats_leaderboard("alice", "buildings")
        self.assertEqual(status, 200)
        self.assertEqual(board["top"][0]["owner"], "alice")
        self.assertTrue(any(x["npc"] for x in board["top"]))
        self.assertEqual(postgres_world.stats_feed("alice")[0], 200)


if __name__ == "__main__":
    unittest.main()
