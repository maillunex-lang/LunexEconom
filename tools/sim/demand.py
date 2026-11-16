"""Суточный спрос по районам и слоям. Только целые, деление вниз, остаток не теряется."""
from __future__ import annotations

from tools.sim.districts import allocate_layers, allocate_population, split_largest_remainder
from tools.sim.formulas import BRAND_M1, demand_breakdown, demand_units, price_attractiveness, rating


def attractiveness(rank: int, traffic: int, appeal_permille: int) -> int:
    """A = R * (1000 + traffic*10) * appeal // 1000000.

    Одно деление, иначе надбавка ниже 1000 ‰ обнуляется. При traffic=0 и appeal=1000
    результат равен R, как у сценариев M1.
    """
    bonus = traffic * 10
    return rank * (1000 + bonus) * appeal_permille // 1000000


def reference_rating(product: dict) -> int:
    """Полка без магазина: эталон, бренд M1, качество 50. Для хлеба это 70."""
    ref = int(product["reference_price"])
    score = price_attractiveness(ref, ref)
    return rating(product["rating_weights"], BRAND_M1, 50, score)


def _positive_int(value, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeError(f"{label} должно быть целым")
    return value


def _weight(appeal: int, sharp: int) -> int:
    weight = 1
    for _ in range(sharp):
        weight *= appeal if appeal > 0 else 0
    return weight


def _carry(raw: list[int], lost: list[int], gap: int, keys: list[str]) -> None:
    if gap < 0:
        raise RuntimeError("спрос районов превысил общий")
    if gap == 0:
        return
    order = sorted(range(len(raw)), key=lambda index: (-lost[index], keys[index]))
    cursor = 0
    while gap > 0:
        raw[order[cursor % len(order)]] += 1
        gap -= 1
        cursor += 1


def market_demand(
    population: int,
    product: dict,
    districts: list[dict],
    layers: list[dict],
    stores: list[dict],
    competition_s: int,
    ad_factor_permille: int,
    growth_bp: int = 0,
    growth_months: int = 0,
) -> dict:
    """Спрос товара по районам и слоям и доли магазинов района.

    Население города делится по pop_permille, остаток людей переносится.
    Слой считается формулой demand_units от населения района и доли слоя.
    Если у всех районов одна цена, один R и одна доля слоя, остаток формулы
    переносится так, что сумма спроса слоя равна спросу на всё население.
    Иначе общий спрос — сумма районных (остаток внутри района уже в формуле).
    Доля магазина — A^s, остаток штук переносится. Район без магазина
    оценивается эталонной полкой.
    """
    population = _positive_int(population, "население")
    if population < 0:
        raise RuntimeError("население отрицательное")
    growth_bp = _positive_int(growth_bp, "growth_bp")
    growth_months = _positive_int(growth_months, "growth_months")
    if growth_months < 0 or growth_bp < 0:
        raise RuntimeError("рост населения отрицательный")
    grown = population
    for _ in range(growth_months):
        grown += grown * growth_bp // 1000000
    sharp = _positive_int(competition_s, "competition_s")
    if sharp < 1 or sharp > 4:
        raise RuntimeError("острота конкуренции вне 1..4")
    ad_factor = _positive_int(ad_factor_permille, "ad_factor_permille")
    per_capita = int(product["base_demand_per_capita"])
    reference = int(product["reference_price"])
    elasticity = int(product["elasticity"])
    layer_ids = [str(layer["id"]) for layer in layers]
    incomes = {str(layer["id"]): int(layer["income_index_permille"]) for layer in layers}
    pops = allocate_population(grown, districts)
    floor_pops = [grown * int(row["pop_permille"]) // 1000 for row in districts]
    grouped: dict[str, list[dict]] = {str(row["id"]): [] for row in districts}
    for store in stores:
        district_id = str(store["district"])
        if district_id not in grouped:
            raise RuntimeError(f"магазин в неизвестном районе {district_id}")
        appeal = attractiveness(int(store["rating"]), int(store["traffic"]), int(store["appeal_permille"]))
        prepared = {
            "enterprise": str(store["enterprise"]),
            "player": str(store["player"]),
            "slot": int(store["slot"]),
            "district": district_id,
            "price": int(store["price"]),
            "rating": int(store["rating"]),
            "traffic": int(store["traffic"]),
            "appeal_permille": int(store["appeal_permille"]),
            "appeal": appeal,
            "weight": _weight(appeal, sharp),
            "share": 0,
        }
        grouped[district_id].append(prepared)
    for group in grouped.values():
        group.sort(key=lambda row: (row["enterprise"], row["slot"]))

    prices = []
    ratings = []
    raw: list[list[int]] = []
    lost: list[list[int]] = []
    for district in districts:
        group = grouped[str(district["id"])]
        if not group:
            price = reference
            avg_rating = reference_rating(product)
        else:
            weight_sum = 0
            for store in group:
                weight_sum += store["weight"]
            if weight_sum <= 0:
                price = sum(store["price"] for store in group) // len(group)
                avg_rating = sum(store["rating"] for store in group) // len(group)
            else:
                price = sum(store["price"] * store["weight"] for store in group) // weight_sum
                avg_rating = sum(store["rating"] * store["weight"] for store in group) // weight_sum
        prices.append(price)
        ratings.append(avg_rating)
        row_raw = []
        row_lost = []
        for layer_id in layer_ids:
            units, remainder = demand_breakdown(
                pops[len(prices) - 1],
                per_capita,
                int(district["layers_permille"][layer_id]),
                incomes[layer_id],
                price,
                reference,
                elasticity,
                avg_rating,
                ad_factor,
            )
            row_raw.append(units)
            row_lost.append(remainder)
        raw.append(row_raw)
        lost.append(row_lost)

    final = [list(row) for row in raw]
    gaps = []
    keys = [str(row["id"]) for row in districts]
    for layer_index, layer_id in enumerate(layer_ids):
        shares = [int(row["layers_permille"][layer_id]) for row in districts]
        uniform = all(share == shares[0] for share in shares)
        uniform = uniform and all(price == prices[0] for price in prices)
        uniform = uniform and all(avg_rating == ratings[0] for avg_rating in ratings)
        if not uniform:
            gaps.append(0)
            continue
        city_units, _city_lost = demand_breakdown(
            grown,
            per_capita,
            shares[0],
            incomes[layer_id],
            prices[0],
            reference,
            elasticity,
            ratings[0],
            ad_factor,
        )
        column = [row[layer_index] for row in final]
        gap = city_units - sum(column)
        _carry(column, [row[layer_index] for row in lost], gap, keys)
        for district_index, value in enumerate(column):
            final[district_index][layer_index] = value
        gaps.append(gap)

    district_rows = []
    for index, district in enumerate(districts):
        district_id = str(district["id"])
        layer_pops = allocate_layers(pops[index], layer_ids, district["layers_permille"])
        layer_rows = []
        for layer_index, layer in enumerate(layers):
            layer_id = str(layer["id"])
            layer_rows.append(
                {
                    "id": layer_id,
                    "share_permille": int(district["layers_permille"][layer_id]),
                    "population": layer_pops[layer_index],
                    "income_index_permille": incomes[layer_id],
                    "floor_demand": raw[index][layer_index],
                    "demand": final[index][layer_index],
                }
            )
        group = grouped[district_id]
        weights = [store["weight"] for store in group]
        for layer_index, _layer_id in enumerate(layer_ids):
            shares = split_largest_remainder(
                final[index][layer_index],
                weights,
                [f"{store['enterprise']}:{store['slot']}" for store in group],
            )
            for store, share in zip(group, shares):
                store["share"] += share
        district_rows.append(
            {
                "id": district_id,
                "name": str(district["name"]),
                "type": str(district["type"]),
                "pop_permille": int(district["pop_permille"]),
                "population": pops[index],
                "floor_population": floor_pops[index],
                "traffic": int(district["traffic"]),
                "appeal_permille": int(district["appeal_permille"]),
                "price": prices[index],
                "rating": ratings[index],
                "floor_demand": sum(raw[index]),
                "demand": sum(final[index]),
                "layers": layer_rows,
                "stores": group,
            }
        )
    floor_demand = 0
    city_demand = 0
    for row in district_rows:
        floor_demand += row["floor_demand"]
        city_demand += row["demand"]
    return {
        "product": str(product["id"]),
        "population": grown,
        "base_population": population,
        "growth_bp": growth_bp,
        "growth_months": growth_months,
        "per_capita": per_capita,
        "reference_price": reference,
        "elasticity": elasticity,
        "ad_factor_permille": ad_factor,
        "competition_s": sharp,
        "floor_population_sum": sum(floor_pops),
        "population_remainder": grown - sum(floor_pops),
        "floor_demand": floor_demand,
        "remainder": sum(gaps),
        "demand": city_demand,
        "districts": district_rows,
    }


def sensitivity_rows(
    population: int,
    per_capita: int,
    layer_share_permille: int,
    income_index: int,
    reference: int,
    elasticity: int,
    prices: list[int],
    ratings: list[int],
    ad_factor_permille: int = 1000,
) -> list[dict]:
    rows = []
    for price in prices:
        for avg_rating in ratings:
            rows.append(
                {
                    "price": price,
                    "rating": avg_rating,
                    "demand": demand_units(
                        population,
                        per_capita,
                        layer_share_permille,
                        income_index,
                        price,
                        reference,
                        elasticity,
                        avg_rating,
                        ad_factor_permille,
                    ),
                }
            )
    return rows
