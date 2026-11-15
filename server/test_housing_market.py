"""EX-05 housing: supply, commissioning, rent funded from residents, mortgage burden."""
import os
import tempfile
import unittest

import balance
import balance_targets
import economy
import game_server
import geo
import households
import housing_market
import regional_prices


class HousingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = game_server.DB
        game_server.DB = os.path.join(self.tmp.name, "w.sqlite3")
        self.addCleanup(self._restore)

    def _restore(self):
        game_server.DB = self.old
        self.tmp.cleanup()
        os.environ.pop("LUNEX_BAL_HOUSEHOLDS_ENABLED", None)
        balance.reload()

    def test_prices_follow_the_city_and_the_burden_stays_in_the_corridor(self):
        self.assertEqual(housing_market.capacity_of("house"), 4)
        self.assertEqual(housing_market.capacity_of("block_5"), 180)
        self.assertEqual(housing_market.price_per_person("ufa") // regional_prices.AREA_PER_RESIDENT, regional_prices.market_price_m2("ufa"))
        share = housing_market.rent_per_person("ufa") / regional_prices.wage("ufa")
        self.assertTrue(0.15 <= share <= 0.40, share)
        quote = housing_market.quote_mortgage(1_000_000, 0.12, 240, income_year=400_000)
        self.assertGreater(quote["payment"], 10_000)
        self.assertLess(quote["payment"], 12_000)
        self.assertTrue(quote["within_burden"])
        self.assertLessEqual(quote["burden"], 0.45)
        clamped = housing_market.quote_mortgage(100_000, 0.80, 12, income_year=10_000_000)
        self.assertEqual(clamped["rate_year"], 0.40)
        floor = housing_market.quote_mortgage(100_000, 0.01, 12, income_year=10_000_000)
        self.assertEqual(floor["rate_year"], 0.05)
        self.assertEqual(balance_targets.check({
            "housing_share_of_family_spending": share,
            "mortgage_burden": quote["burden"],
        }), [])

    def test_supply_commission_and_rent_stay_balanced(self):
        os.environ["LUNEX_BAL_HOUSEHOLDS_ENABLED"] = "1"
        balance.reload()
        city = geo.get_city("ufa")
        with game_server.connect() as db:
            db.execute("INSERT INTO buildings(id,owner,kind,x,y,created) VALUES(?,?,?,?,?,?)",
                       ("h1", "town:ufa", "house", city["x"], city["y"], 1))
            db.execute("INSERT INTO buildings(id,owner,kind,x,y,created) VALUES(?,?,?,?,?,?)",
                       ("b5", "town:ufa", "block_5", city["x"], city["y"], 1))
            economy.post(db, "?", "seed", "тест жителям", [(economy.TREASURY, -50_000), (economy.RESIDENTS, 50_000)], 1)
            first = housing_market.on_commissioned(db, "?", "h1", "ufa", "house", "town:ufa", 0, 1)
            again = housing_market.on_commissioned(db, "?", "h1", "ufa", "house", "town:ufa", 0, 1)
            households.monthly(db, "?", 0, 1)
            households.monthly(db, "?", 0, 1)
            supply = housing_market.housing_supply(db, "?", "ufa")
            txs = db.execute("SELECT COUNT(*) FROM ledger_tx WHERE kind='rent'").fetchone()[0]
            bad = db.execute("SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0").fetchall()
            total = db.execute("SELECT COALESCE(SUM(balance),0) FROM wallets").fetchone()[0]
            paid = db.execute("SELECT SUM(amount) FROM housing_rent_log").fetchone()[0]
            db.commit()
        self.assertTrue(first)
        self.assertFalse(again)
        self.assertEqual(supply["capacity"], 4 + 180)
        self.assertEqual(supply["deficit"], supply["people"] - supply["capacity"])
        self.assertGreater(supply["people"], 11000)
        self.assertEqual(txs, 1)
        self.assertGreater(paid, 0)
        self.assertEqual((bad, total), ([], 0))


if __name__ == "__main__":
    unittest.main()
