"""Целочисленная симуляция решений ИИ-игроков на одном рынке и проверка правил честности (GDD 35). Только проект, balance: draft."""
from __future__ import annotations

import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data" / "ai_engine_proposed"


def load():
    return (json.loads((DATA / "parameters.json").read_text(encoding="utf-8")),
            json.loads((DATA / "scenarios.json").read_text(encoding="utf-8")))


def price_of(player, cost, p, below_cost_months):
    """Возвращает (цена, намеренная цена ниже себестоимости?)."""
    if player["kind"] == "human":
        return p["ref_price"], False
    mk = p["archetypes"][player["archetype"]]["price_markup_bp"]
    price = max(1, p["ref_price"] * (10000 + mk) // 10000)
    wants_below = price < cost
    # правило честности: ниже себестоимости не дольше max_below_cost_months подряд
    if wants_below and below_cost_months >= p["max_below_cost_months"]:
        price = cost
    return price, wants_below


def allocate(players, prices, p):
    """Спрос делится по привлекательности (ref/цена), ограничен мощностью; остаток перераспределяется."""
    avg = sum(prices) // len(prices)
    total = p["market_demand_units"] * max(2000, 10000 - (avg - p["ref_price"]) * 10000 // p["ref_price"] * p["price_elasticity_bp_per_ref_pct"] // 100) // 10000
    sold = [0] * len(players)
    cap = [pl["capacity"] for pl in players]
    weights = [p["ref_price"] * 10000 // pr for pr in prices]
    remaining = total
    for _ in range(3):
        open_idx = [i for i in range(len(players)) if sold[i] < cap[i]]
        wsum = sum(weights[i] for i in open_idx)
        if not open_idx or remaining <= 0 or wsum == 0:
            break
        given = 0
        for i in open_idx:
            part = min(cap[i] - sold[i], remaining * weights[i] // wsum)
            sold[i] += part
            given += part
        remaining -= given
    # правило: ни один игрок не получает более max_market_share_bp спроса (излишек не продаётся)
    limit = total * p["max_market_share_bp"] // 10000
    return [min(s, limit) for s in sold], total


def run(scn, p):
    players = [dict(x) for x in scn["players"]]
    cash = [0] * len(players)
    below = [0] * len(players)
    profits = [0] * len(players)
    for m in range(1, scn.get("months", 24) + 1):
        quotes = [price_of(pl, scn["unit_cost"], p, below[i]) for i, pl in enumerate(players)]
        prices = [q[0] for q in quotes]
        sold, _ = allocate(players, prices, p)
        for i, pl in enumerate(players):
            below[i] = below[i] + 1 if quotes[i][1] else 0
            month_profit = sold[i] * (prices[i] - scn["unit_cost"]) - p["fixed_month"]
            profits[i] += month_profit
            cash[i] += month_profit
            share = p["archetypes"][pl["archetype"]]["reinvest_bp"] if pl["kind"] == "ai" else 5000
            if month_profit > 0:
                invest = month_profit * share // 10000
                pl["capacity"] += invest // p["capacity_cost_per_unit"]
                cash[i] -= invest
    return profits, [pl["capacity"] for pl in players], sold, players


def run_all():
    p, s = load()
    out = []
    for scn in s["scenarios"]:
        scn = dict(scn, months=s["months"])
        profits, caps, sold, players = run(scn, p)
        ai = [profits[i] for i, pl in enumerate(players) if pl["kind"] == "ai"]
        hum = [profits[i] for i, pl in enumerate(players) if pl["kind"] == "human"]
        ratio = (sum(ai) // len(ai)) * 10000 // max(1, sum(hum) // len(hum)) if ai else 0
        total_sold = sum(sold)
        share_ai = sum(sold[i] for i, pl in enumerate(players) if pl["kind"] == "ai") * 10000 // max(1, total_sold) if ai else 0
        out.append({"id": scn["id"], "profits": profits, "capacity_end": caps, "ai_to_human_profit_bp": ratio,
                    "ai_share_end_bp": share_ai})
    return {"scenarios": out}


def rebuild_golden():
    out = run_all()
    (DATA / "golden.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return out
