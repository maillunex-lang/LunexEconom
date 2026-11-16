"""Целые формулы загрузки, спроса, зарплаты и цены рынка. Без float."""
from __future__ import annotations

LOAD_FULL_BP = 10000
VAT_BP = 1000
CORRIDOR_LOW_PERCENT = 25
CORRIDOR_HIGH_PERCENT = 250
BRAND_M1 = 50
DEMAND_DENOM = 1000 * 1000 * 1000 * 1000

# Черновые доли стадий (D-10, D-53, D-58 не утверждён).
# Сервер: server/enterprises/core.py — те же кортежи и то же деление.
# Срок копится границами. Цена: первые три доли независимо, последняя — остаток.
# Старые COST_SHARE_BP / split_by_bp — накопительные границы и на некратных
# суммах расходятся с сервером (пример: 3 ₽ → 0/2/0/1 вместо 0/1/0/2).
COST_SHARES_PERMILLE = (300, 400, 200, 100)
TIME_SHARES_PERMILLE = (250, 350, 300, 100)
TIME_SHARE_BP = (2500, 3500, 3000, 1000)
COST_SHARE_BP = (3000, 4000, 2000, 1000)


def stage_costs(total: int) -> list[int]:
    """Как server.enterprises.core.stage_costs: три floor и остаток на ввод."""
    if total < 1:
        raise RuntimeError("стоимость стадии считается от положительной суммы")
    parts = [total * share // 1000 for share in COST_SHARES_PERMILLE[:3]]
    parts.append(total - sum(parts))
    return parts


def stage_day_lengths(days: int) -> list[int]:
    """Как server.enterprises.core.stage_day_lengths: накопительный // 1000."""
    if days < 1:
        raise RuntimeError("build_days должен быть положительным")
    previous = 0
    result: list[int] = []
    cumulative = 0
    for share in TIME_SHARES_PERMILLE:
        cumulative += share
        end = days * cumulative // 1000
        result.append(end - previous)
        previous = end
    return result


def split_by_bp(total: int, shares: tuple[int, ...]) -> list[int]:
    if sum(shares) != LOAD_FULL_BP:
        raise RuntimeError("доли стадий должны давать 10000 bp")
    if total < 0:
        raise RuntimeError("отрицательная сумма")
    acc = 0
    bounds: list[int] = []
    for share in shares:
        acc += share
        bounds.append(total * acc // LOAD_FULL_BP)
    parts = [bounds[0]]
    for index in range(1, len(bounds)):
        parts.append(bounds[index] - bounds[index - 1])
    return parts


def load_bp(items: dict, recipe: dict, capacity: int, staff_bp: int) -> int:
    """Как server.enterprises.core.load_bp: 0..10000, floor."""
    staff = staff_bp
    if staff < 0:
        staff = 0
    if staff > LOAD_FULL_BP:
        staff = LOAD_FULL_BP
    occupied = 0
    for slot in items.values():
        occupied += slot["quantity"]
    free = capacity - occupied
    if free < 0:
        free = 0
    ratio = staff
    for product, volume in recipe["inputs"].items():
        if volume <= 0:
            continue
        have = items.get(product, {}).get("quantity", 0)
        ratio = min(ratio, have * LOAD_FULL_BP // volume)
    total_output = 0
    for volume in recipe["outputs"].values():
        total_output += volume
    if total_output:
        consumed = 0
        for volume in recipe["inputs"].values():
            consumed += volume
        required_net = total_output - consumed
        if required_net < 0:
            required_net = 0
        if required_net:
            ratio = min(ratio, free * LOAD_FULL_BP // required_net)
    if ratio < 0:
        return 0
    if ratio > LOAD_FULL_BP:
        return LOAD_FULL_BP
    return ratio


def monthly_expense(jobs: int, upkeep: int, salary: int, staff_bp: int, salary_index_bp: int) -> int:
    wage = jobs * salary * staff_bp // LOAD_FULL_BP
    wage = wage * salary_index_bp // LOAD_FULL_BP
    return wage + upkeep


def price_attractiveness(reference: int, price: int) -> int:
    """P = clamp(100 * эталон / цена, 0, 100). Множитель k из GDD не утверждён, k = 1."""
    if price <= 0:
        return 100
    score = (100 * reference) // price
    if score < 0:
        return 0
    if score > 100:
        return 100
    return score


def rating(weights: dict, brand: int, quality: int, price_score: int) -> int:
    brand_w = int(weights["brand"])
    quality_w = int(weights["quality"])
    price_w = int(weights["price"])
    denom = brand_w + quality_w + price_w
    if denom <= 0:
        return 0
    return (brand_w * brand + quality_w * quality + price_w * price_score) // denom


def clamp(value: int, low: int, high: int) -> int:
    if value < low:
        return low
    if value > high:
        return high
    return value


def demand_breakdown(
    population: int,
    per_capita: int,
    layer_share_permille: int,
    income_index: int,
    price: int,
    reference: int,
    elasticity: int,
    avg_rating: int,
    ad_factor_permille: int,
) -> tuple[int, int]:
    """Спрос и остаток числителя. Одно деление в конце, как в 07_POPULATION.md."""
    base = (population * per_capita * layer_share_permille) // 1000
    income_factor = 600 + (400 * income_index) // 1000
    if reference <= 0:
        price_delta_bp = 0
    else:
        price_delta_bp = ((price - reference) * LOAD_FULL_BP) // reference
    price_sens = clamp(1000 - elasticity * price_delta_bp // 100, 300, 1500)
    rating_factor = 700 + (300 * avg_rating) // 100
    numerator = base * income_factor * price_sens * rating_factor * ad_factor_permille
    return numerator // DEMAND_DENOM, numerator % DEMAND_DENOM


def demand_units(
    population: int,
    per_capita: int,
    layer_share_permille: int,
    income_index: int,
    price: int,
    reference: int,
    elasticity: int,
    avg_rating: int,
    ad_factor_permille: int,
) -> int:
    """Один район и один слой. Одно деление в конце, как в 07_POPULATION.md."""
    units, _lost = demand_breakdown(
        population,
        per_capita,
        layer_share_permille,
        income_index,
        price,
        reference,
        elasticity,
        avg_rating,
        ad_factor_permille,
    )
    return units


def corridor(reference: int) -> tuple[int, int]:
    low = reference * CORRIDOR_LOW_PERCENT // 100
    high = reference * CORRIDOR_HIGH_PERCENT // 100
    if low < 1:
        low = 1
    if high < low:
        high = low
    return low, high


def clearing_price(reference: int, demand: int, supply: int) -> int:
    low, high = corridor(reference)
    if demand <= 0 or supply <= 0:
        if supply <= 0 and demand > 0:
            return high
        if reference > 0:
            return reference
        return low
    ratio_percent = demand * 100 // supply
    ratio_percent = clamp(ratio_percent, CORRIDOR_LOW_PERCENT, CORRIDOR_HIGH_PERCENT)
    price = reference * ratio_percent // 100
    return clamp(price, low, high)


def vat_on_gross(gross: int, vat_bp: int = VAT_BP) -> int:
    if gross <= 0:
        return 0
    base = gross * LOAD_FULL_BP // (LOAD_FULL_BP + vat_bp)
    return gross - base
