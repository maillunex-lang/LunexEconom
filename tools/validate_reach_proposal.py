#!/usr/bin/env python3
"""Validate opt-in retail reach draft, bounded integer datasets and golden outputs."""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIM = ROOT / "tools" / "sim"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DATA = SIM / "data" / "reach_proposed"
NAMES = ("parameters.json", "anchors_ufa.json")
SCENARIOS = (
    "reach_corner_vs_mall", "reach_two_neighbors", "reach_far_stores",
    "reach_fame_growth", "reach_stockout", "reach_queue",
)


class ValidationError(ValueError):
    pass


def require(test: bool, message: str) -> None:
    if not test:
        raise ValidationError(message)


def integer(value: object, label: str, low: int, high: int) -> int:
    require(type(value) is int and low <= value <= high, f"{label}: expected int {low}..{high}")
    return value


def check_types(raw: object, path: str = "root") -> None:
    if isinstance(raw, dict):
        for key, value in raw.items():
            require(isinstance(key, str), f"{path}: non-string key")
            check_types(value, path + "." + key)
    elif isinstance(raw, list):
        for index, value in enumerate(raw):
            check_types(value, f"{path}[{index}]")
    elif type(raw) is int:
        integer(raw, path, -(2**63 - 1), 2**63 - 1)
    else:
        require(type(raw) in (str, bool) or raw is None, f"{path}: floats or unsupported value forbidden")


def read(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"),
                         parse_float=lambda _: (_ for _ in ()).throw(ValidationError(f"{path}: float forbidden")),
                         parse_constant=lambda _: (_ for _ in ()).throw(ValidationError(f"{path}: non-finite forbidden")))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"{path}: {exc}") from exc
    check_types(raw)
    require(type(raw) is dict, f"{path}: object expected")
    return raw


def validate(base: Path = DATA, check_golden: bool = True) -> dict:
    from tools.sim.districts import load_city_districts
    from tools.sim.reach import simulate_reach
    src = {name: read(base / name) for name in NAMES}
    for name, document in src.items():
        require(document.get("balance") == "draft", f"{name}: balance must be draft")
    params = src["parameters.json"]
    geo = src["anchors_ufa.json"]
    require(params.get("model_version") == "retail-reach-v1", "wrong reach version")
    require(params.get("metric") == "chebyshev", "wrong metric")
    integer(params.get("cell_m"), "cell_m", 20, 20)
    integer(params.get("min_radius_cells"), "min_radius_cells", 1, 24)
    integer(params.get("max_radius_cells"), "max_radius_cells", params["min_radius_cells"], 48)
    integer(params.get("outside_option_weight"), "outside option", 1, 1000000)
    integer(params.get("core_radius_cells"), "core", 1, params["max_radius_cells"])
    integer(params.get("fame_opening_permille"), "opening fame", 0, 1000)
    integer(params.get("reputation_initial_permille"), "reputation", 0, 1000)
    integer(params.get("max_area_m2"), "max_area", 40, 400)
    integer(params.get("max_cashiers"), "max_cashiers", 1, 50)
    integer(params.get("max_daily_visitors"), "max_visitors", 1, 10000)
    require(params.get("queue_warn_threshold_permille", 0) <= 1000, "queue threshold >1000")
    for key, value in params.items():
        if key.endswith("permille") and type(value) is int:
            integer(value, key, 0, 1500)
        if key.endswith("cells") and type(value) is int:
            integer(value, key, 0, 48)
    formats = params.get("base_radius_by_format")
    defaults = params.get("default_area_by_format_m2")
    require(type(formats) is dict and len(formats) >= 8 and set(defaults) == set(formats), "format tables mismatch")
    for key, value in formats.items():
        integer(value, f"format {key}", 1, params["max_radius_cells"])
        integer(defaults[key], f"area {key}", 1, params["max_area_m2"])
    require(geo.get("city_id") == "ufa" and geo.get("spatial_mode") == "district_centroid_proxy", "unknown city or spatial mode")
    district_book = load_city_districts()
    cells = geo.get("district_cells")
    require(type(cells) is list, "district_cells must be list")
    require({x["id"] for x in cells} == {x["id"] for x in district_book["districts"]}, "M2 district IDs mismatch")
    for cell in cells:
        integer(cell["x"], "x", -38, 38)
        integer(cell["y"], "y", -38, 38)
    for name in SCENARIOS:
        scenario = read(SIM / "scenarios" / "reach" / f"{name}.json")
        require(scenario.get("reach_enabled") is True, f"{name}: reach flag missing")
        require(scenario.get("id") == name, f"{name}: wrong id")
        integer(scenario.get("days"), "days", 1, 365)
        stores = scenario.get("stores")
        require(type(stores) is list and 1 <= len(stores) <= 1000, f"{name}: bad stores")
        require(len({s["id"] for s in stores}) == len(stores), f"{name}: duplicate stores")
        for store in stores:
            require(store["format"] in formats, f"{name}: invalid format")
            require(store["district"] in {d["id"] for d in cells}, f"{name}: invalid district")
            integer(store["x"], "store.x", -38, 38)
            integer(store["y"], "store.y", -38, 38)
            integer(store.get("area_m2", defaults[store["format"]]), "store.area", 1, params["max_area_m2"])
            integer(store.get("cashiers", 2), "store.cashiers", 1, params["max_cashiers"])
            integer(store.get("fame_permille", params["fame_opening_permille"]), "store.fame", 0, 1000)
            integer(store.get("price", params["price_reference_rub"]), "store.price", 1, 100000)
            integer(store.get("stock", 1000000), "store.stock", 0, 1000000000)
        for event in scenario.get("events", []):
            integer(event["day"], "event.day", 1, scenario["days"])
            require(event["store"] in {s["id"] for s in stores}, f"{name}: unknown store in event")
        if check_golden:
            actual = simulate_reach(scenario)
            expected = read(SIM / "golden" / "reach" / f"{name}.json")
            require(actual == expected, f"{name}: golden differs")
            for day in actual["days"]:
                require(day["allocated"] + day["city"] == day["demand"], f"{name}: demand conservation")
                require(day["sold"] + day["unserved"] == day["allocated"], f"{name}: sales conservation")
    for path in (SIM / "reach.py", SIM / "__main__.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            require(not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) and not (isinstance(node.right, ast.Constant) and isinstance(node.right.value, str))), f"{path}: true division")
            require(not (isinstance(node, ast.Constant) and isinstance(node.value, float)), f"{path}: float literal")
    return {"validated_scenarios": len(SCENARIOS), "formats": len(formats), "districts": len(cells)}


if __name__ == "__main__":
    print(validate())
