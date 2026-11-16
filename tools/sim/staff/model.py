"""Целочисленная симуляция персонала: уровни 1-9, обучение, зарплата, текучесть (GDD 33). Только проект, balance: draft."""
from __future__ import annotations

import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data" / "staff_proposed"


def load():
    return (json.loads((DATA / "parameters.json").read_text(encoding="utf-8")),
            json.loads((DATA / "scenarios.json").read_text(encoding="utf-8")))


def productivity_bp(level, p):
    return p["productivity_base_bp"] + p["productivity_per_level_bp"] * (level - 1)


def level_up_cost(level, p):
    return p["train_cost_points_per_level_sq"] * level * level


def expected_wage(level, p):
    return p["base_wage_month"] * (10000 + p["wage_per_level_bp"] * (level - 1)) // 10000


def turnover_bp(wage, level, p):
    expected = expected_wage(level, p)
    under = max(0, (expected - wage) * 10000 // expected) if expected else 0
    return max(p["turnover_floor_bp"], p["turnover_base_bp"] + under * p["turnover_per_underpay_1000_bp"] // 1000)


def morale_bp(wage, level, p):
    expected = expected_wage(level, p)
    under = max(0, (expected - wage) * 10000 // expected) if expected else 0
    return max(p["morale_floor_bp"], 10000 - under * p["morale_penalty_bp_per_underpay_1000_bp"] // 10000)


def run(variant, scn, p):
    b = scn["business"]
    level, pts, workers = 1, 0, b["workers"]
    profit = quits = hires = 0
    carry = 0
    rows = []
    for m in range(1, scn["months"] + 1):
        wage = expected_wage(1, p) * variant["wage_factor_bp"] // 10000 if variant["wage_factor_bp"] else 0
        pts += variant["training_budget_month"] * p["points_per_1000_rub"] // 1000
        while level < p["levels"] and pts >= level_up_cost(level, p):
            pts -= level_up_cost(level, p)
            level += 1
        wage = expected_wage(level, p) * variant["wage_factor_bp"] // 10000
        carry += workers * turnover_bp(wage, level, p)
        leave = carry // 10000
        carry -= leave * 10000
        quits += leave
        hires += leave
        level_loss = leave * 10000 // b["workers"]
        eff_workers = workers - leave
        units = min(b["demand_units_month"], eff_workers * b["units_per_worker_month_base"] * productivity_bp(level, p) // 10000 * morale_bp(wage, level, p) // 10000)
        hire_cost = leave * wage * p["hire_cost_wage_months"]
        profit += units * (b["price"] - b["input_cost_per_unit"]) - workers * wage - b["upkeep_month"] - hire_cost - variant["training_budget_month"]
        rows.append([m, level, units, wage])
    return {"id": variant["id"], "profit": profit, "final_level": level, "quits": quits,
            "last_month_units": rows[-1][2], "wage_last": rows[-1][3]}


def run_all():
    p, s = load()
    return {"variants": [run(v, s, p) for v in s["variants"]]}


def rebuild_golden():
    out = run_all()
    (DATA / "golden.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return out
