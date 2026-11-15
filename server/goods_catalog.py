"""Versioned goods and building recipes for LunexEconom (BE-106).

Honey, oil and goods are defined here and copied into ``economy`` so the live
market keeps the same numbers. New agro and extraction recipes are not part of
``economy.PRODUCTION``: the monthly step picks them up only when such a
building exists (see ``production``). All money and quantities are integers.
"""
from dataclasses import dataclass

CATALOG_VERSION = 2

# Same seasonal curves the live market has used for honey, oil and goods.
_HONEY_SEASON = (1.15, 1.10, 1.00, 0.95, 0.90, 0.90, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15)
_OIL_SEASON = (1.15, 1.10, 1.05, 0.95, 0.90, 0.85, 0.85, 0.90, 0.95, 1.05, 1.10, 1.15)
_GOODS_SEASON = (0.95, 0.90, 0.95, 1.00, 1.00, 1.00, 1.00, 1.05, 1.05, 1.05, 1.10, 1.25)
_FLAT_SEASON = (1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0)


@dataclass(frozen=True)
class Good:
    id: str
    name: str
    unit: str
    reference_price: int
    vat_rate: float
    vat_category: str
    consumer: bool
    base_demand: int
    elasticity: float = 1.5
    season: tuple = _FLAT_SEASON

    @property
    def industrial(self):
        """Industrial means a firm or the base market buys it, not (only) a household."""
        return not self.consumer or self.id in ("honey",)


@dataclass(frozen=True)
class Recipe:
    kind: str
    name: str
    output: str
    capacity: int
    inputs: dict
    jobs: int
    upkeep: int
    build_cost: int
    width: int
    height: int
    role: str
    deposit: str = ""
    storage: int = 0
    legacy: bool = False


def _g(good_id, name, unit, price, vat, category, consumer, demand, season=_FLAT_SEASON):
    return Good(good_id, name, unit, price, vat, category, consumer, demand, 1.5, season)


# Live trio first: these numbers are the economy's. Do not "round" them.
GOODS = (
    _g("honey", "Мёд", "кг", 200, 0.10, "food", True, 200, _HONEY_SEASON),
    _g("oil", "Нефть", "т", 1500, 0.22, "raw", False, 80, _OIL_SEASON),
    _g("goods", "Товары", "шт", 2000, 0.22, "manufactured", True, 120, _GOODS_SEASON),
    _g("grain", "Зерно", "кг", 120, 0.10, "food", False, 200),
    _g("flour", "Мука", "кг", 400, 0.10, "food", False, 160),
    _g("bread", "Хлеб", "шт", 560, 0.10, "food", True, 200),
    _g("gas", "Газ", "м³", 400, 0.22, "raw", False, 160),
    _g("sand", "Песок", "м³", 90, 0.22, "raw", False, 300),
    _g("timber", "Лес", "м³", 220, 0.22, "raw", False, 140),
    _g("stone", "Камень", "м³", 80, 0.22, "raw", False, 200),
    _g("iron_ore", "Железная руда", "т", 500, 0.22, "raw", False, 80),
    _g("coal", "Уголь", "т", 180, 0.22, "raw", False, 120),
    _g("flax", "Лён", "кг", 140, 0.10, "raw", False, 140),
    _g("cement", "Цемент", "т", 700, 0.22, "manufactured", False, 80),
    _g("steel", "Сталь", "т", 2200, 0.22, "manufactured", False, 60),
    _g("brick", "Кирпич", "шт", 160, 0.22, "manufactured", False, 160),
    _g("lumber", "Пиломатериалы", "м³", 480, 0.22, "manufactured", False, 80),
    _g("petrochem", "Нефтехимия", "т", 1800, 0.22, "manufactured", False, 40),
    _g("fabric", "Ткань", "м", 350, 0.22, "manufactured", False, 100),
    _g("machines", "Станки", "шт", 8000, 0.22, "manufactured", False, 20),
    _g("hardware", "Металлоизделия", "шт", 900, 0.22, "manufactured", True, 80),
    _g("clothing", "Одежда", "шт", 1200, 0.22, "manufactured", True, 90),
    _g("electronics", "Электроника", "шт", 4500, 0.22, "manufactured", True, 40),
)

# legacy=True recipes are already wired through economy.PRODUCTION (same numbers).
# The others are buildable kinds added in BE-107 / BE-108.
RECIPES = (
    Recipe("farm", "Пасека", "honey", 100, {}, 4, 2_000, 120_000, 2, 2, "producer", legacy=True),
    Recipe("mine", "Нефтяная шахта", "oil", 40, {}, 10, 15_000, 300_000, 2, 3, "producer", legacy=True),
    Recipe("factory", "Завод товаров", "goods", 60, {"oil": 10, "honey": 20}, 20, 26_000, 450_000, 3, 2, "producer", legacy=True),
    Recipe("grain_field", "Поле зерновых", "grain", 100, {}, 4, 2_000, 90_000, 3, 2, "producer"),
    Recipe("elevator", "Элеватор", "", 0, {}, 2, 1_500, 70_000, 3, 3, "storage", storage=600),
    # `bread_plant`, not `bakery`: that id is the still-disabled shop specialization in construction_catalog.
    Recipe("mill", "Мельница", "flour", 80, {"grain": 100}, 6, 4_000, 180_000, 3, 2, "producer"),
    Recipe("bread_plant", "Хлебозавод", "bread", 100, {"flour": 80}, 8, 5_000, 200_000, 3, 2, "producer"),
    Recipe("oil_well", "Нефтяная скважина", "oil", 24, {}, 8, 10_000, 260_000, 2, 2, "extractor", deposit="oil"),
    Recipe("gas_well", "Газовая скважина", "gas", 80, {}, 6, 8_000, 240_000, 2, 2, "extractor", deposit="gas"),
    Recipe("sand_pit", "Песчаный карьер", "sand", 150, {}, 5, 3_000, 90_000, 2, 2, "extractor", deposit="sand"),
    Recipe("logging_camp", "Лесосека", "timber", 70, {}, 6, 4_000, 110_000, 2, 3, "extractor", deposit="forest"),
    Recipe("stone_pit", "Карьер камня", "stone", 200, {}, 5, 3_000, 40_000, 2, 2, "extractor", deposit="stone"),
    Recipe("iron_mine", "Рудник", "iron_ore", 40, {}, 6, 4_000, 60_000, 2, 2, "extractor", deposit="iron"),
    Recipe("coal_mine", "Угольная шахта", "coal", 140, {}, 6, 4_000, 90_000, 2, 2, "extractor", deposit="coal"),
    Recipe("flax_camp", "Льняное поле", "flax", 100, {}, 4, 2_000, 45_000, 2, 2, "extractor", deposit="flax"),
    Recipe("cement_plant", "Цементный завод", "cement", 60, {"stone": 80, "gas": 20}, 8, 5_000, 100_000, 3, 2, "producer"),
    Recipe("steel_plant", "Сталеплавильный завод", "steel", 30, {"iron_ore": 40, "coal": 50}, 12, 8_000, 110_000, 3, 3, "producer"),
    Recipe("brick_yard", "Кирпичный завод", "brick", 200, {"stone": 40, "sand": 30}, 5, 2_500, 120_000, 3, 2, "producer"),
    Recipe("sawmill", "Лесопилка", "lumber", 80, {"timber": 40}, 6, 3_500, 150_000, 3, 2, "producer"),
    Recipe("refinery", "Нефтехимия", "petrochem", 20, {"oil": 8}, 8, 6_000, 45_000, 3, 2, "producer"),
    Recipe("machine_plant", "Завод станков", "machines", 8, {"steel": 6, "oil": 4}, 14, 9_000, 150_000, 3, 3, "producer"),
    Recipe("metalworks", "Метизный завод", "hardware", 80, {"steel": 8}, 8, 4_000, 200_000, 3, 2, "producer"),
    Recipe("textile_mill", "Ткацкая фабрика", "fabric", 80, {"flax": 60}, 7, 3_500, 40_000, 3, 2, "producer"),
    Recipe("garment_plant", "Швейная фабрика", "clothing", 50, {"fabric": 40}, 10, 5_000, 240_000, 3, 2, "producer"),
    Recipe("electronics_plant", "Завод электроники", "electronics", 20, {"steel": 4, "petrochem": 6}, 16, 10_000, 400_000, 3, 3, "producer"),
)

_GOOD_BY_ID = {g.id: g for g in GOODS}
_RECIPE_BY_KIND = {r.kind: r for r in RECIPES}
LEGACY_KINDS = tuple(r.kind for r in RECIPES if r.legacy)
# Shop is the household buyer of every consumer good. It already lives in economy.
RETAIL_KIND = "shop"


def good(good_id):
    return _GOOD_BY_ID[good_id]


def has_good(good_id):
    return good_id in _GOOD_BY_ID


def recipe(kind):
    return _RECIPE_BY_KIND[kind]


def has_recipe(kind):
    return kind in _RECIPE_BY_KIND


def market_entry(good_id):
    """Shape compatible with ``economy.MARKET`` rows."""
    item = good(good_id)
    return {"name": item.name, "reference_price": item.reference_price, "base_demand": item.base_demand,
            "elasticity": item.elasticity, "consumer": item.consumer, "season": list(item.season)}


def legacy_production(kind):
    """The ``economy.PRODUCTION`` entry for a legacy producer. Same integers as before."""
    item = recipe(kind)
    spec = {"product": item.output, "output": item.capacity, "jobs": item.jobs, "upkeep": item.upkeep}
    if item.inputs:
        spec["inputs"] = dict(item.inputs)
    return spec


def production_spec(kind):
    """Monthly spec for a non-legacy recipe, or None. Legacy kinds stay in ``economy.PRODUCTION``."""
    item = _RECIPE_BY_KIND.get(kind)
    if item is None or item.legacy:
        return None
    spec = {"product": item.output or None, "output": item.capacity, "jobs": item.jobs, "upkeep": item.upkeep,
            "role": item.role}
    if item.inputs:
        spec["inputs"] = dict(item.inputs)
    if item.storage:
        spec["capacity"] = item.storage
    return spec


def deposit_resource(kind):
    item = _RECIPE_BY_KIND.get(kind)
    if item is None or not item.deposit:
        return None
    return item.deposit


def extra_build_costs():
    return {item.kind: item.build_cost for item in RECIPES if not item.legacy}


def extra_footprints():
    return {item.kind: (item.width, item.height) for item in RECIPES if not item.legacy}


def extra_vat_rates():
    """VAT for goods that are not part of the original three-product market."""
    return {item.id: item.vat_rate for item in GOODS if item.id not in ("honey", "oil", "goods")}


def all_inputs():
    found = set()
    for item in RECIPES:
        found.update(item.inputs)
    return found


def producer_kind(product):
    """First recipe (catalog order) that outputs ``product``."""
    for item in RECIPES:
        if item.output == product:
            return item.kind
    raise KeyError(product)


def product_order():
    """Outputs in dependency order, raw materials first. Raises on a cycle or a missing producer."""
    check()
    produced = {}
    for item in RECIPES:
        if item.output and item.output not in produced:
            produced[item.output] = item.kind
    remaining = {item.kind: item for item in RECIPES if item.output}
    resolved = set()
    ordered = []
    while remaining:
        ready = sorted(kind for kind, item in remaining.items() if set(item.inputs).issubset(resolved))
        if not ready:
            raise ValueError("unresolved_or_cyclic_recipe")
        for kind in ready:
            item = remaining.pop(kind)
            if item.output not in ordered:
                ordered.append(item.output)
            resolved.add(item.output)
    return ordered


def check():
    """Invariants: every input has a producer, no cycles, every good has a buyer and a producer."""
    if len(_GOOD_BY_ID) != len(GOODS) or len(_RECIPE_BY_KIND) != len(RECIPES):
        raise ValueError("duplicate_catalog_ids")
    outputs = {item.output for item in RECIPES if item.output}
    for item in RECIPES:
        for raw in item.inputs:
            if raw not in outputs:
                raise ValueError("input_without_producer:%s" % raw)
            if raw not in _GOOD_BY_ID:
                raise ValueError("unknown_input:%s" % raw)
        if item.output and item.output not in _GOOD_BY_ID:
            raise ValueError("unknown_output:%s" % item.output)
    for item in GOODS:
        if len(item.season) != 12:
            raise ValueError("bad_season:%s" % item.id)
        if item.base_demand <= 0:
            raise ValueError("good_without_buyer:%s" % item.id)
        if item.id not in outputs:
            raise ValueError("good_without_producer:%s" % item.id)
        if item.reference_price <= 0 or item.vat_rate < 0 or item.vat_rate > 0.22:
            raise ValueError("bad_good:%s" % item.id)
    pending = {item.kind: set(item.inputs) for item in RECIPES if item.output}
    resolved = set()
    guard = 0
    while pending and guard < 100:
        guard += 1
        ready = [kind for kind, need in pending.items() if need <= resolved]
        if not ready:
            raise ValueError("cyclic_recipes")
        for kind in ready:
            pending.pop(kind)
            resolved.add(_RECIPE_BY_KIND[kind].output)
    if pending:
        raise ValueError("cyclic_recipes")
    return True


def public_view():
    """Read-only JSON for ``GET /catalog/goods``. Stable for a catalog version."""
    check()
    goods = []
    for item in GOODS:
        goods.append({"id": item.id, "name": item.name, "unit": item.unit,
                      "reference_price": item.reference_price, "vat_rate": item.vat_rate,
                      "vat_category": item.vat_category, "consumer": item.consumer,
                      "industrial": (not item.consumer) or bool(any(item.id in r.inputs for r in RECIPES)),
                      "base_demand": item.base_demand, "elasticity": item.elasticity,
                      "season": list(item.season)})
    recipes = []
    for item in RECIPES:
        recipes.append({"kind": item.kind, "name": item.name, "output": item.output or None,
                        "capacity": item.capacity, "inputs": dict(item.inputs), "jobs": item.jobs,
                        "upkeep": item.upkeep, "build_cost": item.build_cost, "width": item.width,
                        "height": item.height, "role": item.role, "deposit": item.deposit or None,
                        "storage": item.storage, "legacy": item.legacy})
    return {"version": CATALOG_VERSION, "goods": goods, "recipes": recipes,
            "retail_kind": RETAIL_KIND,
            "invariants": {"inputs_have_producers": True, "acyclic": True, "goods_have_buyers": True,
                           "goods_have_producers": True}}


check()
