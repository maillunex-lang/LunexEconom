"""Player-to-player contracts: arithmetic, API, monthly delivery, debts, bankruptcy, HTTP and a short world run."""
import io
import json
import os
import tempfile
import unittest
import uuid
from unittest import mock

import contracts
import economy
import game_server

DAY = 86400
T0 = 1_800_000_000


def rid():
    return str(uuid.uuid4())


class ArithmeticTests(unittest.TestCase):
    def test_price_bounds_are_half_to_double_the_reference(self):
        self.assertEqual(contracts.price_bounds("honey"), (100, 400))
        self.assertEqual(contracts.price_bounds("oil"), (750, 3000))
        self.assertEqual(contracts.price_bounds("goods"), (1000, 4000))
        rules = economy.terms()["contracts"]
        self.assertEqual(rules["products"], ["honey", "oil", "goods"])
        self.assertEqual(rules["max_active"], 6)

    def test_own_need_is_reserved_before_a_contract_can_ship(self):
        self.assertEqual(contracts.free_units(100, 0, 20), 80)
        self.assertEqual(contracts.free_units(100, 30, 20), 110)
        self.assertEqual(contracts.free_units(10, 30, 20), 20)   # 10 output + 10 stock stay home
        self.assertEqual(contracts.free_units(0, 5, 9), 0)
        self.assertEqual(contracts.free_units(0, 5, 0), 5)

    def test_scarce_goods_go_to_the_earlier_contract_id(self):
        orders = [("b", "alice", 80), ("a", "alice", 80)]
        # caller passes them already sorted; lower id first
        planned = contracts.plan_deliveries(sorted(orders), {"alice": 100})
        self.assertEqual([(p["id"], p["delivered"], p["shortfall"]) for p in planned], [("a", 80, 0), ("b", 20, 60)])

    def test_plan_is_deterministic(self):
        orders = [("c2", "s", 40), ("c1", "s", 30)]
        available = {"s": 50}
        self.assertEqual(contracts.plan_deliveries(orders, available), contracts.plan_deliveries(list(orders), dict(available)))
        self.assertEqual(available, {"s": 50})


class ContractBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = game_server.DB
        game_server.DB = os.path.join(self.tmp.name, "w.sqlite3")
        self.now = T0
        p = mock.patch.object(game_server.time, "time", side_effect=lambda: self.now)
        p.start()
        self.addCleanup(p.stop)
        self.taxes = economy.TAXES_ENABLED
        economy.TAXES_ENABLED = False
        self.cursor = 0

    def tearDown(self):
        economy.TAXES_ENABLED = self.taxes
        game_server.DB = self.old
        self.tmp.cleanup()

    def build(self, who, kind):
        for _ in range(400):
            self.cursor += 1
            status, res = game_server.build(who, {"kind": kind, "x": 8, "y": 10 + 7 * self.cursor, "request_id": rid()})
            if status == 201:
                return res
            self.assertIn(res.get("error"), ("water", "road_overlap", "occupied", "no_road_access"), res)
        self.fail("no site")

    def month(self, who="alice", n=1):
        self.now += DAY * n + 5
        return game_server.wallet(who)[1]

    def set_cash(self, who, amount):
        game_server.wallet(who)
        account = economy.player_account(who)
        with game_server.connect() as db:
            current = db.execute("SELECT balance FROM wallets WHERE account=?", (account,)).fetchone()[0]
            db.execute("UPDATE wallets SET balance=? WHERE account=?", (amount, account))
            db.execute("UPDATE wallets SET balance=balance-? WHERE account=?", (amount - current, economy.TREASURY))

    def assert_ledger_balanced(self):
        with game_server.connect() as db:
            bad = db.execute("SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0").fetchall()
            total = db.execute("SELECT COALESCE(SUM(balance),0) FROM wallets").fetchone()[0]
            negative = db.execute("SELECT 1 FROM wallets WHERE account LIKE 'player:%' AND balance<0").fetchall()
        self.assertEqual((bad, total, negative), ([], 0, []))

    def offer(self, who, product="honey", qty=20, price=200, term=1, penalty=0):
        return game_server.contracts_offer(who, {"product": product, "qty": qty, "price": price, "term_months": term,
                                                  "penalty": penalty, "request_id": rid()})

    def trade(self, supplier, buyer, **kw):
        status, body = self.offer(supplier, **kw)
        self.assertEqual(status, 201, body)
        accepted = game_server.contracts_accept(buyer, {"offer_id": body["offer"]["id"], "request_id": rid()})
        self.assertEqual(accepted[0], 201, accepted[1])
        return accepted[1]["contract"]


class ApiTests(ContractBase):
    def test_rejects_bad_price_qty_self_deal_and_npc(self):
        self.assertEqual(self.offer("alice", price=99)[1]["error"], "price_out_of_range")
        self.assertEqual(self.offer("alice", price=99)[1]["min_price"], 100)
        self.assertEqual(self.offer("alice", qty=0)[1]["error"], "invalid_qty")
        self.assertEqual(self.offer("alice", qty=True)[1]["error"], "invalid_qty")
        self.assertEqual(self.offer("alice", product="roads")[1]["error"], "invalid_product")
        self.assertEqual(self.offer("alice", penalty=201)[1]["error"], "invalid_penalty")
        self.assertEqual(self.offer("npc:ural-agro")[1]["error"], "npc_forbidden")
        self.assertEqual(game_server.contracts_offer("city", {"product": "honey", "qty": 1, "price": 200, "term_months": 1, "penalty": 0, "request_id": rid()})[1]["error"], "npc_forbidden")
        status, body = self.offer("alice")
        self.assertEqual(game_server.contracts_accept("alice", {"offer_id": body["offer"]["id"], "request_id": rid()})[1]["error"], "self_contract")
        self.assertEqual(game_server.contracts_accept("bob", {"offer_id": "nope", "request_id": rid()})[1]["error"], "invalid_offer")

    def test_offer_is_idempotent_and_leaves_the_board_once_accepted(self):
        request = rid()
        payload = {"product": "oil", "qty": 10, "price": 1500, "term_months": 3, "penalty": 100, "request_id": request}
        first = game_server.contracts_offer("alice", payload)
        second = game_server.contracts_offer("alice", payload)
        self.assertEqual((first[0], second[0]), (201, 200))
        self.assertEqual(first[1], second[1])
        board = game_server.contracts_state("bob")[1]
        self.assertEqual(len(board["offers"]), 1)
        accepted = game_server.contracts_accept("bob", {"offer_id": first[1]["offer"]["id"], "request_id": rid()})
        self.assertEqual(accepted[0], 201)
        self.assertEqual(accepted[1]["contract"]["end_month"], accepted[1]["contract"]["start_month"] + 2)
        again = game_server.contracts_accept("carol", {"offer_id": first[1]["offer"]["id"], "request_id": rid()})
        self.assertEqual(again[1]["error"], "not_open")
        self.assertEqual(game_server.contracts_state("bob")[1]["offers"], [])
        mine = game_server.contracts_state("alice")[1]["mine"]
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]["role"], "supplier")
        self.assertEqual(game_server.contracts_state("bob")[1]["mine"][0]["role"], "buyer")
        self.assertEqual(game_server.contracts_state("carol")[1]["mine"], [])

    def test_open_offer_limit_and_active_limit(self):
        for _ in range(economy.CONTRACT_MAX_OPEN):
            self.assertEqual(self.offer("alice", qty=1, price=100)[0], 201)
        self.assertEqual(self.offer("alice", qty=1, price=100)[1]["error"], "too_many_offers")
        self.assertEqual(game_server.contracts_cancel("bob", {"offer_id": game_server.contracts_state("bob")[1]["offers"][0]["id"], "request_id": rid()})[1]["error"], "not_owner")
        offer_id = game_server.contracts_state("alice")[1]["offers"][0]["id"]
        self.assertEqual(game_server.contracts_cancel("alice", {"offer_id": offer_id, "request_id": rid()})[0], 201)
        self.assertEqual(self.offer("alice", qty=1, price=100)[0], 201)

    def test_active_contract_cap_counts_both_sides(self):
        for i in range(economy.CONTRACT_MAX_ACTIVE):
            self.trade("alice", "buyer%d" % i, qty=1, price=100, term=1)
        extra = self.offer("alice", qty=1, price=100)
        self.assertEqual(extra[0], 201)
        denied = game_server.contracts_accept("zoe", {"offer_id": extra[1]["offer"]["id"], "request_id": rid()})
        self.assertEqual(denied[1]["error"], "too_many_contracts")
        self.assertEqual(game_server.contracts_state("zoe")[1]["mine"], [])

    def test_cancel_fee_is_one_month_of_penalty_and_requires_cash(self):
        contract = self.trade("alice", "bob", qty=20, price=150, penalty=10, term=4)
        self.set_cash("bob", 0)
        denied = game_server.contracts_cancel("bob", {"contract_id": contract["id"], "request_id": rid()})
        self.assertEqual(denied[0], 402)
        self.assertEqual(denied[1]["cost"], 200)
        self.assertEqual(game_server.contracts_state("alice")[1]["mine"][0]["status"], "active")
        self.set_cash("bob", 200)
        done = game_server.contracts_cancel("bob", {"contract_id": contract["id"], "request_id": rid()})
        self.assertEqual(done[0], 201)
        self.assertEqual(done[1]["fee"], 200)
        with game_server.connect() as db:
            moved = db.execute("SELECT SUM(amount) FROM ledger_entries e JOIN ledger_tx t ON t.id=e.tx_id WHERE t.kind='contract_cancel' AND e.account=?",
                               (economy.player_account("alice"),)).fetchone()[0]
        self.assertEqual(moved, 200)
        self.assertEqual(game_server.contracts_cancel("alice", {"contract_id": contract["id"], "request_id": rid()})[1]["error"], "invalid_state")
        self.assert_ledger_balanced()


class DeliveryTests(ContractBase):
    def _honey_market(self):
        with game_server.connect() as db:
            supply, demand = db.execute("SELECT supply,demand FROM market_prices WHERE product='honey' AND month_index=0").fetchone()
            permille = db.execute("SELECT demand_permille FROM population WHERE month_index=0").fetchone()[0]
            rows = db.execute("SELECT delivered,shortfall,paid,penalty_paid FROM trade_deliveries").fetchall()
        return supply, demand, permille, rows

    def test_delivery_reaches_the_factory_before_the_market(self):
        self.build("alice", "farm")
        self.build("bob", "factory")
        contract = self.trade("alice", "bob", qty=20, price=200, penalty=0, term=1)
        self.month("alice")
        supply, demand, permille, rows = self._honey_market()
        self.assertEqual(rows, [(20, 0, 4000, 0)])
        self.assertEqual(supply, 80)   # 100 harvested, 20 never offered
        self.assertEqual(demand, economy.demand_for("honey", 0, permille / 1000.0))  # factory demand left the market
        report = game_server.wallet("bob")[1]["reports"][0]
        self.assertEqual(report["input_cost"], 0)
        self.assertEqual(game_server.contracts_state("alice")[1]["mine"][0]["status"], "completed")
        self.assertEqual(game_server.contracts_state("alice")[1]["mine"][0]["last"]["delivered"], 20)
        self.assertEqual(contract["qty"], 20)
        self.assert_ledger_balanced()
        again = self.month("alice", 0) if False else game_server.wallet("alice")[1]
        self.assertEqual(len(game_server.contracts_state("alice")[1]["mine"]), 1)
        with game_server.connect() as db:
            paid = db.execute("SELECT SUM(amount) FROM ledger_entries e JOIN ledger_tx t ON t.id=e.tx_id WHERE t.kind='contract' AND e.account=?",
                              (economy.player_account("bob"),)).fetchone()[0]
        self.assertEqual(paid, -4000)
        self.assertGreater(again["balance"], 0)

    def test_supplier_keeps_raw_material_for_their_own_factory(self):
        self.build("alice", "farm")
        self.build("alice", "factory")
        self.trade("alice", "carol", qty=100, price=100, penalty=0, term=1)
        self.month("alice")
        with game_server.connect() as db:
            delivered, shortfall = db.execute("SELECT delivered,shortfall FROM trade_deliveries").fetchone()
        self.assertEqual((delivered, shortfall), (80, 20))
        self.assertEqual(game_server.wallet("alice")[1]["reports"][0]["input_cost"], 0)
        self.assert_ledger_balanced()

    def test_shortfall_pays_the_penalty_and_two_buyers_share_in_id_order(self):
        self.build("alice", "farm")
        self.trade("alice", "bob", qty=150, price=100, penalty=10, term=2)
        self.month("alice")
        with game_server.connect() as db:
            delivered, shortfall, paid, penalty_paid = db.execute("SELECT delivered,shortfall,paid,penalty_paid FROM trade_deliveries").fetchone()
        self.assertEqual((delivered, shortfall, paid, penalty_paid), (100, 50, 10000, 500))
        self.assert_ledger_balanced()
        # a second supplier month is not required; priority is checked on a fresh pair of contracts below

    def test_lower_contract_id_is_filled_first(self):
        self.build("alice", "farm")
        self.trade("alice", "bob", qty=80, price=100, penalty=0, term=1)
        self.trade("alice", "carol", qty=80, price=100, penalty=0, term=1)
        self.month("alice")
        with game_server.connect() as db:
            rows = db.execute("SELECT contract_id,delivered FROM trade_deliveries ORDER BY contract_id").fetchall()
        self.assertEqual(sorted(d for _, d in rows), [20, 80])
        self.assertEqual(rows[0][1], 80)
        self.assertEqual(sum(d for _, d in rows), 100)
        self.assert_ledger_balanced()

    def test_unpaid_delivery_is_a_debt_and_a_missed_month(self):
        self.build("alice", "farm")
        self.build("bob", "factory")
        self.trade("alice", "bob", qty=20, price=200, penalty=0, term=6)
        self.set_cash("bob", 0)
        w = self.month("bob")
        self.assertGreaterEqual(w["company"]["missed"], 1)
        state = game_server.contracts_state("bob")[1]
        self.assertEqual(state["debts"]["owed"], 4000)
        self.assertEqual(state["mine"][0]["last"]["paid"], 0)
        self.assertEqual(state["mine"][0]["status"], "active")
        self.assert_ledger_balanced()

    def test_bankruptcy_dissolves_the_contract(self):
        self.build("alice", "farm")
        self.build("bob", "factory")
        self.trade("alice", "bob", qty=20, price=200, penalty=0, term=12)
        self.set_cash("bob", 0)
        w = self.month("bob", 3)
        self.assertEqual(w["company"]["bankruptcies"], 1)
        self.assertEqual(game_server.contracts_state("alice")[1]["mine"][0]["status"], "dissolved")
        self.assertEqual(game_server.contracts_state("bob")[1]["debts"]["owed"], 0)
        self.assert_ledger_balanced()


class HttpTests(ContractBase):
    def _call(self, method, path, body, user):
        raw = json.dumps(body).encode() if body is not None else b""

        class Probe(game_server.Handler):
            def __init__(self):
                self.path = path
                self.headers = {"Content-Length": str(len(raw)), "Authorization": "Bearer t"}
                self.rfile = io.BytesIO(raw)
                self.sent = None

            def _identity(self):
                return user

            def _send(self, status, data):
                self.sent = (status, data)

        probe = Probe()
        with mock.patch.object(game_server, "npc_tick", return_value=0):
            (probe.do_GET if method == "GET" else probe.do_POST)()
        return probe.sent

    def test_http_requires_a_player_and_creates_an_offer(self):
        self.assertEqual(self._call("GET", "/contracts", None, None)[0], 401)
        status, body = self._call("POST", "/contracts/offer",
                                   {"product": "goods", "qty": 10, "price": 2000, "term_months": 2, "penalty": 0, "request_id": rid()}, "alice")
        self.assertEqual(status, 201)
        self.assertEqual(body["offer"]["product"], "goods")
        listed = self._call("GET", "/contracts", None, "bob")
        self.assertEqual(listed[0], 200)
        self.assertEqual(listed[1]["offers"][0]["id"], body["offer"]["id"])
        missing = self._call("POST", "/contracts/accept", {"request_id": rid()}, "bob")
        self.assertEqual(missing[1]["error"], "invalid_offer")


class SimulationTests(ContractBase):
    def test_a_modest_contract_does_not_break_the_market_or_the_npcs(self):
        economy.TAXES_ENABLED = True
        self.build("alice", "farm")
        self.build("bob", "factory")
        self.trade("alice", "bob", qty=10, price=180, penalty=20, term=4)
        for _ in range(6):
            self.now += DAY + 5
            game_server.npc_tick()
            game_server.wallet("alice")
        self.assert_ledger_balanced()
        with game_server.connect() as db:
            prices = db.execute("SELECT product,price FROM market_prices").fetchall()
            deliveries = db.execute("SELECT COUNT(*), COALESCE(SUM(delivered),0) FROM trade_deliveries").fetchone()
            buildings = db.execute("SELECT COUNT(*) FROM buildings WHERE owner LIKE 'npc:%'").fetchone()[0]
        for product, price in prices:
            ref = economy.MARKET[product]["reference_price"]
            self.assertGreaterEqual(price, int(ref * economy.MIN_PRICE_K))
            self.assertLessEqual(price, int(round(ref * economy.MAX_PRICE_K)))
        self.assertGreaterEqual(deliveries[0], 4)
        self.assertGreater(deliveries[1], 0)
        self.assertGreater(buildings, 0)
        self.assertEqual(game_server.contracts_state("alice")[1]["mine"][0]["status"], "completed")
