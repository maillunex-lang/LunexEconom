"""EX-05 households: scale, conservation, idempotency, demand identity while the flag is off."""
import os
import tempfile
import unittest
import uuid

import balance
import economy
import game_server
import households


def _flag(name, value):
    os.environ["LUNEX_BAL_" + name] = str(value)
    balance.reload()


class HouseholdTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = game_server.DB
        game_server.DB = os.path.join(self.tmp.name, "w.sqlite3")
        self.addCleanup(self._restore)

    def _restore(self):
        game_server.DB = self.old
        self.tmp.cleanup()
        for name in ("HOUSEHOLDS_ENABLED", "HH_DEMAND_NUDGE_PPM", "HH_HOUSING_STRESS", "HH_RECESSION"):
            os.environ.pop("LUNEX_BAL_" + name, None)
        balance.reload()

    def test_scale_default_and_preview(self):
        self.assertEqual(balance.get("POPULATION_SCALE"), 100)
        self.assertFalse(balance.get("HOUSEHOLDS_ENABLED"))
        preview = {row["id"]: row["scaled"] for row in households.scale_preview()}
        self.assertEqual(len(preview), 20)
        self.assertEqual(preview["ufa"], 11633)
        self.assertEqual(preview["agidel"], 137)
        self.assertEqual(households.scale_of(13700, 200), 68)
        self.assertEqual(sum(row["scaled"] for row in households.scale_preview(50)), 49746)

    def test_flag_off_is_a_noop_and_demand_is_unchanged(self):
        with game_server.connect() as db:
            households.monthly(db, "?", 0, 1)
            db.commit()
            cities = db.execute("SELECT COUNT(*) FROM household_cities").fetchone()[0]
            done = db.execute("SELECT COUNT(*) FROM household_months").fetchone()[0]
            self.assertEqual(households.consumer_demand(db, "?", "honey", 3, 1.25, "ufa"), economy.demand_for("honey", 3, 1.25))
            self.assertEqual(households.demand_factor(db, "?", "ufa"), 1.0)
            view = households.view(db, "?", "ufa")
        self.assertEqual((cities, done), (0, 0))
        self.assertEqual(view["cities"][0]["scaled"], 11633)
        self.assertFalse(view["cities"][0]["simulated"])

    def test_month_conserves_people_and_is_idempotent(self):
        _flag("HOUSEHOLDS_ENABLED", 1)
        with game_server.connect() as db:
            households.monthly(db, "?", 0, 1)
            first = db.execute(
                "SELECT SUM(children+working+retired), SUM(births), SUM(deaths), SUM(migrants_in), SUM(migrants_out), "
                "SUM(children), SUM(working), SUM(retired) FROM household_cities").fetchone()
            households.monthly(db, "?", 0, 1)
            second = db.execute(
                "SELECT SUM(children+working+retired), SUM(births), SUM(deaths), SUM(migrants_in), SUM(migrants_out) "
                "FROM household_cities").fetchone()
            months = db.execute("SELECT COUNT(*) FROM household_months").fetchone()[0]
            db.commit()
        total, births, deaths, inn, out, children, working, retired = first
        self.assertEqual(births - deaths, total - sum(row["scaled"] for row in households.scale_preview()))
        self.assertEqual(inn, out)
        self.assertEqual(children + working + retired, total)
        self.assertGreater(working, 0)
        self.assertEqual(second[:5], (total, births, deaths, inn, out))
        self.assertEqual(months, 1)
        with game_server.connect() as db:
            factor = households.demand_factor(db, "?", "ufa")
            base = economy.demand_for("goods", 1, 1.0)
            nudged = households.consumer_demand(db, "?", "goods", 1, 1.0, "ufa")
        self.assertLessEqual(abs(factor - 1.0), 0.02 + 1e-9)
        self.assertEqual(nudged, int(round(base * factor)) if abs(factor - 1) > 1e-12 else base)

    def test_live_month_does_not_seed_households_while_off(self):
        from unittest import mock
        now = {"t": 1_800_000_000}
        patch = mock.patch.object(game_server.time, "time", side_effect=lambda: now["t"])
        patch.start()
        self.addCleanup(patch.stop)
        game_server.wallet("alice")
        now["t"] += 86400 + 5
        game_server.wallet("alice")
        with game_server.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM household_cities").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM inflation_index").fetchone()[0], 0)
            bad = db.execute("SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0").fetchall()
            total = db.execute("SELECT COALESCE(SUM(balance),0) FROM wallets").fetchone()[0]
        self.assertEqual((bad, total), ([], 0))


if __name__ == "__main__":
    unittest.main()
