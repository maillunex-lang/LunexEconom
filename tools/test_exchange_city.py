"""Cross-city exchange tests on ephemeral SQLite or disposable PostgreSQL lunex_ci.

Never point PostgreSQL tests at the production lunexeconom database.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))

import economy
import exchange
import regions

NOW = 1_800_000_000


def balances(db, ph):
    query = "SELECT account,balance FROM wallets"
    return {str(a): int(b) for a, b in db.execute(query).fetchall()}


def verify_city_trade(test, db, ph):
    with mock.patch.object(regions, "home_region", side_effect=lambda _db, _ph, owner: (
            "sterlitamak" if owner == "alice" else "ufa")):
        for player in ("alice", "bob"):
            economy.ensure_wallet(db, ph, player, NOW)
        exchange.add_stock(db, ph, "alice", "honey", 12)
        before = balances(db, ph)
        status, sell = exchange.place_order(db, ph, "alice",
                                            {"product": "honey", "side": "sell", "qty": 10, "price": 100},
                                            0, NOW)
        test.assertEqual(status, 201, sell)
        test.assertEqual(sell["order"]["city_id"], "sterlitamak")
        status, only_local = exchange.place_order(db, ph, "bob",
                                                   {"product": "honey", "side": "buy", "qty": 2, "price": 150},
                                                   0, NOW)
        test.assertEqual(status, 201, only_local)
        test.assertEqual(only_local["fills"], [])
        test.assertEqual(exchange._stock(db, ph, "bob", "honey"), 0)
        status, trade = exchange.place_order(db, ph, "bob",
                                             {"product": "honey", "side": "buy", "qty": 4, "price": 150,
                                              "allow_intercity": True}, 0, NOW)
        test.assertEqual(status, 201, trade)
        test.assertEqual(len(trade["fills"]), 1, trade)
        freight = regions.unit_cost("honey", "sterlitamak", "ufa") * 4
        test.assertGreater(freight, 0)
        test.assertEqual(trade["fills"][0]["transport_cost"], freight)
        test.assertEqual(trade["fills"][0]["seller_city"], "sterlitamak")
        after = balances(db, ph)
        test.assertEqual(after[economy.player_account("bob")], before[economy.player_account("bob")] - (400 + freight) - 2 * 150)
        test.assertEqual(after[economy.player_account("alice")], before[economy.player_account("alice")] + 396)
        test.assertEqual(after[economy.player_account(economy.CITY)], before.get(economy.player_account(economy.CITY), 0) + 4 + freight)
        test.assertEqual(exchange._stock(db, ph, "bob", "honey"), 4)
        test.assertEqual(exchange._stock(db, ph, "alice", "honey"), 2)
        row = db.execute(exchange._q("SELECT seller_city,buyer_city,transport_cost FROM soc_fills WHERE buy_id=%s", ph),
                         (trade["order"]["id"],)).fetchone()
        test.assertEqual(tuple(row), ("sterlitamak", "ufa", freight))
        unbalanced = db.execute("SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0").fetchall()
        test.assertEqual(unbalanced, [])
        test.assertEqual(sum(balances(db, ph).values()), 0)
        status, book = exchange.view_book(db, ph, "bob", {"product": "honey"})
        test.assertEqual(status, 200)
        test.assertTrue(any(c["city_id"] == "sterlitamak" for c in book["cities"]))
        test.assertEqual(exchange.cancel_order(db, ph, "bob",
                                               {"order_id": only_local["order"]["id"]}, 0, NOW)[0], 201)
        test.assertEqual(exchange._balance(db, ph, exchange.escrow_account(only_local["order"]["id"])), 0)


class SQLiteCityExchange(unittest.TestCase):
    def test_city_escrow_and_double_entry(self):
        import game_server
        with tempfile.TemporaryDirectory() as tmp:
            old = game_server.DB
            try:
                game_server.DB = str(Path(tmp)/"world.sqlite3")
                game_server.wallet("alice")
                game_server.wallet("bob")
                with game_server.connect() as db:
                    verify_city_trade(self, db, "?")
            finally:
                game_server.DB = old

    def test_invalid_region(self):
        import game_server
        with tempfile.TemporaryDirectory() as tmp:
            old = game_server.DB
            try:
                game_server.DB = str(Path(tmp)/"world.sqlite3")
                game_server.wallet("alice")
                with game_server.connect() as db:
                    code, error = exchange.place_order(db, "?", "alice",
                                                       {"product": "honey", "side": "buy", "qty": 1,
                                                        "price": 100, "city_id": "unknown"}, 0, NOW)
                    self.assertEqual((code, error["error"]), (400, "invalid_city"))
                    code, error = exchange.place_order(db, "?", "alice",
                                                       {"product": "honey", "side": "sell", "qty": 1,
                                                        "price": 100, "city_id": "sterlitamak"}, 0, NOW)
                    self.assertEqual((code, error["error"]), (403, "city_not_owned"))
            finally:
                game_server.DB = old


@unittest.skipUnless(os.getenv("LUNEX_DB_ENGINE") == "postgres" and
                     os.getenv("LUNEX_PG_DB") == "lunex_ci",
                     "Requires explicit disposable PostgreSQL lunex_ci database")
class PostgreSQLCityExchange(unittest.TestCase):
    def test_city_escrow_and_double_entry(self):
        import postgres_db
        postgres_db.init()
        db = postgres_db.connect()
        try:
            verify_city_trade(self, db, "%s")
        finally:
            db.rollback()
            db.close()


if __name__ == "__main__":
    unittest.main()
