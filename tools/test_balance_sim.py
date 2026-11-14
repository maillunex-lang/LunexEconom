"""Короткий прогон симулятора баланса: инварианты, детерминизм, длина месяца."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import balance_sim


def _strip_timing(row):
    return balance_sim.economic_tuple(row)


class DetectorTests(unittest.TestCase):
    def _row(self, month, **over):
        row = {key: 0 for key in balance_sim.METRIC_FIELDS}
        row.update({
            "month": month, "honey_price": 200, "oil_price": 1500, "goods_price": 2000,
            "population": 200, "next_population": 202, "step_ms": 1.0, "tick_ms": 1.0,
            "processed_through": month,
        })
        row.update(over)
        return row

    def test_whipsaw_and_mass_default_are_not_a_stuck_price(self):
        rows = []
        for month in range(8):
            rows.append(self._row(month, honey_price=500 if month % 2 else 80, honey_supply=0 if month % 2 else 400))
        flags = balance_sim.analyze(rows, pin_months=6)
        codes = {flag["code"] for flag in flags}
        self.assertIn("price_whipsaw", codes)
        self.assertNotIn("price_pin", codes)
        self.assertTrue(any("предложение на рынке 0" in flag["detail"] for flag in flags if flag["code"] == "price_whipsaw"))
        calm = [self._row(month, honey_price=200) for month in range(8)]
        self.assertFalse(any(flag["code"] == "price_whipsaw" for flag in balance_sim.analyze(calm)))
        burst = [self._row(1, bankrupt_this_month=3)]
        self.assertEqual(balance_sim.analyze(burst)[0]["code"], "mass_default")
        rows = [self._row(i, honey_price=50) for i in range(8)]
        flags = balance_sim.analyze(rows, pin_months=6, step_budget_ms=100, pop_cap=1600)
        self.assertTrue(any(flag["code"] == "price_pin" and flag["metric"] == "honey_price" for flag in flags))
        self.assertEqual(balance_sim.row_invariants(rows[0]), [])

    def test_population_floor_explode_and_wipe(self):
        low = [self._row(i, population=balance_sim.economy.MIN_POPULATION, next_population=balance_sim.economy.MIN_POPULATION)
               for i in range(6)]
        flags = balance_sim.analyze(low, pin_months=6)
        self.assertTrue(any(flag["code"] == "population_floor" for flag in flags))
        boom = [self._row(3, next_population=balance_sim.DEFAULT_POP_CAP + 1)]
        self.assertTrue(any(flag["code"] == "population_explode" for flag in balance_sim.analyze(boom)))
        wiped = [self._row(4, npc_broke=len(balance_sim.npc.PERSONAS))]
        self.assertEqual(balance_sim.analyze(wiped)[0]["code"], "npc_wiped")

    def test_slow_step_open_loop_and_city_deficit(self):
        rows = [self._row(1, step_ms=800, market=-10, residents=10, city_budget=-1)]
        flags = balance_sim.analyze(rows, step_budget_ms=500)
        codes = {flag["code"] for flag in flags}
        self.assertIn("slow_step", codes)
        self.assertIn("open_loop", codes)
        self.assertTrue(any("бюджет города" in item for item in balance_sim.row_invariants(rows[0])))

    def test_money_from_nothing_is_an_invariant(self):
        row = self._row(2, ledger_sum=5, wallet_sum=0, unbalanced_tx=1)
        self.assertTrue(any("деньги из воздуха" in item for item in balance_sim.row_invariants(row)))
        stock = self._row(2, negative_stock=1, negative_players=1, negative_accounts=["player:alice"])
        text = " ".join(balance_sim.row_invariants(stock))
        self.assertIn("отрицательный запас", text)
        self.assertIn("отрицательные деньги", text)


class ScenarioTests(unittest.TestCase):
    def test_npc_24_months_keep_invariants_and_repeat(self):
        first = balance_sim.run_scenario(months=24, seed=20261114, npc_on=True, strategies=())
        second = balance_sim.run_scenario(months=24, seed=20261114, npc_on=True, strategies=())
        self.assertEqual(len(first["rows"]), 24)
        self.assertEqual(first["invariants"], [])
        self.assertEqual(second["invariants"], [])
        self.assertEqual(first["digest"], second["digest"])
        self.assertEqual([_strip_timing(row) for row in first["rows"]], [_strip_timing(row) for row in second["rows"]])
        last = first["rows"][-1]
        self.assertGreater(last["buildings"], 0)
        self.assertGreaterEqual(last["population"], balance_sim.economy.MIN_POPULATION)
        self.assertEqual(last["wallet_sum"], 0)
        self.assertEqual(last["ledger_sum"], 0)
        # Residents spend their wages (system:residents -> system:market): no hoarded wages, so no open_loop flag.
        self.assertFalse(any(flag["code"] == "open_loop" for flag in first["flags"]))
        self.assertLess(last["residents"], 1_000_000)
        for row in first["rows"]:
            for product in ("honey", "oil", "goods"):
                floor, ceil = balance_sim.price_limits(product)
                self.assertGreaterEqual(row[product + "_price"], floor)
                self.assertLessEqual(row[product + "_price"], ceil)

    def test_bots_are_deterministic_and_do_not_break_the_books(self):
        kwargs = dict(months=12, seed=11, npc_on=True, strategies=("rotate", "hoard", "loan", "idle"), build_cap=6)
        first = balance_sim.run_scenario(**kwargs)
        second = balance_sim.run_scenario(**kwargs)
        self.assertEqual(first["invariants"], [])
        self.assertEqual(first["digest"], second["digest"])
        self.assertGreater(first["builds_ok"], 0)
        by_name = {bot["name"]: bot for bot in first["bots"]}
        self.assertEqual(by_name["idl03"]["built"], 0)
        self.assertGreaterEqual(by_name["hor01"]["built"], 1)
        self.assertGreaterEqual(by_name["rot00"]["built"], 1)
        idle = next(actor for actor in first["actors"] if actor["owner"] == "idl03")
        self.assertEqual(idle["balance"], balance_sim.economy.START_CAPITAL)
        self.assertEqual(idle["buildings"], 0)
        loan = next(actor for actor in first["actors"] if actor["owner"] == "lon02")
        self.assertGreaterEqual(by_name["lon02"]["built"], 1)
        self.assertGreaterEqual(loan["buildings"] + loan["bankruptcies"], 1)

    def test_month_length_does_not_change_boundary_economy(self):
        common = dict(months=12, seed=20261114, npc_on=True, strategies=())
        day = balance_sim.run_scenario(month_seconds=86400, **common)
        minute = balance_sim.run_scenario(month_seconds=60, **common)
        ten = balance_sim.run_scenario(month_seconds=600, **common)
        self.assertEqual(day["invariants"], [])
        self.assertEqual(day["digest"], minute["digest"])
        self.assertEqual(day["digest"], ten["digest"])

    def test_half_month_proration_depends_on_fraction_not_length(self):
        half_minute = _farm_after(60, at_fraction=0.5)
        half_day = _farm_after(86400, at_fraction=0.5)
        full_day = _farm_after(86400, at_fraction=0.0)
        self.assertEqual(_strip_timing(half_minute), _strip_timing(half_day))
        self.assertNotEqual(half_day["honey_supply"], full_day["honey_supply"])
        self.assertGreater(full_day["honey_supply"], half_day["honey_supply"])
        self.assertEqual(half_minute["wallet_sum"], 0)

    def test_perf_probe_small_world_stays_balanced(self):
        item = balance_sim.perf_probe((50,), per_company=10)[0]
        self.assertEqual(item["buildings"], 50)
        self.assertEqual(item["invariants"], [])
        self.assertGreater(item["step_ms"], 0)
        self.assertEqual(item["processed"], 1)
        self.assertGreater(item["jobs"], 0)

    def test_csv_roundtrip_and_refuses_foreign_postgres(self):
        run = balance_sim.run_scenario(months=2, seed=1, npc_on=True, strategies=("idle",))
        self.assertEqual(run["invariants"], [])
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "m.csv")
            balance_sim.write_csv(run["rows"], path)
            with open(path, encoding="utf-8") as handle:
                header = handle.readline().strip().split(",")
            self.assertEqual(header, list(balance_sim.CSV_FIELDS))
        old_engine = os.environ.get("LUNEX_DB_ENGINE")
        old_db = os.environ.get("LUNEX_PG_DB")
        os.environ["LUNEX_DB_ENGINE"] = "postgres"
        os.environ["LUNEX_PG_DB"] = "lunex_prod"
        try:
            with self.assertRaises(RuntimeError):
                balance_sim.run_scenario(months=1, npc_on=False, strategies=())
        finally:
            if old_engine is None:
                os.environ.pop("LUNEX_DB_ENGINE", None)
            else:
                os.environ["LUNEX_DB_ENGINE"] = old_engine
            if old_db is None:
                os.environ.pop("LUNEX_PG_DB", None)
            else:
                os.environ["LUNEX_PG_DB"] = old_db

    def test_unknown_strategy_is_rejected(self):
        with self.assertRaises(ValueError):
            balance_sim.run_scenario(months=1, npc_on=False, strategies=("speculate",))


def _farm_after(month_seconds, at_fraction):
    tmp = tempfile.TemporaryDirectory()
    try:
        path = os.path.join(tmp.name, "w.sqlite3")
        with balance_sim.World(path, month_seconds, balance_sim.T0, seed=1, npc_on=False,
                                strategies=(), build_cap=4, months=1) as world:
            world._advance()
            world.now += int(world.month_seconds * at_fraction)
            self_ok = world.try_build("alice", "farm", 0)
            if not self_ok:
                raise AssertionError("ферма не построилась")
            world.now = world.t0 + world.month_seconds
            step_ms, _clk, processed, _done = world._advance()
            if processed != 1:
                raise AssertionError("ожидался один месяц, получено %s" % processed)
            row = world.snapshot(0, step_ms, 0.0)
            problems = balance_sim.row_invariants(row)
            if problems:
                raise AssertionError(problems)
            return row
    finally:
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
