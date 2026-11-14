"""Deterministic industry recipes and equipment economics.

Design-stage module: not wired to authoritative building endpoints yet.
Existing honey/oil/goods production and player balances are untouched.
All quantities and costs are integer game units/roubles, not real-world quotes.
"""
from dataclasses import dataclass
from typing import Mapping

@dataclass(frozen=True)
class Recipe:
    name: str
    product: str
    output: int
    inputs: Mapping[str, int]
    jobs: int
    upkeep: int

RECIPES = {
    "apiary": Recipe("Пасека", "honey", 100, {}, 4, 2000),
    "oil_well": Recipe("Нефтяная скважина", "oil", 40, {}, 10, 15000),
    "iron_mine": Recipe("Железорудная шахта", "iron_ore", 65, {}, 9, 11000),
    "coal_mine": Recipe("Угольная шахта", "coal", 75, {}, 9, 12000),
    "stone_quarry": Recipe("Карьер", "stone", 100, {}, 6, 6500),
    "grain_farm": Recipe("Зерновая ферма", "grain", 120, {}, 6, 5500),
    "sawmill": Recipe("Лесопилка", "timber", 80, {}, 7, 8000),
    "flour_mill": Recipe("Мукомольный завод", "flour", 90, {"grain": 110}, 9, 12000),
    "bakery": Recipe("Хлебозавод", "bread", 70, {"flour": 70}, 11, 15000),
    "steelworks": Recipe("Металлургический завод", "steel", 50, {"iron_ore": 60, "coal": 30}, 20, 30000),
    "cement_plant": Recipe("Цементный завод", "cement", 70, {"stone": 80, "coal": 15}, 15, 23000),
    "machine_plant": Recipe("Машиностроительный завод", "machinery", 25, {"steel": 35, "oil": 5}, 25, 35000),
    "consumer_factory": Recipe("Завод товаров", "goods", 60, {"oil": 10, "honey": 20}, 20, 26000),
}
LEVEL_MULTIPLIERS = {1: (100, 100), 2: (140, 120), 3: (190, 155)}
SIZE_MULTIPLIERS = {1: 100, 2: 175, 3: 260}


def order():
    """Topological product order, rejecting cycles and missing dependencies."""
    produced = {r.product for r in RECIPES.values()}
    if len(produced) != len(RECIPES):
        raise ValueError("duplicate_products")
    resolved = set()
    remaining = dict(RECIPES)
    result = []
    while remaining:
        ready = sorted((key for key, recipe in remaining.items()
                        if set(recipe.inputs).issubset(resolved)))
        if not ready:
            raise ValueError("unresolved_or_cyclic_recipe")
        for key in ready:
            recipe = remaining.pop(key)
            result.append(key)
            resolved.add(recipe.product)
    return result


def quote(kind, size=1, level=1):
    """One full month at nominal capacity. Caller handles staffing, stock and taxes."""
    if kind not in RECIPES or type(size) is not int or size not in SIZE_MULTIPLIERS or type(level) is not int or level not in LEVEL_MULTIPLIERS:
        raise ValueError("invalid_industry_configuration")
    recipe = RECIPES[kind]
    output_factor, upkeep_factor = LEVEL_MULTIPLIERS[level]
    scale = SIZE_MULTIPLIERS[size]
    return {
        "product": recipe.product,
        "output": recipe.output * scale * output_factor // 10000,
        "inputs": {key: (qty * scale * output_factor + 9999) // 10000
                   for key, qty in recipe.inputs.items()},
        "jobs": (recipe.jobs * scale + 99) // 100,
        "upkeep": (recipe.upkeep * scale * upkeep_factor + 9999) // 10000,
        "size": size, "equipment_level": level,
    }


def max_output(kind, available, size=1, level=1):
    """Integer production with no creation of raw material from rounding."""
    spec = quote(kind, size, level)
    cap = spec["output"]
    for product, needed in spec["inputs"].items():
        if needed <= 0:
            raise ValueError("invalid_input")
        stock = available.get(product, 0)
        if type(stock) is not int or stock < 0:
            raise ValueError("invalid_stock")
        cap = min(cap, spec["output"] * stock // needed)
    return cap


def upgrade_cost(kind, from_level, to_level):
    if kind not in RECIPES or type(from_level) is not int or type(to_level) is not int or to_level != from_level + 1 or to_level not in LEVEL_MULTIPLIERS:
        raise ValueError("invalid_upgrade")
    # Game-balance proposal; not yet an authoritative debit.
    return RECIPES[kind].upkeep * (8 + 4 * to_level)


def expansion_cost(kind, old_size, new_size):
    if kind not in RECIPES or type(old_size) is not int or type(new_size) is not int or old_size not in SIZE_MULTIPLIERS or new_size not in SIZE_MULTIPLIERS or new_size <= old_size:
        raise ValueError("invalid_expansion")
    return RECIPES[kind].upkeep * (SIZE_MULTIPLIERS[new_size] - SIZE_MULTIPLIERS[old_size]) // 10