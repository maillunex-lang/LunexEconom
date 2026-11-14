"""Read-only price and economy charts."""
import os
import tempfile
import unittest
import uuid
from unittest import mock

import game_server
import economy
import social

T0 = 1_800_000_000


class ChartTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = game_server.DB
        game_server.DB = os.path.join(self.tmp.name, "w.sqlite3")
        self.now = T0
        patch = mock.patch.object(game_server.time, "time", side_effect=lambda: self.now)
        patch.start()
        self.addCleanup(patch.stop)
        social.reset_limits()
        game_server.wallet("alice")
        with game_server.connect() as db:
            db.execute("INSERT INTO market_prices(product,month_index,price,supply,demand) VALUES('honey',1,180,100,90)")
            db.execute("INSERT INTO market_prices(product,month_index,price,supply,demand) VALUES('honey',2,210,80,120)")
            db.execute("INSERT INTO market_prices(product,month_index,price,supply,demand) VALUES('oil',2,1400,10,10)")
            db.execute("INSERT INTO population(month_index,population,labor_force,jobs,wage,staffing_permille,demand_permille,next_population) "
                       "VALUES(1,200,100,80,1500,1000,1000,202)")
            db.commit()

    def tearDown(self):
        game_server.DB = self.old
        self.tmp.cleanup()

    def test_price_history_filters_product_and_window(self):
        denied = game_server.soc_get("alice", "/soc/charts/prices", {"product": ["roads"], "months": ["12"]})
        self.assertEqual(denied[1]["error"], "invalid_product")
        bad = game_server.soc_get("alice", "/soc/charts/prices", {"product": ["honey"], "months": ["nope"]})
        self.assertEqual(bad[1]["error"], "invalid_months")
        status, body = game_server.soc_get("alice", "/soc/charts/prices", {"product": ["honey"], "months": ["12"]})
        self.assertEqual(status, 200)
        self.assertEqual([p["month"] for p in body["points"]], [1, 2])
        self.assertEqual(body["points"][1]["price"], 210)
        self.assertEqual([item["id"] for item in body["products"]], list(economy.MARKET))
        self.assertNotIn("email", str(body).lower())
        narrow = game_server.soc_get("alice", "/soc/charts/prices", {"product": ["honey"], "months": ["1"]})
        self.assertEqual([p["month"] for p in narrow[1]["points"]], [2])

    def test_economy_series_reports_unemployment(self):
        status, body = game_server.soc_get("alice", "/soc/charts/economy", {"months": ["all"]})
        self.assertEqual(status, 200)
        self.assertEqual(body["points"][0]["population"], 200)
        self.assertEqual(body["points"][0]["unemployment_permille"], 200)
        self.assertEqual(body["points"][0]["wage"], 1500)

    def test_charts_do_not_move_money(self):
        before = game_server.wallet("alice")[1]["balance"]
        game_server.soc_get("alice", "/soc/charts/prices", {"product": ["honey"], "months": ["all"]})
        self.assertEqual(game_server.wallet("alice")[1]["balance"], before)
        self.assertTrue(uuid.uuid4())
