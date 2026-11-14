import os
import tempfile
import unittest
import uuid
from unittest import mock

import economy
import game_server

DAY = 86400
T0 = 1_800_000_000


class SellTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = game_server.DB
        game_server.DB = os.path.join(self.tmp.name, "w.sqlite3")
        self.now = T0
        p = mock.patch.object(game_server.time, "time", side_effect=lambda: self.now)
        p.start()
        self.addCleanup(p.stop)
        self.cursor = 0

    def tearDown(self):
        game_server.DB = self.old
        self.tmp.cleanup()

    def build(self, who, kind):
        for _ in range(400):
            self.cursor += 1
            status, res = game_server.build(who, {"kind": kind, "x": 8, "y": 10 + 7 * self.cursor, "request_id": str(uuid.uuid4())})
            if status == 201:
                return res
        self.fail("no site")

    def sell(self, who, object_id, request_id=None):
        return game_server.sell(who, {"object_id": object_id, "request_id": request_id or str(uuid.uuid4())})

    def ledger_ok(self):
        with game_server.connect() as db:
            bad = db.execute("SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0").fetchall()
            total = db.execute("SELECT COALESCE(SUM(balance),0) FROM wallets").fetchone()[0]
            neg = db.execute("SELECT 1 FROM wallets WHERE account LIKE 'player:%' AND balance<0").fetchall()
        self.assertEqual((bad, total, neg), ([], 0, []))

    def test_sell_pays_half_and_removes_the_building(self):
        res = self.build("alice", "farm")
        before = game_server.wallet("alice")[1]["balance"]
        status, out = self.sell("alice", res["object_id"])
        self.assertEqual(status, 201, out)
        self.assertEqual(out["price"], 60_000)
        self.assertEqual(out["balance"], before + 60_000)
        w = game_server.wallet("alice")[1]
        self.assertEqual(w["holdings"], {})
        with game_server.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM buildings").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM cells").fetchone()[0], 0)
        self.ledger_ok()

    def test_events_tell_clients(self):
        res = self.build("alice", "farm")
        status, out = self.sell("alice", res["object_id"])
        self.assertTrue(all(e["kind"] == "building_removed" for e in out["events"]))
        status, data = game_server.events(0)
        kinds = [e["kind"] for e in data["events"]]
        self.assertIn("building_removed", kinds)
        seen = {}
        for e in data["events"]:
            key = (e["cx"], e["cy"])
            self.assertEqual(e["version"], seen.get(key, 0) + 1)
            seen[key] = e["version"]

    def test_only_the_owner_can_sell(self):
        res = self.build("alice", "farm")
        self.assertEqual(self.sell("bob", res["object_id"])[1]["error"], "not_owner")
        self.assertEqual(self.sell("bob", res["object_id"])[0], 403)
        self.assertEqual(game_server.wallet("alice")[1]["holdings"], {"farm": 1})

    def test_unknown_building_and_bad_requests(self):
        self.assertEqual(self.sell("alice", "nope")[0], 404)
        self.assertEqual(game_server.sell("alice", {"object_id": "x", "request_id": "bad"})[0], 400)
        self.assertEqual(game_server.sell("alice", {"object_id": 5, "request_id": str(uuid.uuid4())})[0], 400)

    def test_sale_is_idempotent(self):
        res = self.build("alice", "farm")
        rid = str(uuid.uuid4())
        s1, a = self.sell("alice", res["object_id"], rid)
        balance = game_server.wallet("alice")[1]["balance"]
        s2, b = self.sell("alice", res["object_id"], rid)
        self.assertEqual((s1, s2), (201, 200))
        self.assertEqual(a, b)
        self.assertEqual(game_server.wallet("alice")[1]["balance"], balance)

    def test_second_sale_of_the_same_building_fails(self):
        res = self.build("alice", "farm")
        self.sell("alice", res["object_id"])
        self.assertEqual(self.sell("alice", res["object_id"])[0], 404)

    def test_sold_building_stops_producing_and_site_is_free(self):
        res = self.build("alice", "farm")
        self.build("alice", "farm")
        self.sell("alice", res["object_id"])
        self.now += DAY + 5
        w = game_server.wallet("alice")[1]
        self.assertEqual(w["reports"][0]["buildings"], 1)
        with game_server.connect() as db:
            sold_site_cells = db.execute("SELECT COUNT(*) FROM cells").fetchone()[0]
        self.assertEqual(sold_site_cells, 4)      # only the remaining 2x2 farm occupies cells

    def test_selling_a_warehouse_sells_stock_above_capacity(self):
        wh = self.build("alice", "warehouse")
        game_server.wallet("alice")
        with game_server.connect() as db:
            db.execute("INSERT INTO inventory(owner,product,qty) VALUES('alice','honey',300) ON CONFLICT(owner,product) DO UPDATE SET qty=300")
        before = game_server.wallet("alice")[1]["balance"]
        status, out = self.sell("alice", wh["object_id"])
        self.assertEqual(status, 201)
        self.assertGreater(out["price"], int(economy.BUILD_COST["warehouse"] * economy.SELL_RATE))   # stock was sold too
        self.assertEqual(game_server.wallet("alice")[1]["inventory"]["used"], 0)
        self.assertGreater(out["balance"], before)
        self.ledger_ok()

    def test_stock_stays_when_capacity_remains(self):
        a = self.build("alice", "warehouse")
        self.build("alice", "warehouse")
        game_server.wallet("alice")
        with game_server.connect() as db:
            db.execute("INSERT INTO inventory(owner,product,qty) VALUES('alice','honey',300) ON CONFLICT(owner,product) DO UPDATE SET qty=300")
        self.sell("alice", a["object_id"])
        self.assertEqual(game_server.wallet("alice")[1]["inventory"]["used"], 300)    # 400 capacity is left

    def test_selling_does_not_pay_off_nor_hide_debts(self):
        res = self.build("alice", "factory")
        with game_server.connect() as db:
            db.execute("INSERT INTO company_status(owner,missed,wages_owed,input_owed,maint_owed,bankruptcies,last_bankruptcy_month,written_off) VALUES('alice',1,1000,0,0,0,NULL,0) ON CONFLICT(owner) DO UPDATE SET wages_owed=1000")
        self.sell("alice", res["object_id"])
        self.assertEqual(game_server.wallet("alice")[1]["company"]["arrears"], 1000)


if __name__ == "__main__":
    unittest.main()
