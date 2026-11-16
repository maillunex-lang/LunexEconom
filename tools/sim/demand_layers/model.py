"""Детерминированный агрегированный спрос по четырём типам городов.

Изолированный дизайн-симулятор; не меняет существующую M1/M2, сервер, кошельки.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools.sim.districts import split_largest_remainder

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "tools" / "sim" / "data" / "demand_proposed"
CATALOG = ROOT / "server" / "data" / "products.json"
LAYERS = ("poor", "lower_middle", "middle", "affluent")
AGES = ("youth", "families", "pensioners")


def load_inputs():
    def read(name):
        return json.loads(DATA.joinpath(name).read_text(encoding="utf-8"), parse_float=_no_float)
    profiles = read("profiles.json")
    cities = read("cities.json")
    params = read("parameters.json")
    products = json.loads(CATALOG.read_text(encoding="utf-8"), parse_float=_no_float)
    if hashlib.sha256(CATALOG.read_bytes()).hexdigest() != profiles["source_catalog_sha256"]:
        raise ValueError("Каталог обновлён: пересмотрите корзины, не используйте старые коэффициенты")
    if len(products) != 41 or len({p["id"] for p in products}) != 41:
        raise ValueError("Ожидается 41 уникальный товар")
    ids = {p["id"] for p in products}
    consumer = {p["id"] for p in products if p["consumer"]}
    if len(consumer) != 20:
        raise ValueError("Состав потребительских товаров изменён")
    baskets = profiles["baskets"]
    if {(b["layer"], b["age"]) for b in baskets} != {(l, a) for l in LAYERS for a in AGES}:
        raise ValueError("Нужна корзина для каждой пары слой × возраст")
    for basket in baskets:
        shares = basket["shares_permille"]
        if set(shares) != ids or sum(shares.values()) != 1000:
            raise ValueError("Не все 41 SKU представлены либо сумма корзины неверна")
        if any(shares[id] != 0 for id in ids - consumer):
            raise ValueError("Сырьё нельзя продавать напрямую жителям")
    for city in cities["cities"]:
        if set(city["income_shares_bp"]) != set(LAYERS) or sum(city["income_shares_bp"].values()) != 10000:
            raise ValueError("Неверные доли доходов города")
        if set(city["age_shares_bp"]) != set(AGES) or sum(city["age_shares_bp"].values()) != 10000:
            raise ValueError("Неверные возрастные доли города")
    _check_integral({"profiles": profiles, "cities": cities, "params": params, "products": products})
    return profiles, cities, params, products


def _no_float(value):
    raise ValueError("Запрещены дробные числа: " + value)


def _check_integral(value):
    if isinstance(value, dict):
        for v in value.values():
            _check_integral(v)
    elif isinstance(value, list):
        for v in value:
            _check_integral(v)
    elif isinstance(value, bool):
        return
    elif not isinstance(value, (int, str)) and value is not None:
        raise TypeError("Только целые числа")


def _clamp(value, lower, upper):
    return max(lower, min(upper, value))


def migrate_shares(shares, wage_signal_permille, params):
    """Месячные переходы соседних доходных слоёв, без изменения числа жителей."""
    new = dict(shares)
    gap = wage_signal_permille - 1000
    # Величина зависит от оплаченных рабочих мест и зарплаты; без них движения нет.
    cap = params["monthly_migration_cap_bp"]
    move = min(cap, abs(gap) // 3)
    if move == 0:
        return new
    if gap > 0:
        edges = (("poor", "lower_middle"), ("lower_middle", "middle"), ("middle", "affluent"))
    else:
        edges = (("affluent", "middle"), ("middle", "lower_middle"), ("lower_middle", "poor"))
    # Одновременные переводы со снимка, не перевозим одного человека через 3 слоя за месяц.
    transfers = []
    for src, dest in edges:
        allowed = shares[src]
        if src == "poor":
            allowed = max(0, allowed - params["poor_safety_floor_bp"])
        transfers.append((src, dest, min(move, allowed)))
    for src, dest, quantity in transfers:
        new[src] -= quantity
        new[dest] += quantity
    assert sum(new.values()) == 10000 and all(v >= 0 for v in new.values())
    return new


def _wage_signal(city, month, params):
    # Не предполагаем, что зарплата каждого жителя равна зарплате за штатную единицу.
    # Это только прокси силы рынка труда, основанный на оплаченных местах игроков.
    jobs_per_1000 = 180 + (month // 6) * 8
    paid_jobs = jobs_per_1000 * city["population"] // 1000
    wage_per_job = params["salary_per_job_rub"] * city["salary_index_permille"] // 1000
    wage_fund = paid_jobs * wage_per_job
    # Вся зарплата не должна порождать новый доход при отсутствии живых рабочих мест.
    signal = 1000 + ((wage_per_job - params["wage_anchor_rub"]) * 3)
    signal += (jobs_per_1000 - 180) * 2
    return _clamp(signal, 750, 1250), paid_jobs, wage_fund


def _income(layer, age, city, params):
    # Источники рублёвых денег агрегированы; зарплата от предприятий к жителям,
    # но бюджет системы не является бесплатной эмиссией.
    salary = layer["salary_rub"] * age["salary_weight_permille"] * city["salary_index_permille"] // 1000000
    pension = layer["pension_rub"] * age["pension_weight_permille"] // 1000
    benefit = layer["benefit_rub"] * age["benefit_weight_permille"] // 1000
    return max(1, salary + pension + benefit)


def _matrix_population(population, income_shares, age_shares):
    by_layer = split_largest_remainder(population, [income_shares[l] for l in LAYERS], list(LAYERS))
    matrix = {}
    for layer, count in zip(LAYERS, by_layer):
        ages = split_largest_remainder(count, [age_shares[a] for a in AGES], list(AGES))
        for age, n in zip(AGES, ages):
            matrix[(layer, age)] = n
    assert sum(matrix.values()) == population
    return matrix


def _month(city, shares, profiles, params, products, price_indices):
    layers = {x["id"]: x for x in profiles["layers"]}
    ages = {x["id"]: x for x in profiles["ages"]}
    basket = {(x["layer"], x["age"]): x["shares_permille"] for x in profiles["baskets"]}
    people = _matrix_population(city["population"], shares, city["age_shares_bp"])
    # Один набор SKU по городу, а не одна покупка на каждого жителя.
    wanted = {p["id"]: 0 for p in products}
    wanted_by_layer_sku = {layer: {p["id"]: 0 for p in products} for layer in LAYERS}
    total_income = 0
    saved = 0
    for (layer_id, age_id), count in people.items():
        if not count:
            continue
        layer = layers[layer_id]
        age = ages[age_id]
        income_per = _income(layer, age, city, params)
        gross = count * income_per
        total_income += gross
        saved += gross * layer["savings_permille"] // 1000
        goods = gross * layer["goods_budget_permille"] * age["goods_budget_factor_permille"] // 1000000
        goods = min(goods, gross - gross * layer["savings_permille"] // 1000)
        row = basket[(layer_id, age_id)]
        spend = split_largest_remainder(goods, [row[p["id"]] for p in products], [p["id"] for p in products])
        for product, rub in zip(products, spend):
            if rub <= 0 or not product["consumer"]:
                continue
            sku = product["id"]
            price = max(1, product["reference_price"] * price_indices[sku] // 1000)
            # Взвешенная эластичность с более сильной реакцией малоимущих.
            elasticity = layer["elasticity_permille"]
            response = _clamp(1000 - (price_indices[sku] - 1000) * elasticity // 1000, 300, 1500)
            quantity = rub * params["quantity_per_1000_goods_budget_rub"] * response // (1000 * price)
            wanted[sku] += quantity
            wanted_by_layer_sku[layer_id][sku] += quantity
    return wanted, wanted_by_layer_sku, people, total_income, saved


def run(months=24):
    if isinstance(months, bool) or not isinstance(months, int) or months < 24 or months > 120:
        raise ValueError("Требуется 24..120 игровых месяцев")
    profiles, data, params, products = load_inputs()
    retail = [p for p in products if p["consumer"]]
    output = {"model": "demand-v1-draft", "months": months, "cities": {}}
    for city in data["cities"]:
        shares = dict(city["income_shares_bp"])
        prices = {p["id"]: 1000 for p in retail}
        supply = {p["id"]: city["availability_permille"] for p in retail}
        history = []
        for month in range(1, months + 1):
            wage_signal, paid_jobs, wage_fund = _wage_signal(city, month, params)
            shares = migrate_shares(shares, wage_signal, params)
            desired, desired_by_layer, people, income, savings = _month(city, shares, profiles, params, products, prices)
            # Продажи по SKU делим между группами по весу их спроса на этот SKU.
            # Запасы и полка ограничивают факт продаж; непокупки не перераспределяются.
            layer_sales = {layer: 0 for layer in LAYERS}
            shortage = {}
            surplus = {}
            sold_value = 0
            sold_units = 0
            demand_units = 0
            for product in retail:
                sku = product["id"]
                demand = desired[sku]
                demand_units += demand
                available = demand * supply[sku] // 1000
                capacity = city["population"] * params["store_capacity_units_per_1000_people"] // 1000
                accessible = min(demand, available, capacity)
                sold = accessible * params["retail_capture_permille"] // 1000
                unsold = demand - sold
                excess = max(0, available - sold)
                price = max(1, product["reference_price"] * prices[sku] // 1000)
                revenue = sold * price
                sold_value += revenue
                sold_units += sold
                shortage[sku] = unsold
                surplus[sku] = excess
                allocation = split_largest_remainder(revenue, [desired_by_layer[x][sku] for x in LAYERS], list(LAYERS))
                for layer, amount in zip(LAYERS, allocation):
                    layer_sales[layer] += amount
                # Умеренное движение цен: базовая инфляция и реакция на нехватку.
                shortage_bp = unsold * 10000 // max(1, demand)
                price_change = params["reference_inflation_monthly_bp"] + (shortage_bp - 3000) // 220
                price_change = _clamp(price_change, -params["price_response_max_monthly_bp"], params["price_response_max_monthly_bp"])
                prices[sku] = _clamp(prices[sku] * (10000 + price_change) // 10000, params["price_multiplier_min_permille"], params["price_multiplier_max_permille"])
                # Лёгкое улучшение предложения, без бесконечного бесплатного стока.
                supply[sku] = _clamp(supply[sku] * city["supply_growth_permille"] // 1000, params["goods_available_min_permille"], 1000)
            inflation_index = sum(prices.values()) // len(prices)
            row = {
                "month": month,
                "population": city["population"],
                "income_shares_bp": dict(shares),
                "poor_share_bp": shares["poor"],
                "paid_jobs": paid_jobs,
                "wage_fund_rub": wage_fund,
                "wage_signal_permille": wage_signal,
                "household_income_rub": income,
                "savings_rub": savings,
                "inflation_index_permille": inflation_index,
                "retail_revenue_rub": sold_value,
                "retail_revenue_by_layer_rub": layer_sales,
                "wanted_units": demand_units,
                "wanted_units_by_sku": desired,
                "sold_units": sold_units,
                "shortage_units_by_sku": shortage,
                "surplus_units_by_sku": surplus,
                "shortage_units": sum(shortage.values()),
                "surplus_units": sum(surplus.values())
            }
            assert sold_units <= demand_units
            assert sum(layer_sales.values()) == sold_value
            assert sum(shares.values()) == 10000
            history.append(row)
        output["cities"][city["id"]] = {
            "population_initial": city["population"],
            "population_final": city["population"],
            "first": history[0],
            "last": history[-1],
            "minimum_poor_share_bp": min(r["poor_share_bp"] for r in history),
            "maximum_poor_share_bp": max(r["poor_share_bp"] for r in history),
            "minimum_retail_revenue_rub": min(r["retail_revenue_rub"] for r in history),
            "history": history
        }
    _check_integral(output)
    return output


def rebuild_golden(months=24):
    output = run(months)
    target = DATA / "golden_24_months.json"
    target.write_text(json.dumps(output, sort_keys=True, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


if __name__ == "__main__":
    print(rebuild_golden())
