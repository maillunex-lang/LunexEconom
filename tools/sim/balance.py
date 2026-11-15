"""Параметрический прогон окупаемости цепочки M1. Только целые числа.

Запуск из корня репозитория:

    python -m tools.sim balance
"""
from __future__ import annotations

from tools.sim.catalog import Catalog, salary_worker_draft
from tools.sim.engine import STAGE_OPERATIONAL, Engine
from tools.sim.formulas import (
    BRAND_M1,
    demand_units,
    price_attractiveness,
    rating,
    stage_costs,
)

CHAIN = ("field", "mill", "bakery", "store")
BUILDINGS = ("field", "mill", "bakery", "grocery_store")
HORIZON = 720
GOAL_LO = 15
GOAL_HI = 30


def _district() -> dict:
    return {
        "pop_permille": 1000,
        "layer_share_permille": 1000,
        "income_index": 1000,
        "traffic": 0,
        "appeal_permille": 1000,
        "competition_s": 1,
    }


def m1_scenario(
    capital: int,
    staffing_bp: int,
    shelf_price: int,
    days: int,
    salary_worker: int | None = None,
    overrides: dict | None = None,
) -> dict:
    scenario = {
        "id": "m1_balance",
        "days": days,
        "city": "ufa",
        "staffing_bp": staffing_bp,
        "district": _district(),
        "players": [{"id": "mira", "capital": capital}],
        "orders": [
            {"day": 1, "player": "mira", "enterprise": "field", "building": "field", "recipe": "field_grain"},
            {"day": 1, "player": "mira", "enterprise": "mill", "building": "mill", "recipe": "mill_flour"},
            {"day": 1, "player": "mira", "enterprise": "bakery", "building": "bakery", "recipe": "bakery_bread"},
            {"day": 1, "player": "mira", "enterprise": "store", "building": "grocery_store"},
        ],
        "links": [
            {
                "buyer": "mill",
                "product": "grain",
                "suppliers": [{"enterprise": "field", "priority": 1, "share": 100, "min_quality": 1}],
            },
            {
                "buyer": "bakery",
                "product": "flour",
                "suppliers": [{"enterprise": "mill", "priority": 1, "share": 100, "min_quality": 1}],
            },
            {
                "buyer": "store",
                "product": "bread",
                "max_price": "reference",
                "suppliers": [{"enterprise": "bakery", "priority": 1, "share": 100, "min_quality": 1}],
            },
        ],
        "cells": [{"enterprise": "store", "slot": 1, "product": "bread", "price": shelf_price}],
    }
    if salary_worker is not None:
        scenario["salary_worker"] = salary_worker
    if overrides:
        scenario["build_cost_overrides"] = dict(overrides)
    return scenario


def _dash(value) -> str:
    if value is None:
        return "-"
    return str(value)


def _clock(days) -> str:
    if days is None:
        return "-"
    minutes = days * 48
    return str(minutes) + "мин=" + str(minutes // 60) + "ч" + str(minutes % 60) + "м"


def walk(
    catalog: Catalog,
    capital: int,
    staffing_bp: int,
    shelf_price: int,
    days: int = HORIZON,
    salary_worker: int | None = None,
    overrides: dict | None = None,
) -> dict:
    scenario = m1_scenario(capital, staffing_bp, shelf_price, days, salary_worker, overrides)
    engine = Engine(scenario, catalog, days)
    start_money = engine.money("mira")
    op_day = {eid: None for eid in CHAIN}
    cash_back = {eid: None for eid in CHAIN}
    va_back = {eid: None for eid in CHAIN}
    chain_back = None
    first_sale = None
    arrears_days = 0
    tax_days = 0
    months: dict[int, dict[str, int]] = {}
    markers: dict[int, dict] = {}
    steady_made = 0
    steady_sold = 0
    steady_load = {eid: 0 for eid in CHAIN}
    for day in range(1, days + 1):
        engine.tick(day)
        player = engine.players["mira"]
        month = (day - 1) // 30 + 1
        bucket = months.setdefault(month, {"revenue": 0, "wages": 0, "tax": 0})
        bucket["revenue"] += player["revenue"]
        bucket["wages"] += player["wages_paid"]
        bucket["tax"] += player["tax_paid"]
        if player["tax_due"] > 0:
            tax_days += 1
        day_arrears = False
        all_op = True
        stages = {}
        for eid in CHAIN:
            ent = engine.enterprises.get(eid)
            stage = -1 if ent is None else ent["stage"]
            stages[eid] = stage
            if ent is not None and ent["arrears_due"] > 0:
                day_arrears = True
            if stage < STAGE_OPERATIONAL:
                all_op = False
            elif op_day[eid] is None:
                op_day[eid] = day
            if ent is None or stage < STAGE_OPERATIONAL:
                continue
            cash = ent["retail_gross"] - ent["retail_vat"] - ent["wage_charged"]
            added = ent["va"] - ent["wage_charged"]
            if cash_back[eid] is None and cash >= ent["build_cost"]:
                cash_back[eid] = day
            if va_back[eid] is None and added >= ent["build_cost"]:
                va_back[eid] = day
        if day_arrears:
            arrears_days += 1
        if first_sale is None and player["revenue"] > 0:
            first_sale = day
        if chain_back is None and all_op and engine.money("mira") >= start_money:
            chain_back = day
        if day in (1, 60) or day == days:
            markers[day] = {
                "money": engine.money("mira"),
                "stages": stages,
                "stalled": {
                    eid: bool(engine.enterprises[eid]["stalled"]) if eid in engine.enterprises else False
                    for eid in CHAIN
                },
                "invested": {
                    eid: engine.enterprises[eid]["invested"] if eid in engine.enterprises else 0
                    for eid in CHAIN
                },
            }
        if day == 45:
            steady_made = player["output"].get("bread", 0)
            steady_sold = player["sales"]
            for eid in CHAIN:
                ent = engine.enterprises.get(eid)
                steady_load[eid] = 0 if ent is None else ent["load_bp"]
    chain_op = all(op_day[eid] is not None for eid in CHAIN)
    chain_op_day = None
    if chain_op:
        chain_op_day = op_day["field"]
        for eid in CHAIN:
            if op_day[eid] > chain_op_day:
                chain_op_day = op_day[eid]
    month2 = months.get(2, {"revenue": 0, "wages": 0, "tax": 0})
    profit2 = month2["revenue"] - month2["wages"] - month2["tax"]
    bread = catalog.product("bread")
    reference = int(bread["reference_price"])
    score = price_attractiveness(reference, shelf_price)
    rank = rating(bread["rating_weights"], BRAND_M1, 50, score)
    pop = int(catalog.city("ufa")["population_estimate"])
    demand = demand_units(
        pop * 1000 // 1000,
        int(bread["base_demand_per_capita"]),
        1000,
        1000,
        shelf_price,
        reference,
        int(bread["elasticity"]),
        rank,
        1000,
    )
    full = 100 * staffing_bp // 10000
    if not chain_op:
        bottleneck = "деньги_стройка"
    elif arrears_days or tax_days:
        bottleneck = "деньги_просрочка"
    elif steady_sold < steady_made:
        bottleneck = "спрос"
    elif staffing_bp < 10000:
        bottleneck = "мощность_персонал"
    elif steady_made < full:
        bottleneck = "мощность_сырьё"
    else:
        bottleneck = "мощность_рецепт"
    return {
        "start_money": start_money,
        "end_money": engine.money("mira"),
        "min_money": engine.ledger.min_player.get("player:mira", engine.money("mira")),
        "op_day": op_day,
        "chain_op_day": chain_op_day,
        "chain_op": chain_op,
        "chain_payback": chain_back,
        "cash_payback": cash_back,
        "va_payback": va_back,
        "first_sale": first_sale,
        "arrears_days": arrears_days,
        "tax_days": tax_days,
        "month2_revenue": month2["revenue"],
        "month2_wages": month2["wages"],
        "month2_tax": month2["tax"],
        "month2_profit": profit2,
        "demand": demand,
        "steady_made": steady_made,
        "steady_sold": steady_sold,
        "steady_load": steady_load,
        "bottleneck": bottleneck,
        "markers": markers,
        "salary": engine.salary,
    }


def _affordable(row: dict) -> bool:
    return bool(row["chain_op"]) and row["arrears_days"] == 0 and row["tax_days"] == 0 and row["month2_profit"] >= 0


def min_capital(catalog: Catalog, staffing_bp: int, shelf_price: int, ceiling: int = 3000000) -> dict:
    """Наименьший капитал, при котором цепочка введена и за 120 суток нет просрочки.

    Месяц 2 должен быть неотрицательным: иначе запас только откладывает долг.
    """
    probe = walk(catalog, ceiling, staffing_bp, shelf_price, days=120)
    if not probe["chain_op"]:
        return {"capital": None, "reason": "не_введена_даже_при_" + str(ceiling), "probe_profit": probe["month2_profit"]}
    if probe["month2_profit"] < 0:
        return {"capital": None, "reason": "месяц_2_убыточен", "probe_profit": probe["month2_profit"]}
    if probe["arrears_days"] or probe["tax_days"]:
        return {"capital": None, "reason": "просрочка_даже_при_" + str(ceiling), "probe_profit": probe["month2_profit"]}
    lo = 0
    hi = ceiling
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        row = walk(catalog, mid, staffing_bp, shelf_price, days=120)
        if _affordable(row):
            hi = mid
        else:
            lo = mid
    edge = walk(catalog, hi, staffing_bp, shelf_price, days=120)
    below = walk(catalog, hi - 1, staffing_bp, shelf_price, days=120) if hi > 0 else None
    return {
        "capital": hi,
        "reason": "ок",
        "probe_profit": probe["month2_profit"],
        "edge_op": edge["chain_op"],
        "edge_arrears": edge["arrears_days"],
        "edge_tax": edge["tax_days"],
        "edge_profit": edge["month2_profit"],
        "below_op": None if below is None else below["chain_op"],
        "below_arrears": None if below is None else below["arrears_days"],
        "below_profit": None if below is None else below["month2_profit"],
    }


def _scaled(catalog: Catalog, permille: int) -> dict:
    overrides = {}
    for building_id in BUILDINGS:
        base = int(catalog.building(building_id)["build_cost"])
        cost = base * permille // 1000
        if cost < 1:
            cost = 1
        overrides[building_id] = cost
    return overrides


def _chain_payback_for(catalog: Catalog, capital: int, staffing_bp: int, shelf_price: int, overrides=None, salary=None):
    return walk(
        catalog,
        capital,
        staffing_bp,
        shelf_price,
        days=HORIZON,
        salary_worker=salary,
        overrides=overrides,
    )["chain_payback"]


def lowest_price_at_most(catalog: Catalog, limit: int, capital: int, staffing_bp: int) -> int | None:
    lo = 1
    hi = 20000
    answer = None
    while lo <= hi:
        mid = (lo + hi) // 2
        day = _chain_payback_for(catalog, capital, staffing_bp, mid)
        if day is not None and day <= limit:
            answer = mid
            hi = mid - 1
        else:
            lo = mid + 1
    return answer


def highest_permille_at_most(catalog: Catalog, limit: int, staffing_bp: int, shelf_price: int) -> int | None:
    lo = 1
    hi = 1000
    answer = None
    while lo <= hi:
        mid = (lo + hi) // 2
        overrides = _scaled(catalog, mid)
        capital = 0
        for cost in overrides.values():
            capital += cost
        day = _chain_payback_for(catalog, capital, staffing_bp, shelf_price, overrides)
        if day is not None and day <= limit:
            answer = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return answer


def render() -> str:
    catalog = Catalog()
    salary = salary_worker_draft(catalog.root)
    bread_ref = int(catalog.product("bread")["reference_price"])
    pop = int(catalog.city("ufa")["population_estimate"])
    costs = {building_id: int(catalog.building(building_id)["build_cost"]) for building_id in BUILDINGS}
    chain_cost = 0
    for cost in costs.values():
        chain_cost += cost
    lines = [
        "balance: draft",
        "горизонт=" + str(HORIZON),
        "город=ufa население=" + str(pop),
        "ставка=" + str(salary),
        "эталон_хлеба=" + str(bread_ref),
        "цель_суток=" + str(GOAL_LO) + ".." + str(GOAL_HI),
        "правило_времени=1_игровой_месяц_30_суток=24_реальных_часа; 1_сутки=48_реальных_минут",
        "окупаемость_цепочки=первые_сутки_когда_все_4_в_эксплуатации_и_деньги>=стартового_капитала",
        "окупаемость_здания_касса=розница-НДС-зарплата-содержание>=build_cost (трансфер внутри игрока 0)",
        "окупаемость_здания_тень=добавленная_стоимость_по_эталону-зарплата-содержание>=build_cost",
        "просрочка=arrears_здания_или_несписанный_НДС; оба останавливают выпуск в этом симуляторе",
        "капиталы_сетки=300000,600000,1000000,2000000",
        "персонал_bp=2500,5000,10000",
        "цены_полки=эталон*2//3, эталон, эталон*4//3",
        "",
        "стоимость_каталога",
    ]
    for building_id in BUILDINGS:
        parts = stage_costs(costs[building_id])
        lines.append(
            building_id
            + " build_cost="
            + str(costs[building_id])
            + " стадии="
            + ",".join(str(part) for part in parts)
            + " build_days="
            + str(int(catalog.building(building_id)["build_days"]))
        )
    lines.append("сумма_стройки=" + str(chain_cost))
    lines.append("")
    lines.append("порядок_оплаты сутки=1 (фундаменты всех заказов, затем каскад стадий)")
    lines.append("капитал деньги поле мельница пекарня магазин узкое")
    for capital in (200000, 300000, 600000, 899999, 900000, 1000000):
        row = walk(catalog, capital, 10000, bread_ref, days=60)
        mark = row["markers"][1]
        stages = []
        for eid in CHAIN:
            stage = mark["stages"][eid]
            stages.append("-" if stage < 0 else str(stage))
        lines.append(
            str(capital)
            + " "
            + str(mark["money"])
            + " "
            + " ".join(stages)
            + " "
            + row["bottleneck"]
        )
    capitals = (300000, 600000, 1000000, 2000000)
    staffs = (2500, 5000, 10000)
    prices = (bread_ref * 2 // 3, bread_ref, bread_ref * 4 // 3)
    lines.append("")
    lines.append(
        "сетка капитал персонал цена ввод первая_продажа окупаемость реальное месяц2_выручка месяц2_зп_содержание месяц2_ндс месяц2_прибыль мин_деньги просрочка_суток ндс_долг_суток спрос выпуск45 продано45 узкое"
    )
    grid = []
    for capital in capitals:
        for staffing in staffs:
            for price in prices:
                row = walk(catalog, capital, staffing, price, days=HORIZON)
                grid.append((capital, staffing, price, row))
                lines.append(
                    " ".join(
                        [
                            str(capital),
                            str(staffing),
                            str(price),
                            _dash(row["chain_op_day"]),
                            _dash(row["first_sale"]),
                            _dash(row["chain_payback"]),
                            _clock(row["chain_payback"]),
                            str(row["month2_revenue"]),
                            str(row["month2_wages"]),
                            str(row["month2_tax"]),
                            str(row["month2_profit"]),
                            str(row["min_money"]),
                            str(row["arrears_days"]),
                            str(row["tax_days"]),
                            str(row["demand"]),
                            str(row["steady_made"]),
                            str(row["steady_sold"]),
                            row["bottleneck"],
                        ]
                    )
                )
    lines.append("")
    lines.append("минимум_капитала_без_просрочки_и_с_вводом (поиск на 120 сутках, месяц2>=0)")
    lines.append("персонал цена капитал причина прибыль_края ниже_введена")
    for staffing in staffs:
        for price in prices:
            found = min_capital(catalog, staffing, price)
            lines.append(
                str(staffing)
                + " "
                + str(price)
                + " "
                + _dash(found["capital"])
                + " "
                + found["reason"]
                + " "
                + str(found["probe_profit"])
                + " "
                + _dash(found.get("below_op"))
            )
    ref_row = None
    for capital, staffing, price, row in grid:
        if capital == 1000000 and staffing == 10000 and price == bread_ref:
            ref_row = row
    if ref_row is None:
        ref_row = walk(catalog, 1000000, 10000, bread_ref, days=HORIZON)
    lines.append("")
    lines.append("здания_при_капитале_1000000_персонале_10000_цене_эталона")
    lines.append("здание build_cost ввод касса_окупаемость тень_окупаемость")
    for eid, building_id in zip(CHAIN, BUILDINGS):
        lines.append(
            eid
            + " "
            + str(costs[building_id])
            + " "
            + _dash(ref_row["op_day"][eid])
            + " "
            + _dash(ref_row["cash_payback"][eid])
            + " "
            + _dash(ref_row["va_payback"][eid])
        )
    lines.append(
        "цепочка - "
        + _dash(ref_row["chain_op_day"])
        + " "
        + _dash(ref_row["chain_payback"])
        + " "
        + _dash(ref_row["chain_payback"])
    )
    lines.append("первая_продажа=" + _dash(ref_row["first_sale"]))
    lines.append("месяц2_прибыль=" + str(ref_row["month2_profit"]))
    lines.append("спрос45=" + str(ref_row["demand"]) + " выпуск45=" + str(ref_row["steady_made"]))
    price_hi = lowest_price_at_most(catalog, GOAL_HI, 1000000, 10000)
    price_lo_fast = lowest_price_at_most(catalog, GOAL_LO, 1000000, 10000)
    lines.append("")
    lines.append("полка_при_каталоге_и_капитале_1000000_персонале_10000")
    lines.append("минимальная_цена_окупаемости_не_позже_30=" + _dash(price_hi))
    lines.append("минимальная_цена_окупаемости_не_позже_15=" + _dash(price_lo_fast))
    if price_hi is not None:
        slow = _chain_payback_for(catalog, 1000000, 10000, price_hi)
        lines.append("проверка_цены_" + str(price_hi) + "_окупаемость=" + _dash(slow))
        if price_hi > 1:
            prev = _chain_payback_for(catalog, 1000000, 10000, price_hi - 1)
            lines.append("проверка_цены_" + str(price_hi - 1) + "_окупаемость=" + _dash(prev))
    if price_lo_fast is not None:
        fast = _chain_payback_for(catalog, 1000000, 10000, price_lo_fast)
        lines.append("проверка_цены_" + str(price_lo_fast) + "_окупаемость=" + _dash(fast))
    perm_30 = highest_permille_at_most(catalog, GOAL_HI, 10000, bread_ref)
    perm_15 = highest_permille_at_most(catalog, GOAL_LO, 10000, bread_ref)
    lines.append("")
    lines.append("масштаб_стройки_при_цене_эталона_персонале_10000_капитале_равном_сумме_новых_цен")
    lines.append("макс_промилле_окупаемости_не_позже_30=" + _dash(perm_30))
    lines.append("макс_промилле_окупаемости_не_позже_15=" + _dash(perm_15))
    for label, permille in (("не_позже_30", perm_30), ("не_позже_15", perm_15)):
        if permille is None:
            continue
        overrides = _scaled(catalog, permille)
        capital = 0
        for cost in overrides.values():
            capital += cost
        day = _chain_payback_for(catalog, capital, 10000, bread_ref, overrides)
        parts = []
        for building_id in BUILDINGS:
            parts.append(building_id + "=" + str(overrides[building_id]))
        lines.append(
            label
            + " промилле="
            + str(permille)
            + " сумма="
            + str(capital)
            + " окупаемость="
            + _dash(day)
            + " "
            + " ".join(parts)
        )
        if permille < 1000:
            higher = _scaled(catalog, permille + 1)
            higher_capital = 0
            for cost in higher.values():
                higher_capital += cost
            higher_day = _chain_payback_for(catalog, higher_capital, 10000, bread_ref, higher)
            lines.append(
                "проверка_промилле_"
                + str(permille + 1)
                + "_сумма="
                + str(higher_capital)
                + "_окупаемость="
                + _dash(higher_day)
            )
    lines.append("")
    lines.append("ставка_при_каталоге_капитале_1000000_персонале_10000_цене_эталона")
    lines.append("ставка окупаемость месяц2_прибыль")
    for rate in (0, 50, 100, 200, 400):
        row = walk(catalog, 1000000, 10000, bread_ref, days=HORIZON, salary_worker=rate)
        lines.append(str(rate) + " " + _dash(row["chain_payback"]) + " " + str(row["month2_profit"]))
    ref_payback = ref_row["chain_payback"]
    inside = ref_payback is not None and GOAL_LO <= ref_payback <= GOAL_HI
    lines.append("")
    lines.append("цель_15_30_на_каталоге=" + ("да" if inside else "нет"))
    lines.append("окупаемость_каталога=" + _dash(ref_payback) + " " + _clock(ref_payback))
    if ref_payback is not None and ref_payback > 0:
        lines.append("оценка_суммы_на_30_суток=" + str(chain_cost * GOAL_HI // ref_payback))
        lines.append("оценка_суммы_на_15_суток=" + str(chain_cost * GOAL_LO // ref_payback))
    lines.append("конец")
    return "\n".join(lines) + "\n"
