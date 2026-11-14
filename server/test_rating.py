import os
import tempfile
import unittest
import uuid
from unittest import mock

import city
import economy
import game_server

DAY = 86400
T0 = 1_800_000_000
BUDGET = economy.player_account(economy.CITY)


class RatingBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = game_server.DB
        game_server.DB = os.path.join(self.tmp.name, "w.sqlite3")
        self.now = T0
        p = mock.patch.object(game_server.time, "time", side_effect=lambda: self.now)
        p.start()
        self.addCleanup(p.stop)
        self.cursor = 0
        game_server.city_state()

    def tearDown(self):
        game_server.DB = self.old
        self.tmp.cleanup()

    def at(self, month):
        self.now = T0 + month * DAY + 5

    def view(self, owner=None):
        return game_server.city_state(owner)[1]

    def make_mayor(self, who, month=0):
        game_server.wallet(who)
        with game_server.connect() as db:
            city.set_mayor(db, "?", who, who, month, reason="test", now=self.now)

    def rating_rows(self, owner, months, permille):
        with game_server.connect() as db:
            for m in months:
                db.execute("INSERT INTO mayor_rating(month_index,mayor,residents_permille,business_permille,total_permille,low_streak) VALUES(?,?,?,?,?,0) "
                           "ON CONFLICT(month_index) DO UPDATE SET mayor=excluded.mayor,total_permille=excluded.total_permille", (m, owner, permille, permille, permille))

    def build(self, who, kind="farm"):
        for _ in range(400):
            self.cursor += 1
            status, res = game_server.build(who, {"kind": kind, "x": 8, "y": 10 + 7 * self.cursor, "request_id": str(uuid.uuid4())})
            if status == 201:
                return res
        self.fail("no site")

    def wallet_balance(self, who):
        return game_server.wallet(who)[1]["balance"]

    def ledger_ok(self):
        with game_server.connect() as db:
            bad = db.execute("SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0").fetchall()
            total = db.execute("SELECT COALESCE(SUM(balance),0) FROM wallets").fetchone()[0]
            neg = db.execute("SELECT 1 FROM wallets WHERE account LIKE 'player:%' AND balance<0").fetchall()
        self.assertEqual((bad, total, neg), ([], 0, []))


class RatingFormulaTests(unittest.TestCase):
    def test_good_city_low_taxes(self):
        res, biz, total = city.instant_rating(1.0, 0.0, 1.0, 0.05, 0.0)
        self.assertEqual(res, 1.0)
        self.assertAlmostEqual(biz, 1 - 0.6 * 0.2, places=6)
        self.assertAlmostEqual(total, 0.7 * 1.0 + 0.3 * biz, places=6)

    def test_default_taxes_do_not_please_business(self):
        _res, biz, _total = city.instant_rating(0.0, 0.0, 1.0, 0.13, 0.022)
        self.assertAlmostEqual(biz, 1 - 0.6 * 0.52 - 0.4, places=6)

    def test_residents_value_services_jobs_and_a_healthy_budget(self):
        base = city.instant_rating(0.0, 1.0, 0.0, 0.13, 0.022)[0]
        self.assertEqual(base, 0.0)
        self.assertGreater(city.instant_rating(1.0, 1.0, 0.0, 0.13, 0.022)[0], base)
        self.assertGreater(city.instant_rating(0.0, 0.0, 0.0, 0.13, 0.022)[0], base)
        self.assertGreater(city.instant_rating(0.0, 1.0, 1.0, 0.13, 0.022)[0], base)

    def test_values_stay_inside_zero_one(self):
        for args in ((0, 1, 0, 0.25, 0.022), (1, 0, 1, 0.0, 0.0), (5, -3, 9, -1, -1)):
            for v in city.instant_rating(*args):
                self.assertTrue(0.0 <= v <= 1.0)

    def test_no_taxes_means_happy_business(self):
        with mock.patch.object(economy, "TAXES_ENABLED", False):
            self.assertEqual(city.instant_rating(0.0, 1.0, 0.0, 0.25, 0.022)[1], 1.0)

    def test_term_bonus_tiers(self):
        self.assertEqual(city.term_bonus(0.80), 600_000)
        self.assertEqual(city.term_bonus(0.75), 600_000)
        self.assertEqual(city.term_bonus(0.65), 300_000)
        self.assertEqual(city.term_bonus(0.59), 0)
        self.assertEqual(city.term_bonus(None), 0)


class MonthlyRatingTests(RatingBase):
    def test_rating_is_recorded_every_month_and_smoothed(self):
        self.at(3)
        game_server.city_state()
        with game_server.connect() as db:
            rows = db.execute("SELECT month_index,mayor,total_permille FROM mayor_rating ORDER BY month_index").fetchall()
        self.assertEqual([r[0] for r in rows], [0, 1, 2])
        self.assertTrue(all(r[1] == city.ADMIN for r in rows))
        totals = [r[2] for r in rows]
        self.assertTrue(all(abs(a - b) < 200 for a, b in zip(totals, totals[1:])))          # no wild jumps

    def test_view_exposes_rating_perks_and_terms(self):
        v = self.view()
        self.assertEqual(sorted(v["rating"]), ["business", "dismiss_after", "dismiss_below", "low_streak", "residents", "total"])
        self.assertEqual(v["perks"]["salary"], 40_000)
        self.assertEqual(v["perks"]["max_terms"], 2)
        self.assertEqual(v["perks"]["term_bonus"], [[0.75, 600_000], [0.6, 300_000]])
        self.assertEqual(len(v["terms"]), 1)
        self.assertEqual(v["terms"][0]["mayor"], city.ADMIN)

    def test_social_services_raise_the_rating(self):
        a = self.view()["rating"]["total"]
        self.at(6)
        plain = self.view()["rating"]["total"]
        with game_server.connect() as db:
            economy.ensure_wallet(db, "?", economy.CITY, self.now)
            economy.post(db, "?", "test", "funding", [(economy.TREASURY, -5_000_000), (BUDGET, 5_000_000)], self.now)
        self.make_mayor("alice", 6)
        for kind in ("school", "school", "hospital", "park"):
            for _ in range(200):
                self.cursor += 1
                status, res = game_server.city_build("alice", {"kind": kind, "x": 8, "y": 10 + 7 * self.cursor, "request_id": str(uuid.uuid4())})
                if status == 201:
                    break
        self.at(14)
        better = self.view()["rating"]["total"]
        self.assertGreater(better, plain)


class DismissalTests(RatingBase):
    def test_an_unpopular_human_mayor_is_dismissed(self):
        self.make_mayor("alice", 0)
        self.rating_rows("alice", [-1], 100)
        with mock.patch.object(city, "instant_rating", return_value=(0.0, 0.0, 0.0)):
            self.at(3)
            v = self.view()
        self.assertEqual(v["mayor"]["owner"], city.ADMIN)
        self.assertEqual(v["terms"][0]["mayor"], city.ADMIN)
        dismissed = next(t for t in v["terms"] if t["mayor"] == "alice")
        self.assertEqual(dismissed["reason"], "dismissed")
        self.assertEqual(dismissed["bonus"], 0)
        self.assertEqual(v["mayor"]["term_end_month"], 12)            # the original term end stays

    def test_the_dismissed_mayor_loses_power_at_once(self):
        self.make_mayor("alice", 0)
        self.rating_rows("alice", [-1], 100)
        with mock.patch.object(city, "instant_rating", return_value=(0.0, 0.0, 0.0)):
            self.at(3)
            self.view()
        self.assertEqual(game_server.city_taxes("alice", {"profit_tax": 0.1, "property_tax": 0.01})[1]["error"], "not_mayor")

    def test_two_bad_months_are_not_enough(self):
        self.make_mayor("alice", 0)
        self.rating_rows("alice", [-1], 100)
        with mock.patch.object(city, "instant_rating", return_value=(0.0, 0.0, 0.0)):
            self.at(2)
            v = self.view()
        self.assertEqual(v["mayor"]["owner"], "alice")

    def test_a_recovering_rating_resets_the_streak(self):
        self.make_mayor("alice", 0)
        self.rating_rows("alice", [-1], 100)
        with mock.patch.object(city, "instant_rating", return_value=(0.0, 0.0, 0.0)):
            self.at(2)
            self.view()
        with mock.patch.object(city, "instant_rating", return_value=(1.0, 1.0, 1.0)):
            self.at(6)
            v = self.view()
        self.assertEqual(v["mayor"]["owner"], "alice")
        self.assertEqual(v["rating"]["low_streak"], 0)

    def test_the_administration_is_never_dismissed(self):
        with mock.patch.object(city, "instant_rating", return_value=(0.0, 0.0, 0.0)):
            self.at(10)
            v = self.view()
        self.assertEqual(v["mayor"]["owner"], city.ADMIN)
        self.assertEqual(len(v["terms"]), 1)


class PerksTests(RatingBase):
    def test_salary_and_performance_bonus(self):
        with game_server.connect() as db:                      # the salary is paid from the budget: put money in it
            economy.ensure_wallet(db, "?", economy.CITY, self.now)
            economy.post(db, "?", "test", "funding", [(economy.TREASURY, -1_000_000), (BUDGET, 1_000_000)], self.now)
        self.make_mayor("alice", 0)
        self.build("bob", "farm")
        before = self.wallet_balance("alice")
        self.at(1)
        game_server.wallet("alice")
        with game_server.connect() as db:
            collected = db.execute("SELECT COALESCE(SUM(paid),0) FROM company_taxes WHERE month_index=0").fetchone()[0]
        self.assertGreater(collected, 0)
        self.assertEqual(self.wallet_balance("alice") - before, economy.MAYOR_SALARY + int(economy.MAYOR_BONUS_SHARE * collected))

    def test_the_republic_rewards_a_successful_term(self):
        self.make_mayor("alice", 0)
        self.rating_rows("alice", range(0, 12), 800)
        before = self.wallet_balance("alice")
        self.at(12)
        v = self.view()
        term = next(t for t in v["terms"] if t["mayor"] == "alice")
        self.assertEqual(term["bonus"], 600_000)
        self.assertEqual(term["reason"] in ("term_ended", "re-elected"), True)
        self.assertGreaterEqual(self.wallet_balance("alice") - before, 600_000)
        self.ledger_ok()

    def test_a_good_term_earns_the_smaller_reward(self):
        self.make_mayor("alice", 0)
        self.rating_rows("alice", range(0, 12), 650)
        self.at(12)
        v = self.view()
        self.assertEqual(next(t for t in v["terms"] if t["mayor"] == "alice")["bonus"], 300_000)

    def test_a_mediocre_term_earns_nothing(self):
        self.make_mayor("alice", 0)
        self.rating_rows("alice", range(0, 12), 500)
        self.at(12)
        self.assertEqual(next(t for t in self.view()["terms"] if t["mayor"] == "alice")["bonus"], 0)

    def test_the_reward_is_paid_even_if_the_mayor_lost_the_election(self):
        self.make_mayor("alice", 0)
        self.rating_rows("alice", range(0, 12), 800)
        self.at(12)                                     # alice did not run: the NPC winner takes over, alice still gets her reward
        v = self.view()
        self.assertNotEqual(v["mayor"]["owner"], "alice")
        self.assertEqual(next(t for t in v["terms"] if t["mayor"] == "alice")["bonus"], 600_000)

    def test_the_administration_gets_no_reward(self):
        self.rating_rows(city.ADMIN, range(0, 12), 900)
        self.at(12)
        v = self.view()
        self.assertTrue(all(t["bonus"] == 0 for t in v["terms"] if t["mayor"] == city.ADMIN))

    def test_the_reward_comes_from_the_treasury_not_from_the_budget(self):
        self.make_mayor("alice", 0)
        self.rating_rows("alice", range(0, 12), 800)
        with game_server.connect() as db:
            before = db.execute("SELECT COALESCE(balance,0) FROM wallets WHERE account=?", (BUDGET,)).fetchone()
        self.at(12)
        self.view()
        with game_server.connect() as db:
            after = db.execute("SELECT COALESCE(balance,0) FROM wallets WHERE account=?", (BUDGET,)).fetchone()
        self.assertGreaterEqual((after or (0,))[0], (before or (0,))[0])


class TermLimitTests(RatingBase):
    def two_terms(self, who):
        with game_server.connect() as db:
            city.set_mayor(db, "?", who, who, 0, reason="test", now=self.now)
            city.set_mayor(db, "?", who, who, 12, reason="re-elected", now=self.now)

    def test_consecutive_terms_are_counted(self):
        self.two_terms("alice")
        with game_server.connect() as db:
            self.assertEqual(city.consecutive_terms(db, "?", "alice"), 2)
            self.assertEqual(city.consecutive_terms(db, "?", "bob"), 0)
            city.set_mayor(db, "?", "bob", "bob", 24, reason="term_ended", now=self.now)
            self.assertEqual(city.consecutive_terms(db, "?", "alice"), 0)           # a gap resets the count
            self.assertEqual(city.consecutive_terms(db, "?", "bob"), 1)

    def test_a_two_term_mayor_cannot_run_again(self):
        self.build("alice")
        self.two_terms("alice")
        with game_server.connect() as db:
            db.execute("UPDATE city_state SET term_end_month=24 WHERE id=1")
        self.at(20)
        e = self.view("alice")["election"]
        self.assertEqual(e["phase"], "registration")
        self.assertFalse(e["can_register"])
        self.assertTrue(e["term_limit_reached"])
        status, res = game_server.city_candidacy("alice", {"profit_tax": 0.1, "property_tax": 0.01})
        self.assertEqual((status, res["error"]), (403, "term_limit"))

    def test_a_first_term_mayor_may_seek_re_election(self):
        self.build("alice")
        with game_server.connect() as db:
            city.set_mayor(db, "?", "alice", "alice", 0, reason="test", now=self.now)
        self.at(8)
        self.assertTrue(self.view("alice")["election"]["can_register"])
        self.assertEqual(game_server.city_candidacy("alice", {"profit_tax": 0.1, "property_tax": 0.01})[0], 201)

    def test_others_are_not_limited(self):
        self.build("alice")
        self.build("bob")
        self.two_terms("alice")
        with game_server.connect() as db:
            db.execute("UPDATE city_state SET term_end_month=24 WHERE id=1")
        self.at(20)
        self.assertTrue(self.view("bob")["election"]["can_register"])

    def test_perks_show_the_terms_served(self):
        self.two_terms("alice")
        self.assertEqual(self.view()["perks"]["terms_served"], 2)


class IncumbentVoteTests(unittest.TestCase):
    cands = [{"owner": "inc", "profit_tax": 0.13, "social_share": 0.3}, {"owner": "rival", "profit_tax": 0.13, "social_share": 0.3}]

    def test_a_popular_mayor_wins_more_resident_votes(self):
        popular = city.resident_shares(self.cands, "inc", 0.0, 0.9, 12)["inc"]
        hated = city.resident_shares(self.cands, "inc", 0.0, 0.1, 12)["inc"]
        self.assertGreater(popular, hated)
        self.assertGreater(popular, 0.5)
        self.assertLess(hated, 0.5)


if __name__ == "__main__":
    unittest.main()
