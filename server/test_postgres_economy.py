"""Economy on a real PostgreSQL 16 (disposable lunex_ci database only): roads, ledger, production chain, labour,
market, bankruptcy, selling, loans, NPC competitors and concurrency. Mirrors the SQLite suites at scenario level."""
import os
import threading
import unittest
import uuid
from unittest import mock

DAY = 86400
T0 = 1_800_000_000

ENABLED = os.environ.get("LUNEX_DB_ENGINE") == "postgres" and os.environ.get("LUNEX_PG_DB") == "lunex_ci"

if ENABLED:
    import economy
    import game_server          # with LUNEX_DB_ENGINE=postgres this module is wired to the PostgreSQL backend
    import npc
    import postgres_db
    import postgres_world


def rid():
    return str(uuid.uuid4())


@unittest.skipUnless(ENABLED, "requires isolated lunex_ci PostgreSQL database")
class PostgresEconomyTests(unittest.TestCase):
    def setUp(self):
        postgres_db.init()
        with postgres_db.connect() as db:
            names = [r[0] for r in db.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'").fetchall()]
            keep = {"users", "sessions", "auth_attempts", "auth_tokens", "email_verified"}
            db.execute("TRUNCATE TABLE " + ",".join(sorted(n for n in names if n not in keep)) + " RESTART IDENTITY CASCADE")
        self.now = T0
        p = mock.patch.object(game_server.time, "time", side_effect=lambda: self.now)
        p.start()
        self.addCleanup(p.stop)
        self.cursor = 0

    # ---- helpers
    def build(self, who, kind):
        for _ in range(400):
            self.cursor += 1
            status, res = postgres_world.build(who, {"kind": kind, "x": 8, "y": 10 + 7 * self.cursor, "request_id": rid()})
            if status == 201:
                return res
            self.assertIn(res.get("error"), ("water", "road_overlap", "occupied", "no_road_access"), res)
        self.fail("no free site")

    def wallet(self, who):
        return postgres_world.wallet(who)[1]

    def month(self, who="alice", n=1):
        self.now += DAY * n + 5
        return self.wallet(who)

    def sql(self, query, params=()):
        with postgres_db.connect() as db:
            cur = db.execute(query, params)
            try:
                return cur.fetchall()
            except Exception:
                return None

    def set_cash(self, who, amount):
        self.wallet(who)
        account = economy.player_account(who)
        with postgres_db.connect() as db:
            current = db.execute("SELECT balance FROM wallets WHERE account=%s", (account,)).fetchone()[0]
            db.execute("UPDATE wallets SET balance=%s WHERE account=%s", (amount, account))
            db.execute("UPDATE wallets SET balance=balance-%s WHERE account=%s", (amount - current, economy.TREASURY))

    def assert_ledger(self):
        bad = self.sql("SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0")
        total = self.sql("SELECT COALESCE(SUM(balance),0) FROM wallets")[0][0]
        negative = self.sql("SELECT 1 FROM wallets WHERE account LIKE 'player:%%' AND balance<0")
        self.assertEqual((bad, total, negative), ([], 0, []))

    # ---- scenarios
    def test_schema_has_every_economy_table(self):
        names = {r[0] for r in self.sql("SELECT tablename FROM pg_tables WHERE schemaname='public'")}
        for table in ("wallets", "ledger_tx", "ledger_entries", "building_ops", "market_prices", "world_state", "inventory",
                      "company_reports", "company_status", "population", "loans", "npc_state", "roads", "world_clock"):
            self.assertIn(table, names)

    def test_build_far_from_road_lays_a_road_and_charges(self):
        res = self.build("alice", "farm")
        self.assertGreater(res["road_cells"], 0)
        self.assertEqual(res["cost"], 120_000 + 5_000 * res["road_cells"])
        self.assertEqual(res["balance"], 1_000_000 - res["cost"])
        kinds = [e["kind"] for e in res["events"]]
        self.assertIn("building_created", kinds)
        self.assertIn("road_changed", kinds)
        snapshot = []
        for cx in range(-1, 2):
            for cy in range(-1, 2):
                snapshot += postgres_world.chunk(cx, cy)[1]["cells"]
        self.assertEqual(sum(1 for c in snapshot if c["kind"] == "road_changed"), res["road_cells"])
        self.assert_ledger()

    def test_idempotent_build_and_occupied_cells(self):
        rq = rid()
        payload = {"kind": "farm", "x": 8, "y": 10, "request_id": rq}
        a = postgres_world.build("alice", payload)
        b = postgres_world.build("alice", payload)
        self.assertEqual((a[0], b[0]), (201, 200))
        self.assertEqual(a[1], b[1])
        self.assertEqual(postgres_world.build("bob", dict(payload, request_id=rid()))[1]["error"], "occupied")
        self.assertEqual(self.wallet("bob")["balance"], 1_000_000)

    def test_monthly_settlement_pays_income_and_records_market_labour(self):
        self.build("alice", "farm")
        w = self.month("alice", 3)
        self.assertEqual(len(w["reports"]), 3)
        self.assertGreater(w["reports"][0]["revenue"], 0)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM market_prices WHERE product='honey'")[0][0], 3)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM population")[0][0], 3)
        self.assertEqual(self.sql("SELECT processed_through FROM world_state")[0][0], 2)
        self.assertEqual(w["labor"]["jobs"], 4)
        self.assert_ledger()
        again = self.wallet("alice")
        self.assertEqual(again["balance"], w["balance"])          # idempotent

    def test_production_chain_and_warehouse(self):
        for who, kind in (("bob", "farm"), ("carol", "mine"), ("alice", "factory"), ("alice", "warehouse")):
            self.build(who, kind)
        w = self.month("alice", 4)
        goods = self.sql("SELECT supply,price FROM market_prices WHERE product='goods' ORDER BY month_index")
        self.assertTrue(any(s > 0 for s, _ in goods))
        self.assertGreater(w["reports"][0]["revenue"], 0)
        self.assertEqual(w["inventory"]["capacity"], 400)
        self.assert_ledger()

    def test_taxes_flow_into_the_city_budget(self):
        no_roads = mock.patch.object(economy, "ROAD_MAINTENANCE", 0)       # road upkeep is tested separately
        no_roads.start()
        self.addCleanup(no_roads.stop)
        self.build("alice", "farm")
        w = self.month("alice", 2)
        budget = self.sql("SELECT balance FROM wallets WHERE account=%s", (economy.player_account(economy.CITY),))[0][0]
        self.assertGreater(budget, 0)
        self.assertEqual(w["taxes"]["profit_tax"], 0.13)
        self.assertEqual(w["taxes"]["vat"]["honey"], 0.10)
        self.assertTrue(all(r["tax"] > 0 for r in w["reports"]))
        paid = self.sql("SELECT SUM(paid) FROM company_taxes WHERE owner='alice'")[0][0]
        self.assertEqual(paid, budget)
        self.assert_ledger()

    def test_tax_policy_row_changes_the_rates(self):
        self.sql("INSERT INTO city_policy(id,profit_tax_permille,property_tax_permille,social_share_permille,changed_month) VALUES(1,50,0,300,0)")
        self.assertEqual(postgres_world.market_state()[1]["taxes"]["profit_tax"], 0.05)
        self.assertEqual(postgres_world.market_state()[1]["taxes"]["property_tax"], 0.0)

    def fund_budget(self, amount):
        postgres_world.city_state()
        with postgres_db.connect() as db:
            economy.ensure_wallet(db, "%s", economy.CITY, self.now)
            economy.post(db, "%s", "test", "funding", [(economy.TREASURY, -amount), (economy.player_account(economy.CITY), amount)], self.now)

    def test_city_government_taxes_and_social_buildings(self):
        v = postgres_world.city_state()[1]
        self.assertEqual(v["mayor"]["owner"], "npc:administration")
        self.assertEqual(postgres_world.city_taxes("alice", {"profit_tax": 0.10, "property_tax": 0.01})[1]["error"], "not_mayor")
        self.wallet("alice")
        with postgres_db.connect() as db:
            db.execute("UPDATE city_state SET mayor='alice',mayor_name='alice' WHERE id=1")
        status, res = postgres_world.city_taxes("alice", {"profit_tax": 0.10, "property_tax": 0.01})
        self.assertEqual(status, 200, res)
        self.assertEqual(postgres_world.city_taxes("alice", {"profit_tax": 0.12, "property_tax": 0.01})[1]["error"], "cooldown")
        self.assertEqual(postgres_world.city_taxes("alice", {"profit_tax": 0.40, "property_tax": 0.01})[1]["error"], "out_of_limits")
        self.now += DAY + 5
        self.assertEqual(postgres_world.city_taxes("alice", {"profit_tax": 0.12, "property_tax": 0.01})[0], 200)
        # social building: only the mayor, only the city, paid from the budget
        self.assertEqual(postgres_world.build("alice", {"kind": "school", "x": 8, "y": 10, "request_id": rid()})[1]["error"], "social_only_for_city")
        self.assertEqual(postgres_world.city_build("alice", {"kind": "school", "x": 8, "y": 10, "request_id": rid()})[1]["error"], "insufficient_funds")
        self.fund_budget(1_000_000)
        self.cursor = 0
        for _ in range(60):
            self.cursor += 1
            status, res = postgres_world.city_build("alice", {"kind": "school", "x": 8, "y": 10 + 7 * self.cursor, "request_id": rid()})
            if status == 201:
                break
        self.assertEqual(status, 201, res)
        v = postgres_world.city_state()[1]
        self.assertEqual(v["social"]["counts"]["school"], 1)
        self.assertLess(v["budget"], 1_000_000)
        self.month("alice", 3)
        v = postgres_world.city_state()[1]
        self.assertGreaterEqual(v["budget"], 0)
        self.assert_ledger()

    def test_administration_builds_social_buildings_on_postgres(self):
        game_server.npc_tick()
        self.fund_budget(3_000_000)
        for _ in range(4):
            self.now += DAY + 5
            game_server.npc_tick()
        self.assertGreater(len(postgres_world.city_state()[1]["buildings"]), 0)
        self.assert_ledger()

    def test_selling_a_building(self):
        res = self.build("alice", "farm")
        before = self.wallet("alice")["balance"]
        status, out = postgres_world.sell("alice", {"object_id": res["object_id"], "request_id": rid()})
        self.assertEqual((status, out["price"]), (201, 60_000))
        self.assertEqual(out["balance"], before + 60_000)
        self.assertEqual(postgres_world.sell("bob", {"object_id": res["object_id"], "request_id": rid()})[0], 404)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM cells")[0][0], 0)
        kinds = [e["kind"] for e in postgres_world.events(0)[1]["events"]]
        self.assertIn("building_removed", kinds)
        self.assert_ledger()

    def test_only_the_owner_can_sell(self):
        res = self.build("alice", "farm")
        self.assertEqual(postgres_world.sell("bob", {"object_id": res["object_id"], "request_id": rid()})[0], 403)

    def test_loans_interest_and_default(self):
        self.build("alice", "factory")
        self.assertEqual(postgres_world.loan("alice", {"action": "take", "amount": 100_000, "request_id": rid()})[0], 201)
        self.assertEqual(postgres_world.loan("alice", {"action": "take", "amount": 900_000, "request_id": rid()})[1]["error"], "limit_exceeded")
        w = self.month("alice", 2)
        self.assertEqual(w["loan"]["balance"], 100_000)
        self.assertGreater(self.sql("SELECT interest_paid FROM loans WHERE owner='alice'")[0][0], 0)
        self.set_cash("alice", 0)
        w = self.month("alice", 1)
        self.assertTrue(w["loan"]["in_default"])
        self.assertEqual(postgres_world.loan("alice", {"action": "take", "amount": 10_000, "request_id": rid()})[1]["error"], "in_default")
        self.assert_ledger()

    def test_bankruptcy_liquidates_and_tells_clients(self):
        self.build("alice", "factory")
        self.set_cash("alice", 60_000)
        w = self.month("alice", 6)
        self.assertEqual(w["company"]["bankruptcies"], 1)
        self.assertEqual(w["holdings"], {})
        self.assertEqual(self.sql("SELECT COUNT(*) FROM buildings")[0][0], 0)
        events = postgres_world.events(0)[1]["events"]
        versions = {}
        for e in events:
            key = (e["cx"], e["cy"])
            self.assertEqual(e["version"], versions.get(key, 0) + 1)
            versions[key] = e["version"]
        self.assertIn("building_removed", [e["kind"] for e in events])
        self.assert_ledger()

    def test_npc_competitors_act_on_postgres(self):
        game_server.npc_tick()
        for _ in range(8):
            self.now += DAY + 5
            game_server.npc_tick()
        data = postgres_world.market_state()[1]
        self.assertEqual([c["name"] for c in data["competitors"]], [p["name"] for p in npc.PERSONAS])
        self.assertGreater(sum(c["buildings"] for c in data["competitors"]), 0)
        self.assertIn("labor", data)
        self.assert_ledger()

    def test_concurrent_builds_on_one_site_yield_one_building(self):
        results = []

        def attempt(who):
            results.append(postgres_world.build(who, {"kind": "farm", "x": 8, "y": 10, "request_id": rid()})[0])
        threads = [threading.Thread(target=attempt, args=("racer%d" % i,)) for i in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(results).count(201), 1, results)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM buildings")[0][0], 1)
        self.assert_ledger()

    def test_clock_is_continuous_when_month_length_changes(self):
        postgres_world.clock_state()
        self.now += DAY * 3 + 100
        self.assertEqual(postgres_world.clock_state()["month_index"], 3)
        with mock.patch.dict(os.environ, {"LUNEX_MONTH_SECONDS": "600"}):
            self.assertEqual(postgres_world.clock_state()["month_index"], 3)
            self.now += 1250
            self.assertEqual(postgres_world.clock_state()["month_index"], 5)


if __name__ == "__main__":
    unittest.main()
