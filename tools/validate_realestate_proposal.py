#!/usr/bin/env python3
"""Standalone deterministic real-estate proposal validator (no DB/network)."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent / "sim/data/realestate_proposed"
FILES = ("buildings.json", "rates.json", "limits.json", "lifecycle.json", "lease_examples.json", "mall_returns.json")
MAX_I64 = 2**63 - 1


class ValidationError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ValidationError(message)


def integer(value, field, minimum=0, maximum=MAX_I64):
    require(type(value) is int and minimum <= value <= maximum, f"{field}: expected integer [{minimum},{maximum}]")
    return value


def check_types(value, path="root"):
    if isinstance(value, dict):
        for key, item in value.items():
            require(isinstance(key, str), f"{path}: key must be string")
            check_types(item, f"{path}.{key}")
    elif isinstance(value, list):
        for pos, item in enumerate(value):
            check_types(item, f"{path}[{pos}]")
    else:
        require(value is None or type(value) in (int, str, bool), f"{path}: float/non-JSON number forbidden")
        if type(value) is int:
            integer(value, path, -MAX_I64, MAX_I64)


def load_data(base=BASE):
    result = {}
    for name in FILES:
        path = Path(base) / name
        try:
            result[name] = json.loads(path.read_text(encoding="utf-8"), parse_float=lambda _: (_ for _ in ()).throw(ValidationError(f"{name}: float forbidden")), parse_constant=lambda _: (_ for _ in ()).throw(ValidationError(f"{name}: NaN/Infinity forbidden")))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError(f"{name}: {exc}") from exc
        check_types(result[name], name)
        require(result[name].get("balance") == "draft", f"{name}: balance must be draft")
    return result


def rate_reference(rate, zone, city):
    return max(rate["min_rate_rub_per_m2_month"], min(rate["max_rate_rub_per_m2_month"], rate["base_retail_rub_per_m2_month"] * rate["zones"][zone]["factor_permille"] * rate["cities"][city]["rent_index_bp"] // 10000000))


def has_cycles(graph):
    visiting, visited = set(), set()

    def visit(node):
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        for next_node in graph[node]:
            if visit(next_node):
                return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in graph)


def validate(data):
    buildings = data["buildings.json"]["buildings"]
    limits = data["limits.json"]
    rates = data["rates.json"]
    cycle = data["lifecycle.json"]
    leases = data["lease_examples.json"]["leases"]
    returns = data["mall_returns.json"]["cases"]
    by_id = {item["id"]: item for item in buildings}
    require(len(by_id) == len(buildings) and len(buildings) >= 6, "duplicate/insufficient building ids")
    for key in ("retail_m2_per_cell", "retail_stock_units_per_m2", "max_area_share_per_building_permille", "max_area_per_player_per_city_m2", "max_owner_properties_per_player_per_city", "max_owner_leasable_area_city_m2", "rate_floor_permille_of_reference", "rate_ceiling_permille_of_reference", "month_days"):
        integer(limits[key], key, 1)
    for key in ("traffic_factor_min_permille", "traffic_factor_max_permille", "anchor_bonus_cap_permille", "vacancy_default_permille", "upkeep_utilities_permille_of_rent"):
        integer(limits[key], key, 0, 2000)
    require(limits["max_area_share_per_building_permille"] <= 1000, "building share >1000")
    require(limits["vacancy_default_permille"] < 1000, "vacancy >=1000")
    require(limits["rate_floor_permille_of_reference"] <= 1000 <= limits["rate_ceiling_permille_of_reference"], "bad rent factor boundaries")
    require(limits["traffic_factor_min_permille"] <= 1000 <= limits["traffic_factor_max_permille"], "traffic bounds")
    integer(rates["base_retail_rub_per_m2_month"], "base rate", 1)
    integer(rates["min_rate_rub_per_m2_month"], "min rate", 1)
    integer(rates["max_rate_rub_per_m2_month"], "max rate", rates["min_rate_rub_per_m2_month"])
    for zone, obj in rates["zones"].items():
        integer(obj["factor_permille"], f"zone {zone}", 1, 3000)
        integer(obj["land_zone_bp"], f"land zone {zone}", 1, 30000)
    for city, obj in rates["cities"].items():
        integer(obj["land_index_bp"], f"city land {city}", 1)
        integer(obj["rent_index_bp"], f"city rent {city}", 1)
    for item in buildings:
        for key in ("gross_m2", "leasable_m2", "unit_module_m2", "max_units", "min_unit_m2", "max_unit_m2", "build_cost_rub", "upkeep_month_rub"):
            integer(item[key], f"{item["id"]}.{key}", 1)
        integer(item["traffic_visitors_per_day"], "traffic", 0)
        integer(item["quality_score"], "quality", 0, 100)
        integer(item["comfort_score"], "comfort", 0, 100)
        require(item["gross_m2"] >= item["leasable_m2"] and item["leasable_m2"] == item["unit_module_m2"] * item["max_units"], f"{item["id"]}: area inconsistent")
        require(item["min_unit_m2"] <= item["max_unit_m2"] <= item["leasable_m2"], "unit sizes wrong")
        require(item["min_unit_m2"] % item["unit_module_m2"] == 0 and item["max_unit_m2"] % item["unit_module_m2"] == 0, "unit sizes not modular")
        require(item["zone"] in rates["zones"], "unknown zone")
    graph = cycle["transitions"]
    states = set(cycle["states"])
    require(set(graph) == states and cycle["initial_state"] in states, "missing/unknown lifecycle state")
    require(set(cycle["terminal_states"]) <= states, "unknown terminal")
    for state, targets in graph.items():
        require(len(targets) == len(set(targets)) and all(t in states for t in targets), f"{state}: bad targets")
        if state in cycle["terminal_states"]:
            require(not targets, f"{state}: terminal has transitions")
    require(not has_cycles(graph), "lifecycle has cycles")
    require(all(s in states for s in ("active", "delinquent", "evicted", "ended")), "missing lease states")
    per_property, per_player_building, per_player_city = defaultdict(int), defaultdict(int), defaultdict(int)
    units, ids = set(), set()
    for lease in leases:
        lease_id, unit = lease["id"], lease["unit_id"]
        require(lease_id not in ids, "duplicate lease id")
        ids.add(lease_id)
        require(unit not in units, "double-leased unit")
        units.add(unit)
        require(lease["landlord"] != lease["tenant"], "self-lease is for migration only")
        require(lease["building_id"] in by_id and lease["city"] in rates["cities"], "unknown building/city")
        building = by_id[lease["building_id"]]
        require(lease["use"] in building["usable_levels"], "illegal use")
        require(lease["status"] in states, "invalid status")
        area = integer(lease["area_m2"], f"{lease_id}: area", building["min_unit_m2"], building["max_unit_m2"])
        require(area % building["unit_module_m2"] == 0, "area not module multiple")
        if lease["use"] == "retail":
            require(limits["min_store_m2"] <= area <= limits["max_store_m2"], "retail floor area outside bounds")
            require(area // limits["retail_m2_per_cell"] >= 1, "no retail cells")
        integer(lease["term_months"], "term", rates["minimum_term_months"], limits["term_max_months"])
        integer(lease["start_month"], "start month", 1)
        integer(lease["indexation_bp_12_months"], "indexation", 0, rates["max_indexation_bp_12_months"])
        ref = rate_reference(rates, building["zone"], lease["city"])
        lower = max(rates["min_rate_rub_per_m2_month"], ref * limits["rate_floor_permille_of_reference"] // 1000)
        upper = min(rates["max_rate_rub_per_m2_month"], ref * limits["rate_ceiling_permille_of_reference"] // 1000)
        rent_rate = integer(lease["rate_rub_per_m2_month"], "rent rate", lower, upper)
        expected_deposit = area * rent_rate * rates["deposit_months"]
        integer(lease["deposit_rub"], "deposit", 0, area * rent_rate * limits["deposit_max_months"])
        require(lease["deposit_rub"] == expected_deposit, "deposit mismatch")
        per_property[lease["property_id"]] += area
        per_player_building[lease["property_id"], lease["tenant"]] += area
        per_player_city[lease["city"], lease["tenant"]] += area
    property_buildings = {}
    for lease in leases:
        key = lease["property_id"]
        require(key not in property_buildings or property_buildings[key] == lease["building_id"], "property with mixed types")
        property_buildings[key] = lease["building_id"]
    for prop, area in per_property.items():
        require(area <= by_id[property_buildings[prop]]["leasable_m2"], f"{prop}: over-leased")
    for (prop, tenant), area in per_player_building.items():
        require(area * 1000 <= by_id[property_buildings[prop]]["leasable_m2"] * limits["max_area_share_per_building_permille"], f"{prop}/{tenant}: building monopoly")
    for key, area in per_player_city.items():
        require(area <= limits["max_area_per_player_per_city_m2"], f"{key}: city monopoly")
    mall_ids = {b["id"] for b in buildings if b["id"].startswith("mall_")}
    require(len(returns) == len(mall_ids) == 3, "must cover three mall sizes")
    seen = set()
    for case in returns:
        building_id = case["building_id"]
        require(building_id in mall_ids and building_id not in seen, "returns missing/duplicate mall")
        seen.add(building_id)
        b = by_id[building_id]
        rate = rate_reference(rates, case["zone"], case["city"])
        rented = b["leasable_m2"] * (1000 - limits["vacancy_default_permille"]) // 1000
        gross = rate * rented
        utilities = gross * limits["upkeep_utilities_permille_of_rent"] // 1000
        land = limits["land_base_rub"] * rates["cities"][case["city"]]["land_index_bp"] * rates["zones"][case["zone"]]["land_zone_bp"] // 100000000
        tax = (b["build_cost_rub"] + land) * limits["property_tax_bp_month"] // 10000
        net = gross - utilities - b["upkeep_month_rub"] - tax
        invest = land + b["build_cost_rub"]
        expected = {"assumed_occupancy_permille":1000-limits["vacancy_default_permille"],"rented_m2":rented,"rate_rub_per_m2_month":rate,"gross_rent_month_rub":gross,"utilities_month_rub":utilities,"upkeep_month_rub":b["upkeep_month_rub"],"land_price_rub":land,"property_tax_month_rub":tax,"net_month_rub":net,"investment_rub":invest,"payback_months":(invest+net-1)//net if net>0 else None}
        for key, value in expected.items():
            require(case[key] == value, f"{building_id}: {key} expected {value}, got {case[key]}")
    return {"buildings":len(buildings),"leases":len(leases),"mall_returns":len(returns),"transitions":sum(len(v) for v in graph.values())}


def main():
    try:
        counts = validate(load_data())
    except (ValidationError, KeyError, TypeError, ValueError) as exc:
        print(f"FAIL: {exc}")
        return 1
    print("OK: realestate proposal validated", counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
