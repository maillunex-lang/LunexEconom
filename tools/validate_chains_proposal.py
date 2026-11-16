"""Validate the proposed production-chain catalog. Does not read or write server/data."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
PROPOSAL = Path(__file__).resolve().parent / "sim" / "data" / "chains_proposed"
SCHEMA = ROOT / "server" / "data" / "schema.json"
NAMES = ("products", "buildings", "recipes")
STAGE_ORDER = ("foundation", "frame", "finishing", "commissioning")


class ProposalError(ValueError):
    pass


def _pairs(pairs):
    item = {}
    for key, value in pairs:
        if key in item:
            raise ProposalError(f"duplicate JSON key {key!r}")
        item[key] = value
    return item


def _reject_constant(token):
    raise ProposalError(f"non-integer number {token}")


def load_proposal(root=None):
    root = Path(root) if root is not None else PROPOSAL
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"), parse_constant=_reject_constant)
    Draft202012Validator.check_schema(schema)
    data = {}
    for name in NAMES:
        raw = (root / f"{name}.json").read_text(encoding="utf-8")
        contents = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_reject_constant)
        errors = list(Draft202012Validator(schema["$defs"][name]).iter_errors(contents))
        if errors:
            err = sorted(errors, key=lambda item: str(item.path))[0]
            raise ProposalError(f"{name}{list(err.path)}: {err.message}")
        data[name] = contents
    sinks_raw = (root / "sinks.json").read_text(encoding="utf-8")
    data["sinks"] = json.loads(sinks_raw, object_pairs_hook=_pairs, parse_constant=_reject_constant)
    return data


def _integers(value, path, errors):
    if isinstance(value, bool) or isinstance(value, str) or value is None:
        return
    if isinstance(value, float):
        errors.append(f"{path}: float")
        return
    if isinstance(value, int):
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _integers(item, f"{path}[{index}]", errors)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _integers(item, f"{path}.{key}", errors)
        return
    errors.append(f"{path}: not an integer ({type(value).__name__})")


def _consumers(data, products):
    used = {pid: set() for pid in products}
    for recipe in data["recipes"]:
        for pid in recipe["inputs"]:
            if pid in used:
                used[pid].add(f"recipe:{recipe['id']}")
    for building in data["buildings"]:
        if building.get("role") != "retail":
            continue
        for pid in building.get("allowed_goods", []):
            if pid in used:
                used[pid].add(f"retail:{building['id']}")
    sinks = data["sinks"]
    for stage, norms in sinks["construction"]["stages"].items():
        for pid in norms:
            if pid in used:
                used[pid].add(f"build:{stage}")
    fuel = sinks["logistics"]["product"]
    if fuel in used:
        used[fuel].add("logistics")
    gas = sinks["utility"]["product"]
    if gas in used:
        used[gas].add("utility")
    return used


def validate(data):
    errors = []
    _integers(data, "proposal", errors)
    products = {}
    for item in data["products"]:
        if item["id"] in products:
            errors.append(f"duplicate product id {item['id']}")
        products[item["id"]] = item
        if item["quality_range"]["min"] > item["quality_range"]["max"]:
            errors.append(f"{item['id']}: quality_range min exceeds max")
        if sum(item["rating_weights"].values()) != 100:
            errors.append(f"{item['id']}: rating weights must total 100")
        if item["consumer"] and item["base_demand_per_capita"] < 1:
            errors.append(f"{item['id']}: consumer good needs demand")
        if not item["consumer"] and item["base_demand_per_capita"] != 0:
            errors.append(f"{item['id']}: non-consumer demand must be 0")
    buildings = {}
    for item in data["buildings"]:
        if item["id"] in buildings:
            errors.append(f"duplicate building id {item['id']}")
        buildings[item["id"]] = item
        width = item["size"]["width"]
        height = item["size"]["height"]
        if type(width) is not int or type(height) is not int or width < 1 or height < 1:
            errors.append(f"{item['id']}: size must be positive integers")
        if item["build_cost"] < 1 or item["build_days"] < 1 or item["storage_capacity"] < 1:
            errors.append(f"{item['id']}: cost, days and storage must be positive")
    recipes = {}
    by_building = {}
    produced = {pid: set() for pid in products}
    graph = {pid: set() for pid in products}
    for recipe in data["recipes"]:
        if recipe["id"] in recipes:
            errors.append(f"duplicate recipe id {recipe['id']}")
        recipes[recipe["id"]] = recipe
        bid = recipe["building"]
        if bid not in buildings:
            errors.append(f"{recipe['id']}: unknown building {bid}")
            continue
        building = buildings[bid]
        if not building["production"]:
            errors.append(f"{recipe['id']}: {bid} is not a producer")
        if recipe["workers"] > building["jobs"]:
            errors.append(f"{recipe['id']}: workers exceed jobs")
        by_building.setdefault(bid, []).append(recipe)
        if not recipe["outputs"]:
            errors.append(f"{recipe['id']}: no outputs")
        overlap = set(recipe["inputs"]) & set(recipe["outputs"])
        if overlap:
            errors.append(f"{recipe['id']}: input and output overlap {sorted(overlap)}")
        for kind in ("inputs", "outputs"):
            for pid, qty in recipe[kind].items():
                if pid not in products:
                    errors.append(f"{recipe['id']}: unknown {kind} {pid}")
                elif type(qty) is not int or qty < 1:
                    errors.append(f"{recipe['id']}: {pid} quantity must be a positive integer")
        for source in recipe["inputs"]:
            if source not in graph:
                continue
            for target in recipe["outputs"]:
                if target in products:
                    graph[source].add(target)
        for pid in recipe["outputs"]:
            if pid in produced:
                produced[pid].add(recipe["id"])
    for building in buildings.values():
        if building["production"] and building["id"] not in by_building:
            errors.append(f"{building['id']}: producing building has no recipe")
        if building["role"] == "retail":
            if building.get("retail_cells", 0) < 1:
                errors.append(f"{building['id']}: retail needs retail_cells")
            goods = building.get("allowed_goods") or []
            if not goods:
                errors.append(f"{building['id']}: retail needs allowed_goods")
            for pid in goods:
                if pid not in products:
                    errors.append(f"{building['id']}: unknown retail good {pid}")
    sinks = data["sinks"]
    stages = sinks["construction"]["stages"]
    if tuple(stages) != STAGE_ORDER:
        errors.append("construction stages must be foundation, frame, finishing, commissioning")
    for stage, norms in stages.items():
        if not isinstance(norms, dict):
            errors.append(f"build:{stage}: norms must be an object")
            continue
        for pid, qty in norms.items():
            if pid not in products:
                errors.append(f"build:{stage}: unknown product {pid}")
            elif type(qty) is not int or qty < 1:
                errors.append(f"build:{stage}: {pid} norm must be a positive integer")
    if stages["commissioning"]:
        errors.append("commissioning must not consume materials")
    for key in ("logistics", "utility"):
        pid = sinks[key]["product"]
        if pid not in products:
            errors.append(f"{key}: unknown product {pid}")
    if sinks["logistics"].get("autobuy_default") not in (0, 1):
        errors.append("logistics.autobuy_default: flag default must be 0 or 1")
    if type(sinks["logistics"]["divisor"]) is not int or sinks["logistics"]["divisor"] < 1:
        errors.append("logistics.divisor: must be a positive integer")
    if type(sinks["utility"]["population_divisor"]) is not int or sinks["utility"]["population_divisor"] < 1:
        errors.append("utility.population_divisor: must be a positive integer")
    for flag_path, value in (
        ("construction.default", sinks["construction"]["default"]),
        ("logistics.default", sinks["logistics"]["default"]),
        ("utility.default", sinks["utility"]["default"]),
    ):
        if value not in (0, 1):
            errors.append(f"{flag_path}: flag default must be 0 or 1")
    exceptions = {}
    for row in sinks["product_exceptions"]:
        if row["id"] in exceptions:
            errors.append(f"duplicate product exception {row['id']}")
        if not str(row.get("reason", "")).strip():
            errors.append(f"product exception {row.get('id')}: reason required")
        exceptions[row["id"]] = row["reason"]
        if row["id"] not in products:
            errors.append(f"product exception {row['id']}: unknown product")
    building_exceptions = {}
    for row in sinks["building_exceptions"]:
        if row["id"] in building_exceptions:
            errors.append(f"duplicate building exception {row['id']}")
        if not str(row.get("reason", "")).strip():
            errors.append(f"building exception {row.get('id')}: reason required")
        building_exceptions[row["id"]] = row["reason"]
        if row["id"] not in buildings:
            errors.append(f"building exception {row['id']}: unknown building")
        elif buildings[row["id"]]["production"] or buildings[row["id"]]["role"] == "retail":
            errors.append(f"building exception {row['id']}: producers and shops are not exceptions")
    for building in buildings.values():
        if building["production"] or building["role"] == "retail":
            continue
        if building["id"] not in building_exceptions:
            errors.append(f"{building['id']}: non-producer needs a written exception")
    used = _consumers(data, products)
    for pid in sorted(products):
        if pid in exceptions:
            continue
        if not produced[pid]:
            errors.append(f"{pid}: no source")
        if not used[pid]:
            errors.append(f"{pid}: no consumer")
    visiting, visited = set(), set()

    def visit(node, stack):
        if node in visiting:
            errors.append("cycle: " + " -> ".join(stack + [node]))
            return
        if node in visited:
            return
        visiting.add(node)
        for nxt in sorted(graph[node]):
            visit(nxt, stack + [node])
        visiting.remove(node)
        visited.add(node)

    for node in sorted(graph):
        visit(node, [])
    retail_goods = set()
    for building in buildings.values():
        if building["role"] == "retail":
            retail_goods.update(building.get("allowed_goods", []))
    for pid, item in products.items():
        if item["consumer"] and pid not in retail_goods:
            errors.append(f"{pid}: consumer good is not in any retail building")
    bread = [
        ("field", None, "grain"),
        ("mill", "grain", "flour"),
        ("bakery", "flour", "bread"),
    ]
    for building, source, target in bread:
        ok = any(
            target in recipe["outputs"] and (source is None or source in recipe["inputs"])
            for recipe in by_building.get(building, [])
        )
        if not ok:
            errors.append(f"M1 broken: {building} must produce {target}")
    if not any("bread" in b.get("allowed_goods", []) for b in buildings.values() if b["role"] == "retail"):
        errors.append("M1 broken: no shop selling bread")
    return errors


def main(argv=None):
    try:
        data = load_proposal()
    except (OSError, ProposalError, ValueError, KeyError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    errors = validate(data)
    if errors:
        print(f"ERROR: {len(errors)} chain proposal problem(s)", file=sys.stderr)
        for line in errors:
            print(f"ERROR: {line}", file=sys.stderr)
        return 1
    sinks = data["sinks"]
    print(f"products: {len(data['products'])}")
    print(f"buildings: {len(data['buildings'])}")
    print(f"recipes: {len(data['recipes'])}")
    print(f"product exceptions: {len(sinks['product_exceptions'])}")
    print("building exceptions: " + ", ".join(row["id"] for row in sinks["building_exceptions"]))
    print("OK chains proposal (balance: draft)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
