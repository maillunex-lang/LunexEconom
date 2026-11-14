"""Alliances, projects, messages, moderation, achievements and ranking on SQLite."""
import io
import json
import os
import tempfile
import threading
import unittest
import uuid
from unittest import mock

import economy
import game_server
import social

DAY = 86400
T0 = 1_800_000_000


def rid():
    return str(uuid.uuid4())


class NameTests(unittest.TestCase):
    def test_names_fold_case_and_invisible_characters(self):
        self.assertEqual(social.normalize_name("  Мёд   алтая "), "Мёд алтая")
        self.assertEqual(social.name_key("Мёд"), social.name_key("мёд"))
        self.assertEqual(social.name_key("М\u200bёд"), social.name_key("Мёд"))
        self.assertIsNone(social.normalize_name("ab"))
        self.assertIsNone(social.normalize_name("123"))
        self.assertIsNone(social.normalize_name("<b>Мёд</b>"))
        self.assertIsNone(social.normalize_name("a\x00b"))
        self.assertTrue(social.allow("window", 1, 60, now=1_000))
        self.assertFalse(social.allow("window", 1, 60, now=1_010))
        self.assertTrue(social.allow("window", 1, 60, now=1_060))
        social.reset_limits()


class SocialBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = game_server.DB
        game_server.DB = os.path.join(self.tmp.name, "w.sqlite3")
        self.now = T0
        patch = mock.patch.object(game_server.time, "time", side_effect=lambda: self.now)
        patch.start()
        self.addCleanup(patch.stop)
        self.taxes = economy.TAXES_ENABLED
        economy.TAXES_ENABLED = False
        social.reset_limits()
        self.limits = (social.ACTION_PER_MINUTE, social.MSG_PER_MINUTE, social.REPORT_PER_HOUR, social.IP_PER_MINUTE, social.MAX_MEMBERS)
        social.ACTION_PER_MINUTE = 10000
        social.MSG_PER_MINUTE = 10000
        social.REPORT_PER_HOUR = 10000
        social.IP_PER_MINUTE = 10000
        self.cursor = 0

    def tearDown(self):
        social.ACTION_PER_MINUTE, social.MSG_PER_MINUTE, social.REPORT_PER_HOUR, social.IP_PER_MINUTE, social.MAX_MEMBERS = self.limits
        economy.TAXES_ENABLED = self.taxes
        game_server.DB = self.old
        self.tmp.cleanup()

    def post(self, who, path, payload, client="10.0.0.4"):
        return game_server.soc_post(who, path, payload, client)

    def create(self, who="alice", name="Мёд Алтая"):
        return self.post(who, "/soc/alliance/create", {"name": name, "request_id": rid()})

    def ledger(self):
        with game_server.connect() as db:
            bad = db.execute("SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0").fetchall()
            total = db.execute("SELECT COALESCE(SUM(balance),0) FROM wallets").fetchone()[0]
            negative = db.execute("SELECT account,balance FROM wallets WHERE account LIKE 'player:%' AND balance<0").fetchall()
        self.assertEqual((bad, total, negative), ([], 0, []))


class AllianceTests(SocialBase):
    def test_create_is_unique_idempotent_and_rejects_outsiders(self):
        self.assertEqual(self.create("npc:ural-agro", "Чужие")[1]["error"], "npc_forbidden")
        self.assertEqual(self.create("alice", "аб")[1]["error"], "invalid_name")
        self.assertEqual(self.create("alice", "<b>Мёд</b>")[1]["error"], "invalid_name")
        request = rid()
        payload = {"name": "Мёд Алтая", "request_id": request}
        first = self.post("alice", "/soc/alliance/create", payload)
        second = self.post("alice", "/soc/alliance/create", payload)
        self.assertEqual((first[0], second[0]), (201, 200))
        self.assertEqual(first[1], second[1])
        self.assertEqual(first[1]["treasury"], social.CREATE_FEE)
        self.assertEqual(first[1]["balance"], economy.START_CAPITAL - social.CREATE_FEE)
        folded = self.create("bob", "мёд алтая")
        self.assertEqual(folded[1]["error"], "name_taken")
        hidden = self.create("bob", "М\u200bёд Алтая")
        self.assertEqual(hidden[1]["error"], "name_taken")
        self.assertEqual(self.create("alice", "Вторая")[1]["error"], "already_in_alliance")
        view = game_server.soc_get("alice", "/soc/alliance", {})
        self.assertEqual(view[1]["role"], "leader")
        self.assertEqual(view[1]["alliance"]["treasury"], social.CREATE_FEE)
        self.assertNotIn("email", json.dumps(view[1]).lower())
        listed = game_server.soc_get("bob", "/soc/alliances", {"q": ["мёд"]})
        self.assertEqual(listed[1]["alliances"][0]["name"], "Мёд Алтая")
        wildcard = game_server.soc_get("bob", "/soc/alliances", {"q": ["%"]})
        self.assertEqual(wildcard[1]["error"], "invalid_name")
        self.assertNotIn("treasury", listed[1]["alliances"][0])
        self.ledger()

    def test_member_cannot_spend_the_treasury_and_double_withdraw_pays_once(self):
        self.create()
        invite = self.post("alice", "/soc/alliance/invite", {"name": "bob", "request_id": rid()})
        self.assertEqual(self.post("bob", "/soc/alliance/accept", {"invite_id": invite[1]["invite_id"], "request_id": rid()})[0], 201)
        stolen = self.post("bob", "/soc/alliance/withdraw", {"amount": 1000, "request_id": rid()})
        self.assertEqual(stolen[1]["error"], "not_leader")
        self.assertEqual(self.post("carol", "/soc/alliance/contribute", {"amount": 1000, "request_id": rid()})[1]["error"], "not_member")
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
        treasury = game_server.soc_get("alice", "/soc/alliance", {})[1]["alliance"]["treasury"]
        self.assertEqual(treasury, 0)
        self.ledger()

    def test_one_player_cannot_join_two_alliances_at_once(self):
        self.create("alice", "Первый")
        self.create("bob", "Второй")
        left = self.post("alice", "/soc/alliance/invite", {"name": "carol", "request_id": rid()})
        right = self.post("bob", "/soc/alliance/invite", {"name": "carol", "request_id": rid()})
        barrier = threading.Barrier(2)
        results = []

        def accept(invite_id):
            barrier.wait()
            results.append(self.post("carol", "/soc/alliance/accept", {"invite_id": invite_id, "request_id": rid()}))

        threads = [threading.Thread(target=accept, args=(left[1]["invite_id"],)),
                   threading.Thread(target=accept, args=(right[1]["invite_id"],))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(item[0] for item in results), [201, 409])
        self.assertEqual(game_server.soc_get("carol", "/soc/alliance", {})[1]["alliance"]["members"], 2)
        with game_server.connect() as db:
            rows = db.execute("SELECT alliance_id FROM soc_membership WHERE owner='carol'").fetchall()
        self.assertEqual(len(rows), 1)
        self.ledger()

    def test_roles_kick_transfer_and_equal_split_with_remainder_to_the_leader(self):
        created = self.create()
        for name in ("bob", "carol"):
            invite = self.post("alice", "/soc/alliance/invite", {"name": name, "request_id": rid()})
            self.assertEqual(self.post(name, "/soc/alliance/accept", {"invite_id": invite[1]["invite_id"], "request_id": rid()})[0], 201)
        self.assertEqual(self.post("bob", "/soc/alliance/kick", {"name": "carol", "request_id": rid()})[1]["error"], "not_leader")
        self.assertEqual(self.post("alice", "/soc/alliance/kick", {"name": "carol", "request_id": rid()})[0], 201)
        self.assertIsNone(game_server.soc_get("carol", "/soc/alliance", {})[1]["alliance"])
        self.assertEqual(self.post("alice", "/soc/alliance/transfer", {"name": "bob", "request_id": rid()})[0], 201)
        self.assertEqual(game_server.soc_get("bob", "/soc/alliance", {})[1]["role"], "leader")
        # back to alice so the remainder assertion stays on the original leader after a second transfer
        self.assertEqual(self.post("bob", "/soc/alliance/transfer", {"name": "alice", "request_id": rid()})[0], 201)
        invite = self.post("alice", "/soc/alliance/invite", {"name": "carol", "request_id": rid()})
        self.post("carol", "/soc/alliance/accept", {"invite_id": invite[1]["invite_id"], "request_id": rid()})
        done = self.post("alice", "/soc/alliance/dissolve", {"request_id": rid()})
        self.assertEqual(done[0], 201, done[1])
        split = {item["name"]: item["amount"] for item in done[1]["split"]}
        self.assertEqual(sum(split.values()), social.CREATE_FEE)
        self.assertEqual(split["alice"], social.CREATE_FEE // 3 + social.CREATE_FEE % 3)
        self.assertEqual(split["bob"], social.CREATE_FEE // 3)
        self.assertIsNone(game_server.soc_get("alice", "/soc/alliance", {})[1]["alliance"])
        blocked = self.create("dave", "Мёд Алтая")
        self.assertEqual(blocked[1]["error"], "name_taken")
        self.ledger()

    def test_last_free_seat_accepts_only_one_applicant(self):
        social.MAX_MEMBERS = 2
        self.create()
        first = self.post("alice", "/soc/alliance/invite", {"name": "bob", "request_id": rid()})
        second = self.post("alice", "/soc/alliance/invite", {"name": "carol", "request_id": rid()})
        barrier = threading.Barrier(2)
        results = []

        def accept(who, invite_id):
            barrier.wait()
            results.append(self.post(who, "/soc/alliance/accept", {"invite_id": invite_id, "request_id": rid()}))

        threads = [threading.Thread(target=accept, args=("bob", first[1]["invite_id"])),
                   threading.Thread(target=accept, args=("carol", second[1]["invite_id"]))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(item[0] for item in results), [201, 409])
        self.assertEqual(game_server.soc_get("alice", "/soc/alliance", {})[1]["alliance"]["members"], 2)

    def test_rate_limit_blocks_the_third_action_and_replays_do_not_count(self):
        social.reset_limits()
        social.ACTION_PER_MINUTE = 2
        request = rid()
        payload = {"name": "Лимит", "request_id": request}
        self.assertEqual(self.post("alice", "/soc/alliance/create", payload)[0], 201)
        self.assertEqual(self.post("alice", "/soc/alliance/create", payload)[0], 200)
        self.assertEqual(self.post("alice", "/soc/alliance/contribute", {"amount": 1000, "request_id": rid()})[0], 201)
        blocked = self.post("alice", "/soc/alliance/contribute", {"amount": 1000, "request_id": rid()})
        self.assertEqual(blocked[0], 429)
        self.assertEqual(blocked[1]["error"], "rate_limited")

    def test_one_ip_cannot_flood_several_accounts(self):
        social.reset_limits()
        social.IP_PER_MINUTE = 2
        client = "203.0.113.9"
        self.assertEqual(self.post("alice", "/soc/alliance/create", {"name": "Альфа Север", "request_id": rid()}, client)[0], 201)
        self.assertEqual(self.post("bob", "/soc/alliance/create", {"name": "Бета Север", "request_id": rid()}, client)[0], 201)
        blocked = self.post("carol", "/soc/alliance/create", {"name": "Гамма Север", "request_id": rid()}, client)
        self.assertEqual((blocked[0], blocked[1]["error"]), (429, "rate_limited"))
        other = self.post("carol", "/soc/alliance/create", {"name": "Гамма Север", "request_id": rid()}, "203.0.113.10")
        self.assertEqual(other[0], 201)


class ProjectTests(SocialBase):
    def _farm(self, who="alice"):
        for _ in range(400):
            self.cursor += 1
            status, body = self.post(who, "/soc/project", {"kind": "farm", "x": 8, "y": 10 + 7 * self.cursor, "request_id": rid()})
            if status == 201:
                return body
            self.assertIn(body.get("error"), ("water", "road_overlap", "occupied", "no_road_access"), body)
        self.fail("no site")

    def test_cancel_returns_pledges_and_a_full_pledge_builds_for_the_alliance(self):
        self.create()
        self.post("alice", "/soc/alliance/invite", {"name": "bob", "request_id": rid()})
        invite = game_server.soc_get("bob", "/soc/alliance", {})[1]["invites"][0]["id"]
        self.post("bob", "/soc/alliance/accept", {"invite_id": invite, "request_id": rid()})
        opened = self._farm()
        project = opened["project"]
        self.assertGreaterEqual(project["cost"], economy.BUILD_COST["farm"])
        self.assertEqual((project["cost"] - economy.BUILD_COST["farm"]) % economy.ROAD_CELL_COST, 0)
        partial = self.post("bob", "/soc/project/pledge", {"project_id": project["id"], "amount": 1000, "request_id": rid()})
        self.assertEqual(partial[0], 201, partial[1])
        denied = self.post("carol", "/soc/project/pledge", {"project_id": project["id"], "amount": 1000, "request_id": rid()})
        self.assertEqual(denied[1]["error"], "not_member")
        cancelled = self.post("bob", "/soc/project/cancel", {"project_id": project["id"], "request_id": rid()})
        self.assertEqual(cancelled[1]["error"], "not_leader")
        self.assertEqual(self.post("alice", "/soc/project/cancel", {"project_id": project["id"], "request_id": rid()})[0], 201)
        self.assertEqual(game_server.wallet("bob")[1]["balance"], economy.START_CAPITAL)
        built = self._farm()
        project = built["project"]
        pledged = self.post("alice", "/soc/project/pledge", {"project_id": project["id"], "amount": project["cost"], "request_id": rid()})
        self.assertEqual(pledged[0], 201, pledged[1])
        self.assertTrue(pledged[1]["started"]["started"])
        owner = "alliance:" + pledged[1]["project"]["alliance_id"]
        with game_server.connect() as db:
            row = db.execute("SELECT owner FROM buildings WHERE id=?", (pledged[1]["started"]["object_id"],)).fetchone()
            shares = db.execute("SELECT COALESCE(SUM(amount),0) FROM soc_shares WHERE project_id=?", (project["id"],)).fetchone()[0]
            capital = db.execute("SELECT COUNT(*) FROM ledger_tx t JOIN ledger_entries e ON e.tx_id=t.id WHERE t.kind='start_capital' AND e.account=?",
                                 (economy.player_account(owner),)).fetchone()[0]
        self.assertEqual(row[0], owner)
        self.assertEqual(int(shares), project["cost"])
        self.assertEqual(capital, 0)
        self.now += DAY + 5
        state = game_server.soc_get("alice", "/soc/alliance", {})[1]
        with game_server.connect() as db:
            payout = db.execute("SELECT paid FROM soc_payouts").fetchone()
            report = db.execute("SELECT profit FROM company_reports WHERE owner=?", (owner,)).fetchone()
        self.assertIsNotNone(report)
        self.assertGreater(int(report[0]), 0)
        self.assertIsNotNone(payout)
        self.assertGreater(int(payout[0]), 0)
        self.assertGreater(state["alliance"]["treasury"], 0)
        self.ledger()

    def test_parallel_pledges_cannot_overfill_the_project(self):
        self.create()
        for name in ("bob",):
            invite = self.post("alice", "/soc/alliance/invite", {"name": name, "request_id": rid()})
            self.post(name, "/soc/alliance/accept", {"invite_id": invite[1]["invite_id"], "request_id": rid()})
        project = self._farm()["project"]
        amount = project["cost"]
        barrier = threading.Barrier(2)
        results = []

        def give(who):
            barrier.wait()
            results.append(self.post(who, "/soc/project/pledge", {"project_id": project["id"], "amount": amount, "request_id": rid()}))

        threads = [threading.Thread(target=give, args=("alice",)), threading.Thread(target=give, args=("bob",))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(item[0] for item in results), [201, 409])
        started = [item for item in results if item[0] == 201][0][1]["started"]["started"]
        self.assertTrue(started)
        with game_server.connect() as db:
            pledged = db.execute("SELECT pledged,status FROM soc_projects WHERE id=?", (project["id"],)).fetchone()
        self.assertEqual(int(pledged[0]), amount)
        self.assertEqual(pledged[1], "active")
        self.ledger()

    def test_dissolve_sells_the_joint_building_and_the_ledger_stays_closed(self):
        self.create()
        project = self._farm()["project"]
        pledged = self.post("alice", "/soc/project/pledge", {"project_id": project["id"], "amount": project["cost"], "request_id": rid()})
        self.assertTrue(pledged[1]["started"]["started"], pledged[1])
        done = self.post("alice", "/soc/alliance/dissolve", {"request_id": rid()})
        self.assertEqual(done[0], 201, done[1])
        sale = int(economy.BUILD_COST["farm"] * economy.SELL_RATE)
        self.assertEqual(sum(item["amount"] for item in done[1]["split"]), social.CREATE_FEE + sale)
        with game_server.connect() as db:
            left = db.execute("SELECT COUNT(*) FROM buildings WHERE owner LIKE 'alliance:%'").fetchone()[0]
        self.assertEqual(int(left), 0)
        self.ledger()


class MessageTests(SocialBase):
    def test_inbox_blocks_markup_and_keeps_only_the_latest_messages(self):
        self.create()
        denied = self.post("alice", "/soc/message", {"to": "bob", "body": "<b>привет</b>", "request_id": rid()})
        self.assertEqual(denied[1]["error"], "invalid_text")
        self.assertEqual(self.post("alice", "/soc/message", {"to": "bob", "body": "x" * 301, "request_id": rid()})[1]["error"], "invalid_text")
        self.assertEqual(self.post("alice", "/soc/message", {"to": "alice", "body": "себе", "request_id": rid()})[1]["error"], "invalid_name")
        sent = self.post("alice", "/soc/message", {"to": "bob", "body": "  Привет, партнёр  ", "request_id": rid()})
        self.assertEqual(sent[0], 201, sent[1])
        inbox = game_server.soc_get("bob", "/soc/inbox", {"after": ["0"]})
        self.assertEqual(inbox[1]["messages"][0]["name"], "alice")
        self.assertEqual(inbox[1]["messages"][0]["body"], "Привет, партнёр")
        self.assertNotIn("@", json.dumps(inbox[1]))
        self.post("bob", "/soc/block", {"name": "alice", "request_id": rid()})
        blocked = self.post("alice", "/soc/message", {"to": "bob", "body": "ещё", "request_id": rid()})
        self.assertEqual(blocked[1]["error"], "blocked")
        invite = self.post("alice", "/soc/alliance/invite", {"name": "bob", "request_id": rid()})
        self.assertEqual(invite[1]["error"], "blocked")
        self.post("bob", "/soc/unblock", {"name": "alice", "request_id": rid()})
        social.MSG_KEEP = 3
        try:
            for i in range(5):
                self.assertEqual(self.post("alice", "/soc/message", {"to": "carol", "body": "n%d" % i, "request_id": rid()})[0], 201)
        finally:
            social.MSG_KEEP = 50
        rows = game_server.soc_get("carol", "/soc/inbox", {"after": ["0"]})[1]["messages"]
        own = [m for m in rows if m["name"] == "alice"]
        self.assertEqual([m["body"] for m in own], ["n2", "n3", "n4"])
        after = own[-2]["id"]
        newer = game_server.soc_get("carol", "/soc/inbox", {"after": [str(after)]})[1]["messages"]
        self.assertEqual([m["body"] for m in newer], ["n4"])
        social.reset_limits()
        social.MSG_PER_MINUTE = 1
        self.assertEqual(self.post("alice", "/soc/message", {"to": "dave", "body": "раз", "request_id": rid()})[0], 201)
        limited = self.post("alice", "/soc/message", {"to": "dave", "body": "два", "request_id": rid()})
        self.assertEqual(limited[0], 429)

    def test_alliance_chat_and_reports(self):
        created = self.create()
        aid = created[1]["alliance"]["id"]
        self.assertEqual(self.post("bob", "/soc/message", {"alliance": aid, "body": "чужой", "request_id": rid()})[1]["error"], "not_member")
        self.assertEqual(self.post("alice", "/soc/message", {"alliance": aid, "body": "Сбор", "request_id": rid()})[0], 201)
        self.assertEqual(game_server.soc_get("alice", "/soc/inbox", {})[1]["messages"][-1]["body"], "Сбор")
        self.assertEqual(self.post("alice", "/soc/report", {"name": "bob", "reason": "no", "request_id": rid()})[1]["error"], "invalid_text")
        self.assertEqual(self.post("alice", "/soc/report", {"name": "bob", "reason": "<b>спам</b>", "request_id": rid()})[1]["error"], "invalid_text")
        filed = self.post("alice", "/soc/report", {"name": "bob", "reason": "Спам в чате", "request_id": rid()})
        self.assertEqual(filed[0], 201)
        with game_server.connect() as db:
            reason = db.execute("SELECT reason FROM soc_reports").fetchone()[0]
        self.assertEqual(reason, "Спам в чате")
        social.reset_limits()
        social.REPORT_PER_HOUR = 1
        self.assertEqual(self.post("alice", "/soc/report", {"name": "carol", "reason": "Второй сигнал", "request_id": rid()})[0], 201)
        again = self.post("alice", "/soc/report", {"name": "dave", "reason": "Третий сигнал", "request_id": rid()})
        self.assertEqual(again[0], 429)

    def test_http_requires_a_player(self):
        raw = json.dumps({"name": "Сеть", "request_id": rid()}).encode()

        class Probe(game_server.Handler):
            def __init__(self):
                self.path = "/soc/alliance/create"
                self.headers = {"Content-Length": str(len(raw)), "Authorization": "Bearer t"}
                self.rfile = io.BytesIO(raw)
                self.sent = None

            def _identity(self):
                return self.user

            def _client(self):
                return "10.9.9.9"

            def _send(self, status, data):
                self.sent = (status, data)

        probe = Probe()
        probe.user = None
        with mock.patch.object(game_server, "npc_tick", return_value=0):
            probe.do_POST()
        self.assertEqual(probe.sent[0], 401)
        probe.rfile = io.BytesIO(raw)
        probe.user = "alice"
        with mock.patch.object(game_server, "npc_tick", return_value=0):
            probe.do_POST()
        self.assertEqual(probe.sent[0], 201)


class AchievementRankTests(SocialBase):
    def test_achievements_are_idempotent_and_pay_nothing(self):
        self.create()
        before = game_server.wallet("alice")[1]["balance"]
        first = game_server.soc_get("alice", "/soc/achievements", {})
        second = game_server.soc_get("alice", "/soc/achievements", {})
        earned = {item["code"]: item["earned"] for item in first[1]["achievements"]}
        self.assertTrue(earned["alliance_member"])
        self.assertFalse(earned["exchange_deal"])
        self.assertEqual(first[1]["achievements"], second[1]["achievements"])
        self.assertEqual(game_server.wallet("alice")[1]["balance"], before)
        rank = game_server.soc_get("bob", "/soc/alliance-ranking", {"by": ["capital"]})
        self.assertEqual(rank[0], 200)
        self.assertEqual(rank[1]["top"][0]["name"], "Мёд Алтая")
        self.assertGreater(rank[1]["top"][0]["capital"], 0)
        self.assertEqual(game_server.soc_get("bob", "/soc/alliance-ranking", {"by": ["nope"]})[1]["error"], "invalid_sort")
        self.ledger()
