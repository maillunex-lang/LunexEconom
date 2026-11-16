"""Integer-only, ledger-like balanced mock settlement for sales-mode research.
No production DB access, virtual wallets never credited externally.
"""
from __future__ import annotations

import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data" / "sales_proposed"


def load_inputs():
    params = json.loads((DATA / "parameters.json").read_text(encoding="utf-8"))
    scenarios = json.loads((DATA / "scenarios.json").read_text(encoding="utf-8"))["scenarios"]
    return params, scenarios


def checked(x, low=0, high=2**63 - 1):
    if type(x) is not int or not low <= x <= high:
        raise ValueError("invalid integer")
    return x


def pricing_valid(price, cfg):
    checked(price, 1)
    ref = cfg["reference_price_rub"]
    return (ref * cfg["price_min_bp"] // 10000 <= price <=
            ref * cfg["price_max_bp"] // 10000 and price % cfg["price_step_rub"] == 0)


def supplier_score(price, quality, reliability, distance, config):
    """Four normalized 0..1000 terms, weights total 10000; no brand double-counting."""
    for value in (price, quality, reliability, distance):
        checked(value)
    checked(quality, 0, 100)
    checked(reliability, 0, 1000)
    if price == 0:
        raise ValueError("zero external price")
    effective = price + distance * config["freight_rub_per_distance_unit"]
    port = config["port_price_rub"] + distance * config["freight_rub_per_distance_unit"]
    if effective > port or quality < config["min_acceptable_quality"]:
        return None
    price_score = min(1000, config["reference_price_rub"] * 1000 // effective)
    q_score = quality * 10
    d_score = 1000 * (10 + distance) // (10 + 2 * distance)
    value = (price_score * config["price_score_weight_bp"] +
             q_score * config["quality_score_weight_bp"] +
             reliability * config["reliability_score_weight_bp"] +
             d_score * config["distance_score_weight_bp"]) // 10000
    return value if value >= config["score_cutoff"] else None


def allocate_fair(available, requests, cap=None):
    """Max-min water filling by stable buyer id; equal demands differ by <=1."""
    checked(available)
    targets = {str(k): checked(v) for k, v in requests.items()}
    allocations = {k: 0 for k in targets}
    remaining = available
    while remaining:
        active = [k for k in sorted(targets) if allocations[k] < targets[k]]
        if not active:
            break
        step = max(1, remaining // len(active))
        progressed = 0
        for key in active:
            take = min(step, remaining, targets[key] - allocations[key])
            allocations[key] += take
            remaining -= take
            progressed += take
        if not progressed:
            break
    if cap is not None:
        checked(cap)
        # Cap applied in eligibility before clearance; never silently discard here.
        if any(amount > cap for amount in allocations.values()):
            raise ValueError("cap not applied to requests")
    return allocations


def accepted_buyers(buyers, price, quality, reliability, cfg, invited=(), contracts=(), mode="public"):
    qualified = []
    for buyer in sorted(buyers, key=lambda b: b["id"]):
        if mode == "invited" and buyer["id"] not in set(invited) | set(contracts):
            continue
        score = supplier_score(price, quality, reliability, buyer["distance"], cfg)
        if quality < buyer["quality_min"] or score is None:
            continue
        qualified.append((buyer, score))
    return qualified


def simulate_one(scenario, cfg, months=24):
    checked(months, 1, 1000)
    mode = scenario["mode"]
    if mode not in ("private", "public", "mixed", "invited"):
        raise ValueError("invalid mode")
    price = scenario["price_rub"]
    if not pricing_valid(price, cfg):
        raise ValueError("invalid price")
    reserve = checked(scenario["reserve_bp"], 0, 10000)
    if mode != "mixed" and reserve not in (0, 10000):
        raise ValueError("reserve only for mixed")
    buyers = scenario["external_buyers"]
    if len(set(b["id"] for b in buyers)) != len(buyers):
        raise ValueError("duplicate buyer")
    wallets = {"mine": cfg["initial_wallet_rub"]}
    wallets.update({b["id"]: cfg["initial_wallet_rub"] for b in buyers})
    journal = []
    seen = set()
    history = []
    no_sales_days = 0
    total_lost = total_profit = total_buyer_profit = 0
    total_produced = total_external = total_internal = 0
    for month in range(1, months + 1):
        capacity = cfg["mine_monthly_capacity"]
        produced = capacity  # scenario: capacity pre-funded, no stock carry, unsold remains in ending stock
        stock = produced
        own_need = scenario["own_need"]
        own = min(stock, own_need) if mode == "private" else (min(stock, own_need, stock * reserve // 10000) if mode == "mixed" else (min(stock, own_need) if own_need else 0))
        stock -= own
        if mode == "private":
            offer = 0
        elif mode == "mixed":
            # Reserved stock is available to own production first, unneeded reserve stays reserved, not sold.
            offer = min(stock, max(0, produced - produced * reserve // 10000))
        else:
            offer = stock
        eligible = accepted_buyers(buyers, price, scenario["mine_quality"], scenario["mine_reliability"], cfg,
                                   scenario.get("invited_ids", ()), scenario.get("contract_ids", ()), mode)
        requests = {}
        for b, score in eligible:
            demand = cfg["buyers_monthly_need"]
            max_share = capacity * cfg["market_share_cap_bp"] // 10000
            if b["ai"]:
                max_share = min(max_share, capacity * cfg["ai_purchase_cap_bp"] // 10000)
            requests[b["id"]] = min(demand, max_share)
        # Contract purchases have priority after own use; can never exceed actual eligible demand.
        contract_ids = set(scenario.get("contract_ids", ()))
        contracted = {b: q for b, q in requests.items() if b in contract_ids}
        contract_alloc = allocate_fair(offer, contracted)
        offer -= sum(contract_alloc.values())
        open_alloc = allocate_fair(offer, {b: q for b, q in requests.items() if b not in contract_ids})
        sales = {**contract_alloc, **open_alloc}
        external_units = sum(sales.values())
        stock -= external_units
        buyer_profit = 0
        revenue = 0
        for buyer_id, qty in sorted(sales.items()):
            buyer = next(b for b in buyers if b["id"] == buyer_id)
            money = qty * price
            freight = qty * buyer["distance"] * cfg["freight_rub_per_distance_unit"]
            # Budget is checked prior to settlement; no overdrafts or negative stock.
            affordable = min(qty, wallets[buyer_id] // max(1, price + buyer["distance"] * cfg["freight_rub_per_distance_unit"]))
            if affordable != qty:
                raise ValueError("scenario wallet exhausted")
            key = f"sale:{scenario['id']}:{month}:{buyer_id}"
            if key in seen:
                continue
            seen.add(key)
            wallets[buyer_id] -= money + freight
            wallets["mine"] += money
            # freight goes into a separate simulation sink account, not to the mine.
            wallets["freight"] = wallets.get("freight", 0) + freight
            journal.append((key, buyer_id, "mine", money))
            journal.append((key + ":freight", buyer_id, "freight", freight))
            revenue += money
            buyer_profit += qty * (cfg["buyer_finished_good_value_rub"] - cfg["buyer_processing_cost_rub"] - price - buyer["distance"] * cfg["freight_rub_per_distance_unit"])
        mine_cost = cfg["mine_monthly_fixed_cost"] + produced * cfg["mine_unit_cost_rub"]
        own_cost_savings = own * (cfg["reference_price_rub"] - cfg["mine_unit_cost_rub"])
        profit = revenue - mine_cost + own_cost_savings
        # Loss is buyer demand not captured, including buyers rejecting an overpriced public offer.
        visible = len(buyers) if mode in ("public", "mixed") else (len(eligible) if mode == "invited" else 0)
        lost = max(0, visible * cfg["buyers_monthly_need"] - external_units)
        no_sales_days = no_sales_days + cfg["month_days"] if external_units == 0 and mode != "private" else 0
        if (no_sales_days >= cfg["price_reduction_after_no_sales_days"] and price > cfg["reference_price_rub"]):
            lower = cfg["reference_price_rub"] * cfg["price_min_bp"] // 10000
            price = max(lower, price - max(1, price * cfg["monthly_price_reduction_bp"] // 10000))
            no_sales_days = 0
        total_lost += lost
        total_profit += profit
        total_buyer_profit += buyer_profit
        total_produced += produced
        total_external += external_units
        total_internal += own
        history.append({"month":month,"price_rub":price,"produced":produced,"own_delivered":own,
                        "external_sold":external_units,"unsold_stock":stock,"seller_profit_rub":profit,
                        "buyers_profit_rub":buyer_profit,"lost_sales_units":lost})
        assert own + external_units + stock == produced
    assert all(v >= 0 for v in wallets.values())
    assert len(seen) == len(journal) // 2
    return {"scenario":scenario["id"],"mode":mode,"months":months,"history":history,
            "totals":{"produced":total_produced,"own_delivered":total_internal,"external_sold":total_external,
                      "capacity_utilization_bp":total_produced*10000//(months*cfg["mine_monthly_capacity"]),
                      "sold_capacity_utilization_bp":(total_internal+total_external)*10000//(months*cfg["mine_monthly_capacity"]),
                      "seller_profit_rub":total_profit,"buyers_profit_rub":total_buyer_profit,
                      "lost_sales_units":total_lost,"final_price_rub":price,"journal_entries":len(journal)},
            "wallet_conserved":sum(wallets.values()) == cfg["initial_wallet_rub"] * (1+len(buyers))}


def run(months=24):
    cfg, scenarios = load_inputs()
    return {"schema_version":1, "balance":"draft", "months":months,
            "scenarios":{s["id"]:simulate_one(s,cfg,months) for s in scenarios}}


def rebuild_golden():
    data = run(24)
    target = DATA / "golden_24_months.json"
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


if __name__ == "__main__":
    print(json.dumps(run(24), ensure_ascii=False, indent=2))
