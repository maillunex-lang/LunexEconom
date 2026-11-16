"""Целочисленные мини-симуляции GDD 37-44 (бренд, биржа, внешняя торговля, события, логистика, услуги). Только проект, balance: draft."""
from __future__ import annotations

import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data" / "wave4_proposed"


def load():
    return json.loads((DATA / "parameters.json").read_text(encoding="utf-8"))


def brand(p):
    b, out = p["brand"], []
    for budget in b["budgets"]:
        level, profit = 0, 0
        for _ in range(b["months"]):
            gain = budget * b["gain_bp_per_1000_rub"] // 1000 * (10000 - level) // 10000
            level = max(0, min(10000, level + gain - level * b["decay_bp_month"] // 10000))
            points = level * b["rating_weight_bp"] // 10000 * b["rating_points_max"] // 10000
            revenue = b["base_revenue_month"] * (10000 + points * b["revenue_per_rating_point_bp"]) // 10000
            profit += revenue * b["margin_bp"] // 10000 - budget
        out.append({"budget": budget, "final_brand_bp": level, "profit": profit})
    return out


def stock(p):
    s = p["stock"]
    valuation = s["profit_month"] * 12 * s["pe_multiple"] + s["equity"]
    price = valuation // s["shares"] if valuation >= s["shares"] else 1
    price_x100 = valuation * 100 // s["shares"]
    ipo_price_x100 = price_x100 * (10000 - s["ipo_discount_bp"]) // 10000
    sold = s["shares"] * s["ipo_share_bp"] // 10000
    proceeds = sold * ipo_price_x100 // 100
    dividends_year = s["profit_month"] * s["months"] * s["payout_bp"] // 10000
    outside_dividends = dividends_year * s["ipo_share_bp"] // 10000
    return {"valuation": valuation, "ipo_price_x100": ipo_price_x100, "proceeds": proceeds,
            "founder_share_bp": 10000 - s["ipo_share_bp"], "dividends_year": dividends_year,
            "dividends_to_outside": outside_dividends, "dividend_yield_bp": dividends_year * 10000 // valuation}


def trade(p):
    t = p["trade"]
    imp = t["ref_price"] * (10000 + t["import_premium_bp"]) // 10000 * (10000 + t["tariff_bp"]) // 10000
    exp = t["ref_price"] * (10000 - t["export_discount_bp"]) // 10000 * (10000 - t["tariff_bp"]) // 10000
    rows = []
    for dom in t["domestic_prices"]:
        clamped = min(imp, max(exp, dom))
        mode = "import" if dom > imp else "export" if dom < exp else "domestic"
        rows.append({"domestic": dom, "effective": clamped, "mode": mode})
    return {"import_price": imp, "export_price": exp, "rows": rows}


def events(p):
    e = p["events"]
    def total(with_events):
        profit = 0
        for m in range(1, e["months"] + 1):
            farm, store = e["farm_revenue_month"], e["store_revenue_month"]
            if with_events:
                d, c, h = e["drought"], e["crisis"], e["holiday"]
                if d["month"] <= m < d["month"] + d["duration"]:
                    farm = farm * d["farm_output_bp"] // 10000
                if c["month"] <= m < c["month"] + c["duration"]:
                    farm = farm * c["demand_bp"] // 10000
                    store = store * c["demand_bp"] // 10000
                if h["month"] <= m < h["month"] + h["duration"]:
                    store = store * h["demand_bp"] // 10000
            profit += (farm + store) * e["margin_bp"] // 10000
        return profit
    return {"calm": total(False), "with_events": total(True)}


def logistics(p):
    g, rows = p["logistics"], []
    for km in g["distances_km"]:
        units = g["truck_capacity"] * g["trips_per_month"]
        freight = units * km * g["freight_rub_per_100_unit_km"] // 100
        own = km * 2 * g["trips_per_month"] * g["fuel_rub_per_km"] + g["driver_month"]
        payback = g["truck_cost"] // max(1, freight - own) if freight > own else 0
        rows.append({"km": km, "freight_month": freight, "own_month": own, "payback_months": payback})
    return rows


def service(p):
    s, rows = p["service"], []
    capacity = s["seats"] * s["turns_per_day"] * s["days"]
    for visits in s["demand_visits_month"]:
        sold = min(visits, capacity)
        profit = sold * (s["price"] - s["ingredient_cost"]) - s["staff_month"] - s["upkeep_month"]
        rows.append({"demand": visits, "sold": sold, "capacity": capacity, "profit_month": profit})
    return rows


def run_all():
    p = load()
    return {"brand": brand(p), "stock": stock(p), "trade": trade(p), "events": events(p),
            "logistics": logistics(p), "service": service(p)}


def rebuild_golden():
    out = run_all()
    (DATA / "golden.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return out
