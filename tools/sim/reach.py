"""Draft opt-in, deterministic spatial retail reach model (no server writes)."""
from __future__ import annotations

import json
from pathlib import Path

from tools.sim.catalog import Catalog
from tools.sim.demand import market_demand
from tools.sim.districts import load_city_districts, split_largest_remainder

DATA = Path(__file__).resolve().parent.joinpath("data", "reach_proposed")


def config() -> dict:
    return json.loads(DATA.joinpath("parameters.json").read_text(encoding="utf-8"))


def anchors() -> dict:
    return json.loads(DATA.joinpath("anchors_ufa.json").read_text(encoding="utf-8"))


def clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(upper, value))


def checked(value: object, name: str, lower: int = 0, upper: int = 1000000000) -> int:
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError(f"{name}: expected integer [{lower},{upper}]")
    return value


def distance(x: int, y: int, a: int, b: int) -> int:
    return max(abs(x - a), abs(y - b))


def radius(store: dict, params: dict) -> int:
    fmt = str(store["format"])
    area = checked(store["area_m2"], "area_m2", 1, params["max_area_m2"])
    fame = checked(store["fame_permille"], "fame_permille", 0, 1000)
    transport = checked(store.get("transport_bonus_cells", 0), "transport_bonus_cells", 0, params["transport_bonus_cap_cells"])
    base = params["base_radius_by_format"][fmt]
    area_bonus = min(params["area_bonus_cap_cells"], area // params["area_step_m2"])
    fame_bonus = min(params["fame_bonus_cap_cells"], fame // params["fame_step_permille"])
    return clamp(base + area_bonus + fame_bonus + transport, params["min_radius_cells"], params["max_radius_cells"])


def falloff(dist: int, reach: int, params: dict) -> int:
    if dist > reach:
        return 0
    core = min(reach, params["core_radius_cells"])
    if dist <= core:
        return 1000
    fringe = params["fringe_min_permille"]
    return fringe + (1000 - fringe) * (reach - dist) // max(1, reach - core)


def daily_capacity(store: dict, params: dict) -> int:
    area = checked(store["area_m2"], "area_m2", 1, params["max_area_m2"])
    tills = checked(store["cashiers"], "cashiers", 1, params["max_cashiers"])
    return min(params["max_daily_visitors"], area * params["area_visitors_per_m2_day"], tills * params["cashier_visitors_per_day"])


def reputation_score(quality: int, price: int, reference: int, availability: int) -> int:
    quality = checked(quality, "quality", 0, 100)
    price = checked(price, "price", 1)
    availability = checked(availability, "availability", 0, 1000)
    price_score = clamp(reference * 1000 // price, 0, 1500)
    return clamp((quality * 10 * 450 + price_score * 350 + availability * 200) // 1000, 0, 1000)


def fame_and_reputation(store: dict, params: dict, sold: int, attempts: int) -> dict:
    """Completed day: advertise only with verified spending, feedback from actual visits."""
    value = store["fame_permille"]
    rep = store["reputation_permille"]
    age = store.get("days_with_sales", 0)
    ad_spend = checked(store.get("ad_spend_rub", 0), "ad_spend_rub", 0, 100000000)
    ad_reach = checked(store.get("ad_reach_permille", 0), "ad_reach_permille", 0, 1000)
    ad_delta = min(params["fame_daily_ad_cap_permille"], ad_spend * ad_reach // params["fame_ad_budget_divisor"])
    if age < params["fame_ad_validity_sale_days"]:
        ad_delta = min(ad_delta, max(0, params["fame_unproven_ad_cap_permille"] - value))
    if sold > 0:
        age += 1
    fame_change = ad_delta - (0 if ad_spend > 0 else params["fame_daily_decay_permille"])
    score = reputation_score(store["quality"], store["price"], params["price_reference_rub"], store["stock_availability_permille"])
    if sold >= params["reputation_min_visits_per_day"]:
        if score >= rep:
            rep += min(score - rep, params["reputation_daily_good_step_permille"])
        else:
            rep -= min(rep - score, params["reputation_daily_bad_step_permille"])
    elif attempts > 0 and sold == 0:
        rep = max(0, rep - params["reputation_daily_bad_step_permille"])
    elif rep > params["reputation_initial_permille"]:
        rep -= params["reputation_daily_recovery_step_permille"]
    elif rep < params["reputation_initial_permille"]:
        rep += params["reputation_daily_recovery_step_permille"]
    if store["day"] % params["fame_word_of_mouth_step_days"] == 0 and age > 0:
        if rep >= params["fame_wom_target_threshold_permille"]:
            fame_change += params["fame_word_of_mouth_good_permille"]
        if rep <= params["fame_wom_bad_threshold_permille"]:
            fame_change -= params["fame_word_of_mouth_bad_permille"]
    fame_change = clamp(fame_change, -params["daily_fame_delta_cap_permille"], params["daily_fame_delta_cap_permille"])
    return {"fame_permille": clamp(value + fame_change, 0, 1000), "reputation_permille": clamp(rep, 0, 1000), "days_with_sales": age, "experience_score_permille": score, "fame_delta": fame_change}


def _store_weight(store: dict, dist: int, params: dict) -> int:
    fade = falloff(dist, radius(store, params), params)
    if not fade or not store["open"]:
        return 0
    # Shared M2 A^2 style. Mall/anchor adds weight but never modifies district demand.
    price = checked(store["price"], "price", 1)
    reference = params["price_reference_rub"]
    quality = checked(store["quality"], "quality", 0, 100)
    attractiveness = (quality * 10 + clamp(reference * 1000 // price, 250, 1500)) // 2
    visibility = clamp(500 + store["fame_permille"], 500, 1500)
    mall = checked(store.get("mall_traffic_factor_permille", 1000), "mall traffic", params["mall_traffic_factor_min_permille"], params["mall_traffic_factor_cap_permille"])
    anchor = checked(store.get("anchor_factor_permille", 1000), "anchor", 1000, 1300)
    # One floor for multiplied factors (four permille multipliers), then A squared.
    appeal = attractiveness * visibility * mall * anchor * fade // 1000000000000
    return appeal * appeal


def _demand_template(city: dict, sku: str, catalog: Catalog) -> dict:
    product = catalog.product(sku)
    # Compute the M2 demand once with NO stores at reference price and reference rating.
    # This prevents price changes or multiple stores from minting/destroying demand.
    return market_demand(int(catalog.city(city["city_id"])["population_estimate"]), product,
                         city["districts"], city["layers"], [], city["competition_s"],
                         city["ad_factor_permille"], city["growth_bp"])


def _district_effects(store: dict, district: dict, params: dict) -> tuple[int, int]:
    dist = distance(store["x"], store["y"], district["x"], district["y"])
    return dist, _store_weight(store, dist, params)


def allocate_day(stores: list[dict], book: dict, loci: dict, params: dict, total_demand: dict) -> dict:
    by_id = {d["id"]: d for d in loci["district_cells"]}
    demand_by_district = {d["id"]: d for d in total_demand["districts"]}
    chosen: dict[str, int] = {store["id"]: 0 for store in stores}
    district_choices: dict[str, dict[str, int]] = {store["id"]: {} for store in stores}
    allocated: dict[str, int] = {store["id"]: 0 for store in stores}
    records = []
    for district in book["districts"]:
        district_id = district["id"]
        locus = by_id[district_id]
        source = demand_by_district[district_id]
        district_selected = 0
        district_demand = 0
        layers = []
        for layer in source["layers"]:
            amount = layer["demand"]
            weights = []
            keys = []
            for store in stores:
                _dist, weight = _district_effects(store, locus, params)
                weights.append(weight)
                keys.append(store["id"])
            weights.append(params["outside_option_weight"])
            keys.append("~city")
            shares = split_largest_remainder(amount, weights, keys)
            for idx, store in enumerate(stores):
                chosen[store["id"]] += shares[idx]
                district_choices[store["id"]][district_id] = district_choices[store["id"]].get(district_id, 0) + shares[idx]
                district_selected += shares[idx]
            district_demand += amount
            layers.append({"id": layer["id"], "demand": amount, "allocated_to_stores": sum(shares[:-1]), "city": shares[-1]})
        records.append({"id": district_id, "name": district["name"], "demand": district_demand,
                        "allocated_to_stores": district_selected, "city": district_demand - district_selected,
                        "layers": layers})
    # Capacity is shared by every SKU sold in this store. The six scenarios use one SKU.
    store_rows = []
    for store in stores:
        key = store["id"]
        wanted = chosen[key]
        capacity = daily_capacity(store, params)
        stock = checked(store["stock"], "stock", 0, 1000000000)
        queue_factor = max(0, wanted * 1000 // max(1, capacity) - params["queue_warn_threshold_permille"])
        queue_penalty = min(params["queue_penalty_max_permille"], queue_factor * params["queue_penalty_step_permille"] // 1000)
        visitors = min(wanted, capacity)
        served = visitors * (1000 - queue_penalty) // 1000
        sold = min(served, stock)
        allocated[key] = wanted
        store_rows.append({"id": key, "format": store["format"], "district": store["district"], "radius_cells": radius(store, params),
                           "fame_permille": store["fame_permille"], "reputation_permille": store["reputation_permille"],
                           "capacity_visitors": capacity, "allocated": wanted, "visitors": visitors, "queue_penalty_permille": queue_penalty,
                           "sold": sold, "unserved": wanted - sold, "stock_remaining": max(0, stock - sold),
                           "district_allocated": {d: district_choices[key][d] for d in sorted(district_choices[key])}})
    return {"demand": sum(d["demand"] for d in records), "districts": records,
            "stores": store_rows, "city": sum(d["city"] for d in records),
            "allocated": sum(allocated.values()), "sold": sum(s["sold"] for s in store_rows),
            "unserved": sum(s["unserved"] for s in store_rows)}


def simulate_reach(scenario: dict, days: int | None = None) -> dict:
    params = config()
    loci = anchors()
    book = load_city_districts()
    catalog = Catalog()
    count = checked(scenario["days"] if days is None else days, "days", 1, 365)
    stores = []
    known = {district["id"] for district in book["districts"]}
    for raw in scenario["stores"]:
        fmt = str(raw["format"])
        if fmt not in params["base_radius_by_format"]:
            raise ValueError("unknown format")
        if raw["district"] not in known:
            raise ValueError("unknown district")
        stores.append({**raw, "open": raw.get("open", True), "stock": raw.get("stock", 1000000),
                       "cashiers": raw.get("cashiers", 2), "area_m2": raw.get("area_m2", params["default_area_by_format_m2"][fmt]),
                       "fame_permille": raw.get("fame_permille", params["fame_opening_permille"]),
                       "reputation_permille": raw.get("reputation_permille", params["reputation_initial_permille"]),
                       "quality": raw.get("quality", 70), "price": raw.get("price", params["price_reference_rub"]),
                       "stock_availability_permille": raw.get("stock_availability_permille", 1000),
                       "days_with_sales": 0, "day": 0})
    if len({s["id"] for s in stores}) != len(stores):
        raise ValueError("duplicate stores")
    stores.sort(key=lambda item: item["id"])
    demand = _demand_template(book, str(scenario.get("product", "bread")), catalog)
    rows = []
    for day in range(1, count + 1):
        for event in scenario.get("events", []):
            if event["day"] == day:
                target = next(store for store in stores if store["id"] == event["store"])
                for field, value in event["changes"].items():
                    if field not in {"ad_spend_rub", "ad_reach_permille", "price", "quality", "stock", "cashiers", "open"}:
                        raise ValueError(f"forbidden scenario event {field}")
                    target[field] = value
        for store in stores:
            store["day"] = day
        daily = allocate_day(stores, book, loci, params, demand)
        for output in daily["stores"]:
            store = next(item for item in stores if item["id"] == output["id"])
            store["stock"] = output["stock_remaining"]
            # Availability comes from physical stock, not from a buyer-supplied flag.
            store["stock_availability_permille"] = 0 if output["stock_remaining"] == 0 else 1000
            new = fame_and_reputation(store, params, output["sold"], output["allocated"])
            store.update({key: new[key] for key in ("fame_permille", "reputation_permille", "days_with_sales")})
            output.update({"fame_after_permille": new["fame_permille"], "reputation_after_permille": new["reputation_permille"],
                           "experience_score_permille": new["experience_score_permille"], "fame_delta_permille": new["fame_delta"]})
        daily["day"] = day
        rows.append(daily)
    return {"balance": "draft", "model_version": params["model_version"], "scenario": scenario["id"], "days_run": count,
            "spatial_mode": loci["spatial_mode"], "product": scenario.get("product", "bread"), "days": rows,
            "totals": {"demand": sum(d["demand"] for d in rows), "allocated": sum(d["allocated"] for d in rows),
                       "sold": sum(d["sold"] for d in rows), "unserved": sum(d["unserved"] for d in rows),
                       "city": sum(d["city"] for d in rows)}}
