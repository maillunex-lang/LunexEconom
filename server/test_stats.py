"""Disposable SQLite tests for the read-only company statistics API."""
import os
import tempfile
import unittest
from unittest import mock

import economy
import game_server
import stats


class StatsSQLiteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original = game_server.DB
        game_server.DB = os.path.join(self.tmp.name, "stats.sqlite3")
        with game_server.connect() as db:
            db.execute("INSERT INTO wallets VALUES('player:alice',100000)")
            db.execute("INSERT INTO wallets VALUES('player:bob',400000)")
            db.execute("INSERT INTO wallets VALUES('player:npc:ural-agro',200000)")
            db.execute("INSERT INTO building_ops VALUES('b1','alice','farm',0,1000)")
            db.execute("INSERT INTO building_ops VALUES('b2','alice','mine',0,1000)")
            db.execute("INSERT INTO building_ops VALUES('b3','bob','farm',0,1000)")
            db.execute("INSERT INTO loans VALUES('alice',300000,0,0,0)")
            db.execute("INSERT INTO company_reports VALUES('alice',1,25000,0,0,5000,2)")
            db.execute("INSERT INTO company_reports VALUES('alice',2,70000,0,0,30000,2)")
            db.execute("INSERT INTO company_reports VALUES('bob',2,90000,0,0,20000,1)")
            db.execute("INSERT INTO monthly_reports VALUES('alice',3,11111,0,9000,1)")
            db.execute("INSERT INTO world_clock VALUES(1,1800000000,86400,0)")

    def tearDown(self):
        game_server.DB = self.original
        self.tmp.cleanup()

    def snapshot(self):
        with game_server.connect() as db:
            return {table: db.execute("SELECT * FROM " + table + " ORDER BY 1").fetchall()
                    for table in ("wallets", "loans", "building_ops", "company_reports", "ledger_tx")}

    def test_networth_and_npc_identity(self):
        status, data = game_server.stats_leaderboard("alice")
        self.assertEqual(status, 200)
        me = data["me"]
        self.assertEqual(me["networth"], 220000)
        self.assertEqual(me["appraisal"], 420000)
        self.assertEqual(me["debt"], 300000)
        self.assertEqual(me["buildings"], 2)
        self.assertEqual(data["top"][0]["owner"], "bob")
        self.assertEqual(next(x["name"] for x in data["top"] if x["owner"] == "npc:ural-agro"), "Урал-Агро")
        self.assertNotIn("email", repr(data))

    def test_income_and_buildings_sorts(self):
        _, income = game_server.stats_leaderboard("alice", "income")
        self.assertEqual(income["me"]["income"], 70000)
        self.assertEqual(income["me"]["profit"], 30000)
        self.assertEqual(income["top"][0]["owner"], "bob")
        _, buildings = game_server.stats_leaderboard("alice", "buildings")
        self.assertEqual(buildings["top"][0]["owner"], "alice")

    def test_me_beyond_top_twenty_and_no_wallet_creation(self):
        with game_server.connect() as db:
            for i in range(22):
                db.execute("INSERT INTO wallets VALUES(?,?)", (f"player:p{i:02d}", 10_000_000 - i))
        _, data = game_server.stats_leaderboard("alice")
        self.assertEqual(len(data["top"]), 20)
        self.assertGreater(data["me"]["rank"], 20)
        before = self.snapshot()
        _, empty = game_server.stats_leaderboard("newcomer")
        self.assertEqual(empty["me"]["balance"], 0)
        self.assertEqual(before, self.snapshot())

    def test_feed_private_sources_and_pagination(self):
        with game_server.connect() as db:
            economy.post(db, "?", "build", "Строительство: farm",
                         [(economy.player_account("alice"), -10_000), (economy.CONSTRUCTION, 10_000)], 1800000010)
            economy.post(db, "?", "loan", "Выдача кредита",
                         [(economy.player_account("alice"), 5_000), (economy.BANK, -5_000)], 1800000020)
            economy.post(db, "?", "sale", "Продажа здания: mine",
                         [(economy.player_account("bob"), 2_500), (economy.CONSTRUCTION, -2_500)], 1800000030)
            db.execute("INSERT INTO company_taxes VALUES('alice',2,100,200,300,600)")
            db.execute("INSERT INTO election_candidates VALUES(4,'alice','Alice',130,22,400,'')")
            db.execute("INSERT INTO election_results VALUES(4,'bob','Bob','{}',4)")
        status, data = game_server.stats_feed("alice")
        self.assertEqual(status, 200)
        kinds = [item["kind"] for item in data["events"]]
        for kind in ("build", "loan", "monthly_result", "tax", "election_candidacy", "election_result"):
            self.assertIn(kind, kinds)
        self.assertNotIn("Продажа здания: mine", repr(data))
        self.assertEqual(data["cursor"], data["total"])
        self.assertEqual(game_server.stats_feed("alice", data["cursor"])[1]["events"], [])
        self.assertEqual(game_server.stats_feed("alice")[1], data)

    def test_bankruptcy_without_liquidation_payment(self):
        with game_server.connect() as db:
            db.execute("INSERT INTO company_status VALUES('alice',0,0,0,0,1,2,0)")
        code, result = game_server.stats_feed("alice")
        self.assertEqual(code, 200)
        self.assertIn("bankruptcy", [e["kind"] for e in result["events"]])

    def test_multiple_feed_pages(self):
        with game_server.connect() as db:
            for i in range(65):
                economy.post(db, "?", "build", "Строительство: farm #%d" % i,
                             [(economy.player_account("alice"), -1), (economy.CONSTRUCTION, 1)],
                             1800000100 + i)
        _, first = game_server.stats_feed("alice")
        self.assertEqual(len(first["events"]), 50)
        self.assertFalse(first["has_more"])
        self.assertEqual(first["cursor"], first["total"])
        self.assertEqual(game_server.stats_feed("alice", first["cursor"])[1]["events"], [])
        with game_server.connect() as db:
            economy.post(db, "?", "build", "Строительство: новый склад",
                         [(economy.player_account("alice"), -1), (economy.CONSTRUCTION, 1)], 1800500000)
        _, newer = game_server.stats_feed("alice", first["cursor"])
        self.assertEqual(len(newer["events"]), 1)
        self.assertIn("новый склад", newer["events"][0]["title"])

    def test_http_requires_bearer_and_valid_query(self):
        # Only loopback on the ephemeral CI runner; no production API calls.
        import json
        import threading
        import urllib.error
        import urllib.request
        from http.server import ThreadingHTTPServer
        http = ThreadingHTTPServer(("127.0.0.1", 0), game_server.Handler)
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (http.shutdown(), http.server_close(), thread.join(timeout=2)))
        base = "http://127.0.0.1:%d" % http.server_port
        with self.assertRaises(urllib.error.HTTPError) as unauthorized:
            urllib.request.urlopen(base + "/leaderboard", timeout=4)
        self.assertEqual(unauthorized.exception.code, 401)
        with mock.patch.object(game_server.auth, "profile", return_value=(200, {"username": "alice"})):
            def get(path):
                req = urllib.request.Request(base + path,
                    headers={"Authorization": "Bearer test-not-a-real-token"})
                return urllib.request.urlopen(req, timeout=4)
            with get("/leaderboard?by=networth") as response:
                self.assertEqual(json.load(response)["me"]["owner"], "alice")
            with get("/feed?after=0") as response:
                self.assertTrue(json.load(response)["ok"])
            with self.assertRaises(urllib.error.HTTPError) as bad:
                get("/leaderboard?by=unknown")
            self.assertEqual(bad.exception.code, 400)
            with self.assertRaises(urllib.error.HTTPError) as cursor:
                get("/feed?after=-1")
            self.assertEqual(cursor.exception.code, 400)

    def test_invalid_queries_and_read_only(self):
        before = self.snapshot()
        self.assertEqual(game_server.stats_leaderboard("alice", "bad")[0], 400)
        self.assertEqual(game_server.stats_feed("alice", -1)[0], 400)
        self.assertEqual(game_server.stats_feed("alice", True)[0], 400)
        with mock.patch.object(game_server, "npc_tick", side_effect=AssertionError("tick called")):
            game_server.stats_leaderboard("alice")
            game_server.stats_feed("alice")
        self.assertEqual(before, self.snapshot())


if __name__ == "__main__":
    unittest.main()
