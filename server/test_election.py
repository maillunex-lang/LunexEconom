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


class ElectionBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = game_server.DB
        game_server.DB = os.path.join(self.tmp.name, "w.sqlite3")
        self.now = T0
        p = mock.patch.object(game_server.time, "time", side_effect=lambda: self.now)
        p.start()
        self.addCleanup(p.stop)
        self.cursor = 0
        game_server.city_state()          # creates the clock at T0 (month 0) and the default mayor

    def tearDown(self):
        game_server.DB = self.old
        self.tmp.cleanup()

    def at(self, month):
        self.now = T0 + month * DAY + 5

    def view(self, owner=None):
        return game_server.city_state(owner)[1]

    def build(self, who, kind="farm"):
        for _ in range(400):
            self.cursor += 1
            status, res = game_server.build(who, {"kind": kind, "x": 8, "y": 10 + 7 * self.cursor, "request_id": str(uuid.uuid4())})
            if status == 201:
                return res
        self.fail("no site")

    def set_cash(self, who, amount):
        """Set a wallet balance directly; the treasury absorbs the difference so the ledger stays closed."""
        game_server.wallet(who)
        account = economy.player_account(who)
        with game_server.connect() as db:
            current = db.execute("SELECT balance FROM wallets WHERE account=?", (account,)).fetchone()[0]
            db.execute("UPDATE wallets SET balance=? WHERE account=?", (amount, account))
            db.execute("UPDATE wallets SET balance=balance-? WHERE account=?", (amount - current, economy.TREASURY))

    def tycoon(self, who, factories=8):
        self.set_cash(who, 50_000_000)
        for _ in range(factories):
            self.build(who, "factory")

    def candidacy(self, who, profit=0.10, prop=0.015, slogan="x"):
        return game_server.city_candidacy(who, {"profit_tax": profit, "property_tax": prop, "slogan": slogan})

    def vote(self, who, candidate):
        return game_server.city_vote(who, {"candidate": candidate})

    def budget(self):
        with game_server.connect() as db:
            row = db.execute("SELECT balance FROM wallets WHERE account=?", (BUDGET,)).fetchone()
        return row[0] if row else 0

    def ledger_ok(self):
        with game_server.connect() as db:
            bad = db.execute("SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0").fetchall()
            total = db.execute("SELECT COALESCE(SUM(balance),0) FROM wallets").fetchone()[0]
            neg = db.execute("SELECT 1 FROM wallets WHERE account LIKE 'player:%' AND balance<0").fetchall()
        self.assertEqual((bad, total, neg), ([], 0, []))


class PhaseTests(unittest.TestCase):
    def test_phase_windows(self):
        self.assertEqual([city.phase(m, 12) for m in range(0, 13)],
                         ["idle"] * 8 + ["registration", "registration", "voting", "voting", "idle"])

    def test_term_is_twelve_months(self):
        self.assertEqual(economy.ELECTION_PERIOD, 12)
        self.assertEqual(economy.ELECTION_FEE, 50_000)


class ResidentVoteTests(unittest.TestCase):
    cands = [
        {"owner": "a", "profit_tax": 0.08, "social_share": 0.2},
        {"owner": "b", "profit_tax": 0.18, "social_share": 0.6},
    ]

    def test_shares_sum_to_one_and_are_deterministic(self):
        s = city.resident_shares(self.cands, "a", 0.3, 0.5, 12)
        self.assertAlmostEqual(sum(s.values()), 1.0)
        self.assertEqual(s, city.resident_shares(self.cands, "a", 0.3, 0.5, 12))

    def test_residents_reward_social_spending(self):
        s = city.resident_shares(self.cands, "none", 0.0, 0.0, 12)
        self.assertGreater(s["b"], s["a"])

    def test_unemployment_favours_low_taxes(self):
        calm = city.resident_shares(self.cands, "none", 0.0, 0.0, 12)
        hungry = city.resident_shares(self.cands, "none", 1.0, 0.0, 12)
        self.assertGreater(hungry["a"], calm["a"])

    def test_incumbent_is_rewarded_for_quality_of_life(self):
        bad = city.resident_shares(self.cands, "a", 0.0, 0.0, 12)
        good = city.resident_shares(self.cands, "a", 0.0, 1.0, 12)
        self.assertGreater(good["a"], bad["a"])


class RegistrationTests(ElectionBase):
    def test_only_in_the_registration_period(self):
        self.build("alice")
        self.assertEqual(self.candidacy("alice")[1]["error"], "not_registration_period")
        self.at(8)
        self.assertEqual(self.candidacy("alice")[0], 201)

    def test_npc_candidates_appear_when_registration_starts(self):
        self.assertEqual(self.view()["election"]["phase"], "idle")
        self.assertEqual(self.view()["election"]["candidates"], [])
        self.at(8)
        e = self.view()["election"]
        self.assertEqual(e["phase"], "registration")
        owners = {c["owner"] for c in e["candidates"]}
        self.assertEqual(owners, {"npc:growth-party", "npc:social-course", city.ADMIN})

    def test_fee_goes_to_the_budget_and_requires_money(self):
        self.build("alice")
        self.at(8)
        before = game_server.wallet("alice")[1]["balance"]
        b0 = self.budget()
        self.assertEqual(self.candidacy("alice")[0], 201)
        self.assertEqual(game_server.wallet("alice")[1]["balance"], before - economy.ELECTION_FEE)
        self.assertEqual(self.budget(), b0 + economy.ELECTION_FEE)
        self.ledger_ok()

    def test_poor_players_cannot_register(self):
        self.build("alice")
        self.at(8)
        self.set_cash("alice", 1000)          # after eight months of income the farm owner would otherwise afford the fee
        self.assertEqual(self.candidacy("alice")[1]["error"], "insufficient_funds")

    def test_must_run_a_business(self):
        self.at(8)
        self.assertEqual(self.candidacy("alice")[1]["error"], "no_company")

    def test_platform_must_respect_the_law(self):
        self.build("alice")
        self.at(8)
        self.assertEqual(self.candidacy("alice", 0.40, 0.01)[1]["error"], "out_of_limits")
        self.assertEqual(self.candidacy("alice", 0.10, 0.05)[1]["error"], "out_of_limits")
        self.assertEqual(self.candidacy("alice", "10", 0.01)[1]["error"], "invalid_rate")

    def test_only_one_registration_per_election(self):
        self.build("alice")
        self.at(8)
        self.assertEqual(self.candidacy("alice")[0], 201)
        self.assertEqual(self.candidacy("alice")[1]["error"], "already_registered")

    def test_view_tells_who_can_register(self):
        self.build("alice")
        self.at(8)
        self.assertTrue(self.view("alice")["election"]["can_register"])
        self.assertFalse(self.view("bob")["election"]["can_register"])          # no company
        self.candidacy("alice")
        e = self.view("alice")["election"]
        self.assertTrue(e["registered"])
        self.assertFalse(e["can_register"])

    def test_npcs_and_the_city_cannot_run(self):
        self.at(8)
        self.assertEqual(self.candidacy("npc:ural-agro")[0], 403)
        self.assertEqual(game_server.city_candidacy(economy.CITY, {"profit_tax": 0.1, "property_tax": 0.01})[0], 403)


class VotingTests(ElectionBase):
    def test_only_in_the_voting_period_for_known_candidates(self):
        self.build("alice")
        self.at(9)
        self.assertEqual(self.vote("alice", "npc:social-course")[1]["error"], "not_voting_period")
        self.at(10)
        self.assertEqual(self.vote("alice", "nobody")[1]["error"], "unknown_candidate")
        status, res = self.vote("alice", "npc:social-course")
        self.assertEqual(status, 200, res)
        self.assertEqual(self.view("alice")["election"]["my_vote"], "npc:social-course")

    def test_vote_can_be_changed_and_counts_once(self):
        self.build("alice")
        self.at(10)
        self.vote("alice", "npc:social-course")
        self.vote("alice", "npc:growth-party")
        self.assertEqual(self.view("alice")["election"]["my_vote"], "npc:growth-party")
        with game_server.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM election_votes").fetchone()[0], 1)

    def test_only_business_owners_vote_as_players(self):
        self.at(10)
        self.assertEqual(self.vote("bob", "npc:social-course")[1]["error"], "no_company")

    def test_vote_weight_grows_with_the_company(self):
        self.build("alice", "farm")
        self.build("bob", "factory")
        self.at(10)
        wa, wb = self.vote("alice", "npc:social-course")[1]["weight"], self.vote("bob", "npc:social-course")[1]["weight"]
        self.assertEqual(wa, 10 + 5 * 4)
        self.assertEqual(wb, 10 + 5 * 20)

    def test_npcs_do_not_vote(self):
        self.at(10)
        self.assertEqual(self.vote("npc:ural-agro", "npc:social-course")[0], 403)


class TallyTests(ElectionBase):
    def run_to_result(self):
        self.at(12)
        return self.view()

    def test_residents_decide_by_default_and_a_winner_takes_office(self):
        self.at(8)
        self.view()
        v = self.run_to_result()
        m = v["mayor"]
        self.assertNotEqual(m["since_month"], 0)
        self.assertEqual(m["since_month"], 12)
        self.assertEqual(m["term_end_month"], 24)
        self.assertIsNotNone(v["election"]["last_result"])
        self.assertEqual(v["election"]["last_result"]["winner"], m["owner"])
        tally = v["election"]["last_result"]["tally"]
        self.assertEqual([t["votes"] for t in tally], sorted([t["votes"] for t in tally], reverse=True))
        self.assertEqual(v["election"]["phase"], "idle")

    def test_the_winners_platform_becomes_policy(self):
        self.at(8)
        self.view()
        v = self.run_to_result()
        winner = next(t for t in v["election"]["last_result"]["tally"] if t["owner"] == v["mayor"]["owner"])
        promised = {c["owner"]: c for c in [dict(owner=x["owner"], profit=0, prop=0) for x in v["election"]["last_result"]["tally"]]}
        policy = {"npc:growth-party": 0.08, "npc:social-course": 0.18, city.ADMIN: 0.13}[winner["owner"]]
        self.assertEqual(v["taxes"]["profit_tax"], policy)

    def test_a_player_with_a_big_company_can_win(self):
        # one dominant business; residents are split between three NPC options
        self.tycoon("alice")
        self.at(8)
        self.candidacy("alice", 0.06, 0.01, "Бизнесу — зелёный свет")
        self.at(10)
        # the votes of the player (10 + 5*160 = 810) beat the whole population of ~200
        self.vote("alice", "alice")
        v = self.run_to_result()
        self.assertEqual(v["mayor"]["owner"], "alice")
        self.assertFalse(v["mayor"]["is_npc"])
        self.assertEqual(v["taxes"]["profit_tax"], 0.06)
        self.assertEqual(v["taxes"]["property_tax"], 0.01)

    def test_the_new_human_mayor_can_govern_at_once(self):
        self.tycoon("alice")
        self.at(8)
        self.candidacy("alice", 0.06, 0.01)
        self.at(10)
        self.vote("alice", "alice")
        self.at(12)
        self.view()
        status, res = game_server.city_taxes("alice", {"profit_tax": 0.07, "property_tax": 0.01})
        self.assertEqual(status, 200, res)
        self.assertEqual(game_server.city_taxes("bob", {"profit_tax": 0.07, "property_tax": 0.01})[1]["error"], "not_mayor")

    def test_the_old_mayor_loses_power(self):
        self.tycoon("alice")
        with game_server.connect() as db:
            city.set_mayor(db, "?", "bob", "bob", 0)
        self.at(8)
        self.candidacy("alice", 0.06, 0.01)
        self.at(10)
        self.vote("alice", "alice")
        self.at(12)
        self.view()
        self.assertEqual(game_server.city_taxes("bob", {"profit_tax": 0.07, "property_tax": 0.01})[1]["error"], "not_mayor")

    def test_nobody_running_extends_the_incumbents_term(self):
        with game_server.connect() as db:
            city.set_mayor(db, "?", "bob", "bob", 0)        # a human incumbent is not an automatic candidate
        self.at(8)
        self.view()
        e = self.view()["election"]
        self.assertNotIn("bob", [c["owner"] for c in e["candidates"]])
        self.at(12)
        v = self.view()
        self.assertIsNotNone(v["election"]["last_result"])

    def test_results_are_deterministic(self):
        def run(path):
            game_server.DB = path
            self.now = T0
            game_server.city_state()
            self.at(8)
            self.view()
            self.at(12)
            return self.view()["election"]["last_result"]
        a = run(os.path.join(self.tmp.name, "a.sqlite3"))
        b = run(os.path.join(self.tmp.name, "b.sqlite3"))
        self.assertEqual(a, b)

    def test_a_second_election_follows_one_term_later(self):
        self.at(8)
        self.view()
        self.at(12)
        v = self.view()
        self.assertEqual(v["election"]["election_month"], 24)
        self.at(20)
        self.assertEqual(self.view()["election"]["phase"], "registration")
        self.at(24)
        v = self.view()
        self.assertEqual(v["mayor"]["term_end_month"], 36)
        self.assertEqual(self.view()["election"]["last_result"]["election"], 24)

    def test_ledger_stays_balanced_through_an_election(self):
        self.build("alice")
        self.at(8)
        self.candidacy("alice")
        self.at(10)
        self.vote("alice", "alice")
        self.at(13)
        game_server.wallet("alice")
        self.ledger_ok()


if __name__ == "__main__":
    unittest.main()
