"""EX-09 inflation index: observational, clamped, idempotent, off by default."""
import os
import tempfile
import unittest

import balance
import balance_targets
import economy
import game_server
import inflation


class InflationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = game_server.DB
        game_server.DB = os.path.join(self.tmp.name, "w.sqlite3")
        self.addCleanup(self._restore)

    def _restore(self):
        game_server.DB = self.old
        self.tmp.cleanup()
        for name in ("INFLATION_ENABLED", "INFLATION_SHOCK"):
            os.environ.pop("LUNEX_BAL_" + name, None)
        balance.reload()

    def _prices(self, db, month, factor):
        for product in inflation.BASKET:
            ref = economy.reference_price(product)
            db.execute(
                "INSERT INTO market_prices(product,month_index,price,supply,demand) VALUES(?,?,?,?,?)",
                (product, month, int(ref * factor), 1, 1))

    def test_flag_off_writes_nothing(self):
        with game_server.connect() as db:
            self._prices(db, 0, 2.5)
            self.assertIsNone(inflation.monthly(db, "?", 0, 1))
            count = db.execute("SELECT COUNT(*) FROM inflation_index").fetchone()[0]
            quiet = inflation.view(db, "?")
            db.commit()
        self.assertEqual(count, 0)
        self.assertEqual(quiet["rate_year"], 0.0)

    def test_ceiling_and_shock_stay_inside_the_corridor(self):
        os.environ["LUNEX_BAL_INFLATION_ENABLED"] = "1"
        os.environ["LUNEX_BAL_INFLATION_SHOCK"] = "1"
        balance.reload()
        with game_server.connect() as db:
            before = db.execute("SELECT COALESCE(SUM(balance),0) FROM wallets").fetchone()[0]
            self._prices(db, 0, 2.5)
            inflation.monthly(db, "?", 0, 1)
            inflation.monthly(db, "?", 0, 1)
            view = inflation.view(db, "?")
            rows = db.execute("SELECT COUNT(*) FROM inflation_index").fetchone()[0]
            after = db.execute("SELECT COALESCE(SUM(balance),0) FROM wallets").fetchone()[0]
            db.commit()
        self.assertEqual(rows, 1)
        self.assertGreater(view["rate_year"], 0)
        self.assertLessEqual(view["rate_year"], 0.10)
        self.assertEqual(before, after)
        self.assertEqual(balance_targets.check({"inflation_year": view["rate_year"]}), [])


if __name__ == "__main__":
    unittest.main()
