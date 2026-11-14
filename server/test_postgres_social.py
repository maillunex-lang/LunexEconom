"""Social systems on a disposable PostgreSQL 16 database named lunex_ci. Never point this at production."""
import os
import threading
import unittest
import uuid
from unittest import mock

DAY = 86400
T0 = 1_800_000_000
ENABLED = os.environ.get("LUNEX_DB_ENGINE") == "postgres" and os.environ.get("LUNEX_PG_DB") == "lunex_ci"

if ENABLED:
    import economy
    import game_server
    import postgres_db
    import social


def rid():
    return str(uuid.uuid4())


@unittest.skipUnless(ENABLED, "requires isolated lunex_ci PostgreSQL database")
class PostgresSocialTests(unittest.TestCase):
    def setUp(self):
        postgres_db.init()
        with postgres_db.connect() as db:
            names = [r[0] for r in db.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'").fetchall()]
            keep = {"users", "sessions", "auth_attempts", "auth_tokens", "email_verified"}
            db.execute("TRUNCATE TABLE " + ",".join(sorted(n for n in names if n not in keep)) + " RESTART IDENTITY CASCADE")
        self.now = T0
        patch = mock.patch.object(game_server.time, "time", side_effect=lambda: self.now)
        patch.start()
        self.addCleanup(patch.stop)
        self.taxes = economy.TAXES_ENABLED
        economy.TAXES_ENABLED = False
        social.reset_limits()
        self.limits = (social.ACTION_PER_MINUTE, social.MSG_PER_MINUTE, social.IP_PER_MINUTE, social.MAX_MEMBERS)
        social.ACTION_PER_MINUTE = 10000
        social.MSG_PER_MINUTE = 10000
        social.IP_PER_MINUTE = 10000
        self.cursor = 0

    def tearDown(self):
        social.ACTION_PER_MINUTE, social.MSG_PER_MINUTE, social.IP_PER_MINUTE, social.MAX_MEMBERS = self.limits
        economy.TAXES_ENABLED = self.taxes

    def post(self, who, path, payload, client="10.8.8.8"):
        return game_server.soc_post(who, path, payload, client)

    def create(self, who="alice", name="Мёд Алтая"):
        return self.post(who, "/soc/alliance/create", {"name": name, "request_id": rid()})

    def ledger(self):
        with postgres_db.connect() as db:
            bad = db.execute("SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0").fetchall()
            total = db.execute("SELECT COALESCE(SUM(balance),0) FROM wallets").fetchone()[0]
            negative = db.execute("SELECT account FROM wallets WHERE account LIKE 'player:%' AND balance<0").fetchall()
        self.assertEqual((bad, int(total), negative), ([], 0, []))

    def test_schema_and_idempotent_create(self):
        with postgres_db.connect() as db:
            names = {r[0] for r in db.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'").fetchall()}
        for table in ("soc_alliances", "soc_members", "soc_projects", "soc_messages", "soc_orders", "soc_achievements", "soc_reports"):
            self.assertIn(table, names)
        request = rid()
        payload = {"name": "Мёд Алтая", "request_id": request}
        first = self.post("alice", "/soc/alliance/create", payload)
        second = self.post("alice", "/soc/alliance/create", payload)
        self.assertEqual((first[0], second[0]), (201, 200))
        self.assertEqual(first[1], second[1])
        self.assertEqual(self.create("bob", "мёд алтая")[1]["error"], "name_taken")
        self.ledger()

    def test_parallel_withdraw_and_parallel_join(self):
        self.create()
        invite = self.post("alice", "/soc/alliance/invite", {"name": "bob", "request_id": rid()})
        self.assertEqual(self.post("bob", "/soc/alliance/accept", {"invite_id": invite[1]["invite_id"], "request_id": rid()})[0], 201)
        barrier = threading.Barrier(2)
        results = []

        def pull():
            barrier.wait()
            results.append(self.post("alice", "/soc/alliance/withdraw", {"amount": social.CREATE_FEE, "request_id": rid()}))

        threads = [threading.Thread(target=pull), threading.Thread(target=pull)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(item[0] for item in results), [201, 402])
        self.create("carol", "Второй Союз")
        left = self.post("alice", "/soc/alliance/invite", {"name": "dave", "request_id": rid()})
        right = self.post("carol", "/soc/alliance/invite", {"name": "dave", "request_id": rid()})
        barrier = threading.Barrier(2)
        joined = []

        def accept(invite_id):
            barrier.wait()
            joined.append(self.post("dave", "/soc/alliance/accept", {"invite_id": invite_id, "request_id": rid()}))

        threads = [threading.Thread(target=accept, args=(left[1]["invite_id"],)),
                   threading.Thread(target=accept, args=(right[1]["invite_id"],))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(item[0] for item in joined), [201, 409])
        self.ledger()

    def test_project_builds_and_dissolve_returns_the_sale(self):
        self.create()
        body = None
        for _ in range(400):
            self.cursor += 1
            status, body = self.post("alice", "/soc/project", {"kind": "farm", "x": 8, "y": 10 + 7 * self.cursor, "request_id": rid()})
            if status == 201:
                break
            self.assertIn(body.get("error"), ("water", "road_overlap", "occupied", "no_road_access"), body)
        else:
            self.fail("no site")
        project = body["project"]
        pledged = self.post("alice", "/soc/project/pledge", {"project_id": project["id"], "amount": project["cost"], "request_id": rid()})
        self.assertEqual(pledged[0], 201, pledged[1])
        self.assertTrue(pledged[1]["started"]["started"])
        done = self.post("alice", "/soc/alliance/dissolve", {"request_id": rid()})
        self.assertEqual(done[0], 201, done[1])
        sale = int(economy.BUILD_COST["farm"] * economy.SELL_RATE)
        self.assertEqual(sum(item["amount"] for item in done[1]["split"]), social.CREATE_FEE + sale)
        self.ledger()

    def test_messages_exchange_charts_and_achievements(self):
        self.create()
        sent = self.post("alice", "/soc/message", {"to": "bob", "body": "Привет", "request_id": rid()})
        self.assertEqual(sent[0], 201, sent[1])
        inbox = game_server.soc_get("bob", "/soc/inbox", {"after": ["0"]})
        self.assertEqual(inbox[1]["messages"][0]["name"], "alice")
        self.assertNotIn("email", str(inbox[1]).lower())
        blocked = self.post("alice", "/soc/message", {"to": "bob", "body": "<b>x</b>", "request_id": rid()})
        self.assertEqual(blocked[1]["error"], "invalid_text")
        game_server.wallet("alice")
        with postgres_db.connect() as db:
            db.execute("INSERT INTO inventory(owner,product,qty) VALUES(%s,%s,%s) ON CONFLICT(owner,product) DO UPDATE SET qty=excluded.qty",
                       ("alice", "honey", 8))
        sell = self.post("alice", "/soc/exchange/order", {"side": "sell", "product": "honey", "qty": 8, "price": 100, "request_id": rid()})
        self.assertEqual(sell[0], 201, sell)
        buy = self.post("bob", "/soc/exchange/order", {"side": "buy", "product": "honey", "qty": 3, "price": 150, "request_id": rid()})
        self.assertEqual(buy[0], 201, buy[1])
        self.assertEqual(buy[1]["fills"][0]["qty"], 3)
        self.assertEqual(buy[1]["fills"][0]["price"], 100)
        with postgres_db.connect() as db:
            goods = db.execute("SELECT COALESCE(SUM(qty),0) FROM inventory WHERE product='honey'").fetchone()[0]
            reserved = db.execute("SELECT COALESCE(SUM(qty_left),0) FROM soc_orders WHERE product='honey' AND side='sell' AND status='open'").fetchone()[0]
        self.assertEqual((int(goods), int(reserved)), (3, 5))
        prices = game_server.soc_get("alice", "/soc/charts/prices", {"product": ["honey"], "months": ["12"]})
        self.assertEqual(prices[0], 200)
        self.assertIn("products", prices[1])
        achievements = game_server.soc_get("alice", "/soc/achievements", {})
        again = game_server.soc_get("alice", "/soc/achievements", {})
        self.assertEqual(achievements[1]["achievements"], again[1]["achievements"])
        self.assertTrue(any(item["code"] == "alliance_member" and item["earned"] for item in achievements[1]["achievements"]))
        self.assertTrue(any(item["code"] == "exchange_deal" and item["earned"] for item in achievements[1]["achievements"]))
        rank = game_server.soc_get("bob", "/soc/alliance-ranking", {"by": ["capital"]})
        self.assertEqual(rank[1]["top"][0]["name"], "Мёд Алтая")
        self.ledger()

