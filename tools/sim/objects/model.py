"""Целочисленная симуляция износа, уровней, истощения месторождений и автозакупки (GDD 31). Только проект, balance: draft."""
from __future__ import annotations

import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data" / "objects_proposed"


def load():
    return (json.loads((DATA / "parameters.json").read_text(encoding="utf-8")),
            json.loads((DATA / "scenarios.json").read_text(encoding="utf-8")))


def capacity_bp(level, wear_bp, p):
    lv = p["levels"][str(level)]["capacity_bp"]
    return lv * (10000 - wear_bp // p["wear"]["capacity_penalty_divisor"]) // 10000


def upkeep(level, wear_bp, base, p):
    lv = base * p["levels"][str(level)]["upkeep_bp"] // 10000
    return lv + lv * wear_bp // (10000 * p["wear"]["upkeep_penalty_divisor"])


def repair_cost(build_cost, wear_bp, p):
    return build_cost * wear_bp // 10000 * p["wear"]["repair_cost_bp_of_value"] // 10000


def run_wear(scn, variant, p):
    b = scn["building"]
    wear = profit = repaired = 0
    rows = []
    upgrade = b["build_cost"] * p["levels"][str(variant["level"])]["upgrade_cost_bp"] // 10000
    profit -= upgrade
    for m in range(1, b["months"] + 1):
        wear = min(p["wear"]["max_wear_bp"], wear + p["wear"]["rate_bp_per_month"][b["category"]])
        if variant["repair_at_bp"] is not None and wear >= variant["repair_at_bp"]:
            cost = repair_cost(b["build_cost"], wear, p)
            profit -= cost
            repaired += cost
            wear = 0
        units = min(b["demand_units_month"], b["units_month_base"] * capacity_bp(variant["level"], wear, p) // 10000)
        revenue = units * b["price"]
        cost_month = (units * b["input_cost_per_unit"] + upkeep(variant["level"], wear, b["upkeep_month"], p)
                      + b["jobs"] * b["wage_month"])
        profit += revenue - cost_month
        rows.append([m, wear, units, revenue - cost_month])
    return {"id": variant["id"], "profit": profit, "repair_spent": repaired, "upgrade_cost": upgrade,
            "final_wear_bp": wear, "last_month_units": rows[-1][2], "months": rows}


def run_deposit(scn, p):
    rem = scn["initial_reserve"]
    start = rem
    profit = out_total = 0
    rows = []
    for m in range(1, scn["months"] + 1):
        remaining_bp = rem * 10000 // start
        factor = 10000
        if remaining_bp < p["deposit"]["slowdown_below_bp"]:
            factor = min(10000, remaining_bp * p["deposit"]["slowdown_factor_bp_per_remaining_bp"])
        take = min(rem, scn["extract_month_base"] * factor // 10000)
        rem -= take
        out_total += take
        profit += take * scn["price"] - scn["wage_upkeep_month"]
        rows.append([m, take, rem])
    return {"id": "deposit", "extracted": out_total, "remaining": rem, "profit": profit, "months": rows}


def run_automation(scn, auto, p):
    stock = scn["stock_start"]
    profit = lost = 0
    for m in range(1, scn["months"] + 1):
        stock += 0 if m in scn["interrupted_months"] else scn["delivery_per_month"]
        need = scn["use_per_month"]
        if auto and stock < need + scn["min_stock_months"] * need // 2:
            buy = need - stock if need > stock else 0
            buy = max(buy, 0) + need // 2
            price = scn["input_ref_price"] * (10000 + p["automation"]["auto_buy_premium_bp"]) // 10000
            profit -= buy * price
            stock += buy
        used = min(stock, need)
        lost += need - used
        stock -= used
        profit += used * scn["output_per_input"] * scn["output_price"]
        profit -= used * scn["input_ref_price"] if not auto else 0
    return {"id": "auto" if auto else "manual", "profit": profit, "lost_input": lost, "final_stock": stock}


def run_all():
    p, s = load()
    return {
        "wear": [run_wear(s["wear"], v, p) for v in s["wear"]["variants"]],
        "deposit": run_deposit(s["deposit"], p),
        "automation": [run_automation(s["automation"], False, p), run_automation(s["automation"], True, p)],
    }


def rebuild_golden():
    out = run_all()
    (DATA / "golden.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return out
