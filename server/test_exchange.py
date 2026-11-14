"""Exchange matcher (pure) and the order-book API on SQLite."""
import os
import tempfile
import threading
import unittest
import uuid
from unittest import mock

import economy
import exchange
import game_server
import social

DAY = 86400
T0 = 1_800_000_000


def rid():
    return str(uuid.uuid4())


class MatchTests(unittest.TestCase):
    def book(self):
        return [
            {"id": "s-expensive", "owner": "ann", "side": "sell", "price": 120, "qty": 5, "seq": 1},
            {"id": "s-cheap-late", "owner": "bob", "side": "sell", "price": 100, "qty": 4, "seq": 3},
            {"id": "s-cheap-early", "owner": "cara", "side": "sell", "price": 100, "qty": 3, "seq": 2},
            {"id": "s-self", "owner": "me", "side": "sell", "price": 90, "qty": 9, "seq": 0},
            {"id": "b-low", "owner": "dan", "side": "buy", "price": 80, "qty": 6, "seq": 1},
        ]

    def test_buy_takes_cheapest_then_earliest_and_skips_self(self):
        fills, left = exchange.match_book(self.book(), {"owner": "me", "side": "buy", "price": 100, "qty": 6})
        self.assertEqual([(f["id"], f["qty"], f["price"]) for f in fills], [("s-cheap-early", 3, 100), ("s-cheap-late", 3, 100)])
        self.assertEqual(left, 0)
        self.assertEqual(self.book()[0]["qty"], 5)   # pure: inputs stay put

    def test_partial_and_no_cross(self):
        fills, left = exchange.match_book(self.book(), {"owner": "zoe", "side": "buy", "price": 89, "qty": 2})
        self.assertEqual(fills, [])
        self.assertEqual(left, 2)
        sells = [{"id": "only", "owner": "ann", "side": "sell", "price": 100, "qty": 10, "seq": 1}]
        fills, left = exchange.match_book(sells, {"owner": "zoe", "side": "buy", "price": 150, "qty": 4})
        self.assertEqual(fills[0]["qty"], 4)
        self.assertEqual(fills[0]["price"], 100)
        self.assertEqual(left, 0)

    def test_sell_hits_the_highest_bid_first(self):
        resting = [
            {"id": "low", "owner": "a", "side": "buy", "price": 100, "qty": 5, "seq": 1},
            {"id": "high-late", "owner": "b", "side": "buy", "price": 130, "qty": 2, "seq": 4},
            {"id": "high-early", "owner": "c", "side": "buy", "price": 130, "qty": 2, "seq": 2},
            {"id": "mine", "owner": "me", "side": "buy", "price": 200, "qty": 9, "seq": 0},
        ]
        fills, left = exchange.match_book(resting, {"owner": "me", "side": "sell", "price": 100, "qty": 3})
        self.assertEqual([(f["id"], f["qty"], f["price"]) for f in fills], [("high-early", 2, 130), ("high-late", 1, 130)])
        self.assertEqual(left, 0)

    def test_same_input_is_deterministic(self):
        incoming = {"owner": "zoe", "side": "buy", "price": 120, "qty": 8}
        self.assertEqual(exchange.match_book(self.book(), incoming), exchange.match_book(self.book(), dict(incoming)))

    def test_fee_never_exceeds_the_notional(self):
        self.assertEqual(exchange.fee_of(0), 0)
        self.assertEqual(exchange.fee_of(99), 0)
        self.assertEqual(exchange.fee_of(100), 1)
        self.assertEqual(exchange.fee_of(400), 4)
        self.assertLessEqual(exchange.fee_of(10**9), 10**9)


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = game_server.DB
        game_server.DB = os.path.join(self.tmp.name, "w.sqlite3")
        self.now = T0
        patch = mock.patch.object(game_server.time, "time", side_effect=lambda: self.now)
        patch.start()
        self.addCleanup(patch.stop)
        social.reset_limits()
        self.limits = (social.ACTION_PER_MINUTE, social.IP_PER_MINUTE)
        social.ACTION_PER_MINUTE = 10000
        social.IP_PER_MINUTE = 10000
        self.taxes = economy.TAXES_ENABLED
        economy.TAXES_ENABLED = False

    def tearDown(self):
        social.ACTION_PER_MINUTE, social.IP_PER_MINUTE = self.limits
        economy.TAXES_ENABLED = self.taxes
        game_server.DB = self.old
        self.tmp.cleanup()

    def post(self, who, path, payload):
        return game_server.soc_post(who, path, payload, "10.0.0.8")

    def order(self, who, side, product="honey", qty=10, price=200):
        return self.post(who, "/soc/exchange/order", {"side": side, "product": product, "qty": qty, "price": price, "request_id": rid()})

    def stock(self, who, product, qty):
        game_server.wallet(who)
        with game_server.connect() as db:
            db.execute("INSERT INTO inventory(owner,product,qty) VALUES(?,?,?) ON CONFLICT(owner,product) DO UPDATE SET qty=excluded.qty",
                       (who, product, qty))
            db.commit()

    def ledger(self):
        with game_server.connect() as db:
            bad = db.execute("SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0").fetchall()
            total = db.execute("SELECT COALESCE(SUM(balance),0) FROM wallets").fetchone()[0]
            negative = db.execute("SELECT account FROM wallets WHERE account LIKE 'player:%' AND account NOT LIKE 'player:alliance:%' AND balance<0").fetchall()
            goods = db.execute("SELECT COALESCE(SUM(qty),0) FROM inventory WHERE product='honey'").fetchone()[0]
            reserved = db.execute("SELECT COALESCE(SUM(qty_left),0) FROM soc_orders WHERE product='honey' AND side='sell' AND status='open'").fetchone()[0]
        self.assertEqual(bad, [])
        self.assertEqual(total, 0)
        self.assertEqual(negative, [])
        return int(goods), int(reserved)

    def test_rejects_bad_orders_self_trade_and_keeps_units(self):
        self.stock("alice", "honey", 20)
        self.assertEqual(self.order("alice", "sell", price=50)[1]["error"], "price_out_of_range")
        self.assertEqual(self.order("alice", "sell", qty=0)[1]["error"], "invalid_qty")
        self.assertEqual(self.order("alice", "sell", qty=True)[1]["error"], "invalid_qty")
        self.assertEqual(self.order("npc:ural-agro", "buy")[1]["error"], "npc_forbidden")
        self.assertEqual(self.order("alice", "hold")[1]["error"], "invalid_side")
        denied = self.order("bob", "sell", qty=1)
        self.assertEqual(denied[1]["error"], "insufficient_stock")
        placed = self.order("alice", "sell", qty=20, price=200)
        self.assertEqual(placed[0], 201)
        self.assertEqual(placed[1]["fills"], [])
        buy = self.order("alice", "buy", qty=5, price=200)
        self.assertEqual(buy[0], 201, buy[1])
        self.assertEqual(buy[1]["fills"], [])
        self.assertEqual(self.ledger(), (0, 20))
        cancelled = self.post("alice", "/soc/exchange/cancel", {"order_id": placed[1]["order"]["id"], "request_id": rid()})
        self.assertEqual(cancelled[0], 201, cancelled[1])
        self.assertEqual(self.ledger()[0], 20)
        other = self.post("bob", "/soc/exchange/cancel", {"order_id": placed[1]["order"]["id"], "request_id": rid()})
        self.assertEqual(other[1]["error"], "not_owner")

    def test_partial_fill_price_improvement_and_city_fee(self):
        self.stock("alice", "honey", 10)
        sell = self.order("alice", "sell", qty=10, price=100)
        self.assertEqual(sell[0], 201, sell[1])
        buy = self.order("bob", "buy", qty=4, price=150)
        self.assertEqual(buy[0], 201, buy[1])
        self.assertEqual(buy[1]["fills"], [{"order_id": sell[1]["order"]["id"], "qty": 4, "price": 100, "fee": 4}])
        goods, reserved = self.ledger()
        self.assertEqual((goods, reserved), (4, 6))
        with game_server.connect() as db:
            seller = db.execute("SELECT balance FROM wallets WHERE account=?", (economy.player_account("alice"),)).fetchone()[0]
            buyer = db.execute("SELECT balance FROM wallets WHERE account=?", (economy.player_account("bob"),)).fetchone()[0]
            city = db.execute("SELECT balance FROM wallets WHERE account=?", (economy.player_account(economy.CITY),)).fetchone()[0]
        # Seller reserved nothing in cash and received 400-4. Buyer reserved 150*4 then was refunded the 50*4 improvement.
        self.assertEqual(seller, economy.START_CAPITAL + 396)
        self.assertEqual(buyer, economy.START_CAPITAL - 400)
        self.assertEqual(city, 4)
        book = game_server.soc_get("bob", "/soc/exchange/book", {"product": ["honey"]})
        self.assertEqual(book[0], 200)
        self.assertEqual(book[1]["asks"], [{"price": 100, "qty": 6}])
        self.assertNotIn("alice", str(book[1]["asks"]))
        again = self.order("bob", "buy", qty=6, price=100)
        self.assertEqual(again[1]["order"]["status"], "filled")
        self.assertEqual(self.ledger(), (10, 0))

    def test_idempotent_order_and_parallel_sells_cannot_duplicate_stock(self):
        self.stock("alice", "honey", 10)
        request = rid()
        payload = {"side": "sell", "product": "honey", "qty": 10, "price": 200, "request_id": request}
        first = self.post("alice", "/soc/exchange/order", payload)
        second = self.post("alice", "/soc/exchange/order", payload)
        self.assertEqual((first[0], second[0]), (201, 200))
        self.assertEqual(first[1], second[1])
        self.stock("bob", "oil", 5)
        barrier = threading.Barrier(2)
        results = []

        def sell():
            barrier.wait()
            results.append(game_server.soc_post("bob", "/soc/exchange/order",
                                                 {"side": "sell", "product": "oil", "qty": 5, "price": 1500, "request_id": rid()}, "10.1.1.1"))

        threads = [threading.Thread(target=sell), threading.Thread(target=sell)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        codes = sorted(item[0] for item in results)
        self.assertEqual(codes, [201, 409])
        self.assertEqual(results[0][1].get("error") or results[1][1].get("error"), "insufficient_stock")
        with game_server.connect() as db:
            left = db.execute("SELECT COALESCE(SUM(qty),0) FROM inventory WHERE owner='bob' AND product='oil'").fetchone()[0]
            reserved = db.execute("SELECT COALESCE(SUM(qty_left),0) FROM soc_orders WHERE owner='bob' AND product='oil' AND status='open'").fetchone()[0]
        self.assertEqual((int(left), int(reserved)), (0, 5))
        self.ledger()

    def test_resting_buy_pays_its_price_to_the_incoming_seller(self):
        self.stock("alice", "goods", 3)
        buy = self.order("bob", "buy", product="goods", qty=3, price=2000)
        self.assertEqual(buy[0], 201, buy[1])
        sell = self.order("alice", "sell", product="goods", qty=3, price=1000)
        self.assertEqual(sell[0], 201, sell[1])
        self.assertEqual(sell[1]["fills"][0]["price"], 2000)
        self.ledger()
        with game_server.connect() as db:
            alice = db.execute("SELECT balance FROM wallets WHERE account=?", (economy.player_account("alice"),)).fetchone()[0]
        notional = 6000
        fee = exchange.fee_of(notional)
        self.assertEqual(alice, economy.START_CAPITAL + notional - fee)
