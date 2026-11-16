"""Целочисленная симуляция исследований: очки, дерево, качество, цена, лицензии (GDD 32). Только проект, balance: draft."""
from __future__ import annotations

import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data" / "rnd_proposed"


def load():
    return (json.loads((DATA / "parameters.json").read_text(encoding="utf-8")),
            json.loads((DATA / "scenarios.json").read_text(encoding="utf-8")))


def rp_month(budget, staff_level, p):
    base = budget * p["rp_per_1000_rub"] // 1000
    return base * (10000 + p["rp_staff_bonus_bp_per_level"] * (staff_level - 1)) // 10000


def quality_cap_bp(done, p):
    nodes = {n["id"]: n for n in p["tech_nodes"]}
    return max([nodes[i]["quality_cap_bp"] for i in done] + [p["base_quality_cap_bp"]])


def run(variant, scn, p):
    nodes = p["tech_nodes"]
    done, rp_stock, profit, spent_rd, fee_paid = [], 0, 0, 0, 0
    first_unlock = {}
    rows = []
    for m in range(1, scn["months"] + 1):
        rp_stock += rp_month(variant["budget_month"], variant["staff_level"], p)
        spent_rd += variant["budget_month"]
        for n in nodes:
            if n["id"] in done or any(r not in done for r in n["requires"]):
                continue
            if rp_stock >= n["cost_rp"]:
                rp_stock -= n["cost_rp"]
                done.append(n["id"])
                first_unlock[n["id"]] = m
        if variant.get("license_nodes") and m == variant["license_month"]:
            for nid in variant["license_nodes"]:
                if nid not in done:
                    done.append(nid)
                    first_unlock[nid] = m
                    fee_paid += max(p["license"]["min_fee_rub"], next(n for n in nodes if n["id"] == nid)["cost_rp"] * 1000 // p["rp_per_1000_rub"])
        cap = quality_cap_bp(done, p)
        quality = p["quality_scale"]["base_quality"] + cap * p["quality_scale"]["quality_per_cap_bp"] // 1000
        price = scn["business"]["base_price"] * (10000 + (quality - p["quality_scale"]["base_quality"]) * p["quality_scale"]["premium_bp_per_quality_point"]) // 10000
        b = scn["business"]
        units = b["units_month"]
        profit += units * (price - b["unit_cost"]) - b["fixed_month"] - variant["budget_month"]
        rows.append([m, quality, price])
    profit -= fee_paid
    return {"id": variant["id"], "profit": profit, "tech_done": done, "unlock_month": first_unlock,
            "final_quality": rows[-1][1], "final_price": rows[-1][2], "rd_spent": spent_rd, "license_fee": fee_paid}


def obsolescence_factor_bp(months_since_gen, p):
    o = p["obsolescence"]
    over = max(0, months_since_gen - o["generation_months"])
    return max(o["floor_bp"], 10000 - over * o["demand_decay_bp_per_month"])


def run_all():
    p, s = load()
    return {"variants": [run(v, s, p) for v in s["variants"]],
            "obsolescence": [[m, obsolescence_factor_bp(m, p)] for m in (12, 24, 30, 36, 48, 60)]}


def rebuild_golden():
    out = run_all()
    (DATA / "golden.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return out
