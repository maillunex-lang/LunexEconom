"""Shops take a markup; a world without shops keeps the old resident payment."""
import os
import tempfile
import unittest
import uuid
from unittest import mock

import economy
import game_server
import npc
import retail

DAY = 86400
T0 = 1_800_000_000


class RetailTests(unittest.TestCase):
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

    def month(self):
        self.now += DAY + 5
        return game_server.wallet("alice")

    def test_without_a_shop_residents_pay_the_market_the_whole_consumer_value(self):
        self.build("alice", "farm")
        self.month()
        with game_server.connect() as db:
            resident_to_market = db.execute(
                "SELECT COALESCE(SUM(e.amount),0) FROM ledger_entries e JOIN ledger_tx t ON t.id=e.tx_id "
                "WHERE t.kind='residents' AND e.account=?", (economy.MARKET_ACCOUNT,)).fetchone()[0]
            shop_revenue = db.execute(
                "SELECT COALESCE(SUM(amount),0) FROM eco_owner_spend").fetchone()[0]
        self.assertGreater(resident_to_market, 0)
        self.assertGreater(shop_revenue, 0)          # the farm owner still consumes; that is not retail

    def test_a_shop_earns_a_markup_and_the_ledger_stays_closed(self):
        self.build("alice", "farm")          # honey has to exist, or residents buy nothing and the shop has no turnover
        self.build("bob", "shop")
        self.month()
        with game_server.connect() as db:
            revenue = db.execute("SELECT revenue FROM company_reports WHERE owner='bob'").fetchone()[0]
            bad = db.execute("SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0").fetchall()
            total = db.execute("SELECT COALESCE(SUM(balance),0) FROM wallets").fetchone()[0]
            residents = db.execute("SELECT balance FROM wallets WHERE account=?", (economy.RESIDENTS,)).fetchone()[0]
        self.assertGreater(revenue, 0)
        self.assertGreaterEqual(residents, 0)
        self.assertEqual((bad, total), ([], 0))
        retail_view = game_server.wallet("alice")[1]["retail"]
        self.assertEqual(retail_view["shops"], 1)
        self.assertGreater(retail_view["floor"], 0)
        self.assertLess(retail_view["unmet_units"], retail_view["consumer_demand"])
        with game_server.connect() as db:
            vat = db.execute("SELECT vat FROM company_taxes WHERE owner='bob'").fetchone()[0]
        # The markup is booked as goods revenue, so VAT is the goods rate (22%), paid to the city.
        self.assertEqual(vat, int(round(revenue * economy.VAT_RATES["goods"])))

    def test_the_city_budget_does_not_spend_like_an_owner(self):
        self.build("alice", "farm")
        self.month()
        with game_server.connect() as db:
            city = db.execute("SELECT COUNT(*) FROM eco_owner_spend WHERE owner=?", (economy.CITY,)).fetchone()[0]
        self.assertEqual(city, 0)

    def test_two_shops_split_the_margin_by_floor(self):
        weights = [("bob", 100), ("ann", 300)]
        self.assertEqual(retail._split(1000, weights), {"ann": 750, "bob": 250})
        self.assertEqual(retail._split(0, weights), {})

    def test_npc_builds_a_shop_only_when_demand_is_unserved(self):
        persona = {"owner": "npc:ural-agro", "name": "Урал-Агро", "pace": 1, "focus": {"farm": 3.0, "shop": 1.0}}
        quotes = {"honey": {"price": 200, "price_if_added": 200, "supply": 100},
                  "oil": {"price": 1500, "price_if_added": 1500, "supply": 40},
                  "goods": {"price": 2000, "price_if_added": 2000, "supply": 60}}
        served = dict(quotes, _retail={"unmet_units": 0, "unit_price": 1500})
        self.assertEqual(npc.choose_kind(persona, {"balance": 2_000_000, "holdings": {}}, served), "farm")
        unmet = dict(quotes, _retail={"unmet_units": 500, "unit_price": 1500})
        seller = {"owner": "npc:shop", "name": "S", "pace": 1, "focus": {"shop": 1.0}}
        self.assertEqual(npc.choose_kind(seller, {"balance": 2_000_000, "holdings": {}}, unmet), "shop")
        self.assertIsNone(npc.choose_kind(seller, {"balance": 2_000_000, "holdings": {}}, served))
