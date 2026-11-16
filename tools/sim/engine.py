"""Суточный тик цепочки M1. Только целые числа, без случайности."""
from __future__ import annotations

import json
from pathlib import Path

from tools.sim.catalog import Catalog, read_flag, salary_worker_draft
from tools.sim.demand import market_demand
from tools.sim.districts import load_city_districts
from tools.sim.formulas import (
    BRAND_M1,
    LOAD_FULL_BP,
    clearing_price,
    demand_units,
    load_bp,
    monthly_expense,
    price_attractiveness,
    rating,
    stage_costs,
    stage_day_lengths,
    vat_on_gross,
)
from tools.sim.ledger import Ledger

SIM_VERSION = 1
STAGE_OPERATIONAL = 4


def _int(value, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeError(f"{label} должно быть целым")
    return value


def _slot() -> dict:
    return {"quantity": 0, "quality": 50, "input_carry": 0, "output_carry": 0}


class Engine:
    def __init__(self, scenario: dict, catalog: Catalog, days: int):
        self.scenario = scenario
        self.catalog = catalog
        self.days = days
        self.city_id = str(scenario["city"])
        self.city = catalog.city(self.city_id)
        self.salary = salary_worker_draft(catalog.root)
        if "salary_worker" in scenario:
            self.salary = _int(scenario["salary_worker"], "salary_worker")
            if self.salary < 0:
                raise RuntimeError("ставка зарплаты отрицательная")
        self.wear_step = read_flag("enterprise_wear_month_draft", catalog.root)
        self.default_staff = read_flag("enterprise_staffing_bp_draft", catalog.root)
        self.scenario_staff = self._staffing_value(scenario.get("staffing_bp", self.default_staff))
        self.ledger = Ledger()
        self.players: dict[str, dict] = {}
        self.enterprises: dict[str, dict] = {}
        self.links: list[dict] = []
        self.cells: list[dict] = []
        self.orders: list[dict] = list(scenario.get("orders") or [])
        self.infusions: list[dict] = list(scenario.get("infusions") or [])
        self.m2 = "districts_file" in scenario
        self.demand_report: list[dict] = []
        self.district_book: dict | None = None
        if self.m2:
            if "district" in scenario:
                raise RuntimeError("сценарий M2 не задаёт одиночный district")
            self.district_book = load_city_districts(self._districts_path())
            self.district = None
        else:
            self.district = scenario["district"]
        self._prepare()

    def _prepare(self) -> None:
        for row in self.scenario["players"]:
            pid = str(row["id"])
            capital = self._capital(row["capital"], pid)
            if capital < 0:
                raise RuntimeError("капитал отрицательный")
            self.players[pid] = {
                "id": pid,
                "tax_due": 0,
                "vat_month": 0,
                "output": {},
                "sales": 0,
                "revenue": 0,
                "tax": 0,
                "wages_paid": 0,
                "tax_paid": 0,
            }
            account = "player:" + pid
            posted = self.ledger.post(
                "initial-capital:" + pid,
                [(account, capital), ("system:treasury", -capital)],
            )
            if posted is None:
                raise RuntimeError("стартовый капитал не проведён")
        for row in self.scenario.get("links") or []:
            suppliers = list(row.get("suppliers") or [])
            if len(suppliers) > 3:
                raise RuntimeError("у входа больше трёх поставщиков")
            cleaned = []
            for sup in suppliers:
                cleaned.append(
                    {
                        "enterprise": str(sup["enterprise"]),
                        "priority": _int(sup.get("priority", 1), "priority"),
                        "share": _int(sup.get("share", 100), "share"),
                        "min_quality": _int(sup.get("min_quality", 1), "min_quality"),
                        "max_price": self._money_limit(sup.get("max_price"), str(row["product"])),
                        "price": None if sup.get("price") is None else _int(sup["price"], "price"),
                    }
                )
            cleaned.sort(key=lambda item: (item["priority"], item["enterprise"]))
            self.links.append(
                {
                    "buyer": str(row["buyer"]),
                    "product": str(row["product"]),
                    "max_price": self._money_limit(row.get("max_price"), str(row["product"])),
                    "suppliers": cleaned,
                }
            )
        for row in self.scenario.get("cells") or []:
            self.cells.append(
                {
                    "enterprise": str(row["enterprise"]),
                    "slot": _int(row["slot"], "slot"),
                    "product": str(row["product"]),
                    "price_spec": row["price"],
                    "min_stock": None if row.get("min_stock") is None else _int(row["min_stock"], "min_stock"),
                }
            )
        for row in self.scenario.get("fixtures") or []:
            self._open_fixture(row)

    def _districts_path(self) -> Path:
        relative = Path(str(self.scenario["districts_file"]))
        if relative.is_absolute():
            return relative
        return self.catalog.root.joinpath(relative)

    def _open_fixture(self, row: dict) -> None:
        building = self.catalog.building(str(row["building"]))
        if not building.get("retail_cells"):
            raise RuntimeError("fixture M2 поддерживает только магазин")
        blank = {
            "player": str(row["player"]),
            "enterprise": str(row["enterprise"]),
        }
        if "staffing_bp" in row:
            blank["staffing_bp"] = row["staffing_bp"]
        ent = self._blank_enterprise(blank, building, None, self._build_cost_of(building))
        ent["stage"] = STAGE_OPERATIONAL
        district_id = str(row["district"])
        known = {str(item["id"]) for item in self.district_book["districts"]}
        if district_id not in known:
            raise RuntimeError(f"неизвестный район {district_id}")
        ent["district"] = district_id
        for product, spec in (row.get("stock") or {}).items():
            if isinstance(spec, bool) or isinstance(spec, int):
                qty = _int(spec, "запас")
                quality = 50
            else:
                qty = _int(spec["quantity"], "запас")
                quality = _int(spec.get("quality", 50), "качество")
            if quality < 1 or quality > 100:
                raise RuntimeError("качество запаса вне 1..100")
            self.add_goods(ent, str(product), qty, quality)
        self.enterprises[ent["id"]] = ent

    def _district_views(self, day: int) -> list[dict]:
        layer_ids = [str(layer["id"]) for layer in self.district_book["layers"]]
        views = []
        for src in self.district_book["districts"]:
            row = dict(src)
            row["layers_permille"] = dict(src["layers_permille"])
            for shift in self.scenario.get("layer_shifts") or []:
                if _int(shift["day"], "день сдвига слоёв") != day:
                    continue
                target = shift.get("district")
                if target is not None and str(target) != row["id"]:
                    continue
                shares = shift.get("layers_permille")
                if not isinstance(shares, dict) or set(shares) != set(layer_ids):
                    raise RuntimeError("сдвиг слоёв не покрывает четыре слоя")
                cleaned = {}
                for layer_id in layer_ids:
                    cleaned[layer_id] = _int(shares[layer_id], layer_id)
                    if cleaned[layer_id] < 0:
                        raise RuntimeError("доля слоя отрицательная")
                if sum(cleaned.values()) != 1000:
                    raise RuntimeError("доли слоёв после сдвига не 1000")
                row["layers_permille"] = cleaned
            views.append(row)
        return views

    def _money_limit(self, raw, product: str) -> int | None:
        if raw is None:
            return None
        if raw == "reference":
            return int(self.catalog.product(product)["reference_price"])
        return _int(raw, "max_price")

    def _staffing_value(self, raw) -> int:
        value = _int(raw, "staffing_bp")
        if value < 0 or value > LOAD_FULL_BP:
            raise RuntimeError("staffing_bp вне 0..10000")
        if value > self.default_staff:
            return self.default_staff
        return value

    def _build_cost_of(self, building: dict) -> int:
        overrides = self.scenario.get("build_cost_overrides") or {}
        building_id = str(building["id"])
        if building_id in overrides:
            return _int(overrides[building_id], "build_cost")
        return int(building["build_cost"])

    def _capital(self, raw, pid: str) -> int:
        if isinstance(raw, dict):
            building_id = raw.get("equals_build_cost")
            if not isinstance(building_id, str):
                raise RuntimeError(f"капитал {pid} задан неверно")
            return int(self.catalog.building(building_id)["build_cost"])
        return _int(raw, f"капитал {pid}")

    def account(self, pid: str) -> str:
        return "player:" + pid

    def money(self, pid: str) -> int:
        return self.ledger.balance(self.account(pid))

    def blocked(self, ent: dict) -> bool:
        if ent["arrears_due"] > 0:
            return True
        if self.players[ent["player"]]["tax_due"] > 0:
            return True
        return False

    def operational(self, ent: dict) -> bool:
        return ent["stage"] >= STAGE_OPERATIONAL and ent["running"] and not self.blocked(ent)

    def qty(self, ent: dict, product: str) -> int:
        return ent["stock"].get(product, {}).get("quantity", 0)

    def quality_of(self, ent: dict, product: str) -> int:
        return ent["stock"].get(product, {}).get("quality", 50)

    def ensure(self, ent: dict, product: str) -> dict:
        slot = ent["stock"].get(product)
        if slot is None:
            slot = _slot()
            ent["stock"][product] = slot
        return slot

    def add_goods(self, ent: dict, product: str, qty: int, quality: int) -> None:
        if qty <= 0:
            return
        slot = self.ensure(ent, product)
        old = slot["quantity"]
        total = old + qty
        if total <= 0:
            return
        slot["quality"] = (old * slot["quality"] + qty * quality) // total
        slot["quantity"] = total

    def take_goods(self, ent: dict, product: str, qty: int) -> int:
        slot = self.ensure(ent, product)
        if qty > slot["quantity"]:
            raise RuntimeError("склад ушёл в минус")
        quality = slot["quality"]
        slot["quantity"] -= qty
        return quality

    def occupied(self, ent: dict) -> int:
        total = 0
        for slot in ent["stock"].values():
            total += slot["quantity"]
        return total

    def tick(self, day: int) -> None:
        for player in self.players.values():
            player["output"] = {}
            player["sales"] = 0
            player["revenue"] = 0
            player["tax"] = 0
            player["wages_paid"] = 0
            player["tax_paid"] = 0
        self._infusions(day)
        self._settle_debts(day)
        self._production(day)
        self._links(day)
        self._market(day)
        self._retail(day)
        self._projects(day)
        if day % 30 == 0:
            self._close_month(day // 30)
        self.ledger.audit()

    def _infusions(self, day: int) -> None:
        for row in self.infusions:
            if _int(row["day"], "день пополнения") != day:
                continue
            pid = str(row["player"])
            amount = _int(row["amount"], "сумма пополнения")
            if amount <= 0:
                continue
            posted = self.ledger.post(
                f"infusion:{pid}:{day}",
                [(self.account(pid), amount), ("system:treasury", -amount)],
            )
            if posted is None:
                raise RuntimeError("пополнение не проведено")

    def _settle_debts(self, day: int) -> None:
        for eid in sorted(self.enterprises):
            ent = self.enterprises[eid]
            due = ent["arrears_due"]
            if due <= 0:
                continue
            if self.money(ent["player"]) < due:
                continue
            posted = self.ledger.post(
                f"enterprise:upkeep:{eid}:settle:{day}",
                [(self.account(ent["player"]), -due), ("system:upkeep", due)],
            )
            if posted is None:
                continue
            ent["arrears_due"] = 0
            ent["arrears_months"] = 0
            self.players[ent["player"]]["wages_paid"] += due
        for pid in sorted(self.players):
            due = self.players[pid]["tax_due"]
            if due <= 0:
                continue
            if self.money(pid) < due:
                continue
            posted = self.ledger.post(
                f"vat:{pid}:settle:{day}",
                [(self.account(pid), -due), ("system:treasury", due)],
            )
            if posted is None:
                continue
            self.players[pid]["tax_due"] = 0
            self.players[pid]["tax_paid"] += due

    def _production(self, day: int) -> None:
        for eid in sorted(self.enterprises):
            ent = self.enterprises[eid]
            ent["load_bp"] = 0
            ent["made"] = {}
            if ent["stage"] < STAGE_OPERATIONAL or not ent["running"] or ent["recipe_id"] is None:
                continue
            if self.blocked(ent):
                continue
            recipe = self.catalog.recipe_for(ent["recipe_id"])
            staff = ent["staffing_bp"]
            if staff > self.default_staff:
                staff = self.default_staff
            load = load_bp(ent["stock"], recipe, ent["storage_capacity"], staff)
            ent["load_bp"] = load
            ent["loads"].append(load)
            qualities = {product: self.quality_of(ent, product) for product in recipe["inputs"]}
            input_value = 0
            for product, volume in recipe["inputs"].items():
                slot = self.ensure(ent, product)
                used, carry = divmod(volume * load + slot["input_carry"], LOAD_FULL_BP)
                if used:
                    self.take_goods(ent, product, used)
                    input_value += used * int(self.catalog.product(product)["reference_price"])
                slot["input_carry"] = carry
            weight_sum = 0
            weighted = 0
            for product, volume in recipe["inputs"].items():
                weight_sum += volume
                weighted += qualities[product] * volume
            quality = weighted // weight_sum if weight_sum else 50
            output_value = 0
            for product, volume in recipe["outputs"].items():
                slot = self.ensure(ent, product)
                made, carry = divmod(volume * load + slot["output_carry"], LOAD_FULL_BP)
                slot["output_carry"] = carry
                if made:
                    self.add_goods(ent, product, made, quality)
                    ent["made"][product] = made
                    output_value += made * int(self.catalog.product(product)["reference_price"])
                    bucket = self.players[ent["player"]]["output"]
                    bucket[product] = bucket.get(product, 0) + made
            ent["va"] += output_value - input_value
            if self.occupied(ent) > ent["storage_capacity"]:
                raise RuntimeError("склад переполнен после выпуска")

    def _link_for(self, buyer: str, product: str) -> dict | None:
        for link in self.links:
            if link["buyer"] == buyer and link["product"] == product:
                return link
        return None

    def _supplier_daily(self, buyer: str, product: str) -> int:
        link = self._link_for(buyer, product)
        if link is None:
            return 0
        total = 0
        for sup in link["suppliers"]:
            ent = self.enterprises.get(sup["enterprise"])
            if ent is None or ent["recipe_id"] is None:
                continue
            recipe = self.catalog.recipe_for(ent["recipe_id"])
            total += int(recipe["outputs"].get(product, 0))
        return total

    def _needs(self, ent: dict) -> dict[str, int]:
        if not self.operational(ent):
            return {}
        if ent["recipe_id"] is not None:
            recipe = self.catalog.recipe_for(ent["recipe_id"])
            needs = {}
            for product, volume in recipe["inputs"].items():
                gap = volume - self.qty(ent, product)
                if gap > 0:
                    needs[product] = gap
            return needs
        needs = {}
        for cell in self.cells:
            if cell["enterprise"] != ent["id"]:
                continue
            product = cell["product"]
            if cell["min_stock"] is not None:
                target = cell["min_stock"]
            else:
                target = self._supplier_daily(ent["id"], product)
            gap = target - self.qty(ent, product)
            if gap > 0:
                needs[product] = needs.get(product, 0) + gap
        return needs

    def _links(self, day: int) -> None:
        for eid in sorted(self.enterprises):
            buyer = self.enterprises[eid]
            for product, need in sorted(self._needs(buyer).items()):
                link = self._link_for(eid, product)
                if link is None or need <= 0:
                    continue
                suppliers = link["suppliers"]
                portions = [need * sup["share"] // 100 for sup in suppliers]
                if suppliers and sum(sup["share"] for sup in suppliers) == 100:
                    portions[0] += need - sum(portions)
                for sup, portion in zip(suppliers, portions):
                    if portion <= 0 or need <= 0:
                        continue
                    source = self.enterprises.get(sup["enterprise"])
                    if source is None or source["stage"] < STAGE_OPERATIONAL:
                        continue
                    have = self.qty(source, product)
                    if have <= 0:
                        continue
                    if self.quality_of(source, product) < sup["min_quality"]:
                        continue
                    move = portion
                    if move > have:
                        move = have
                    if move > need:
                        move = need
                    free = buyer["storage_capacity"] - self.occupied(buyer)
                    if move > free:
                        move = free
                    if move <= 0:
                        continue
                    unit = self._transfer_price(buyer, source, product, sup)
                    if sup["max_price"] is not None and unit > sup["max_price"]:
                        continue
                    if not self._pay_transfer(day, buyer, source, product, move, unit):
                        continue
                    quality = self.take_goods(source, product, move)
                    self.add_goods(buyer, product, move, quality)
                    need -= move

    def _transfer_price(self, buyer: dict, source: dict, product: str, sup: dict) -> int:
        if buyer["player"] == source["player"]:
            return 0
        if sup["price"] is not None:
            return sup["price"]
        return int(self.catalog.product(product)["reference_price"])

    def _pay_transfer(self, day: int, buyer: dict, source: dict, product: str, qty: int, unit: int) -> bool:
        if unit <= 0 or buyer["player"] == source["player"]:
            return True
        cost = qty * unit
        if self.money(buyer["player"]) < cost:
            return False
        posted = self.ledger.post(
            f"link:{buyer['id']}:{source['id']}:{product}:{day}",
            [
                (self.account(buyer["player"]), -cost),
                (self.account(source["player"]), cost),
            ],
        )
        return posted is not None

    def _market(self, day: int) -> None:
        demands: dict[str, list[tuple[str, int, int | None]]] = {}
        offers: dict[str, list[tuple[str, int]]] = {}
        for eid in sorted(self.enterprises):
            ent = self.enterprises[eid]
            if ent["stage"] < STAGE_OPERATIONAL:
                continue
            if self.operational(ent):
                for product, gap in self._needs(ent).items():
                    link = self._link_for(eid, product)
                    cap = None if link is None else link["max_price"]
                    demands.setdefault(product, []).append((eid, gap, cap))
            if ent["sell_to_market"] and ent["recipe_id"] is not None:
                recipe = self.catalog.recipe_for(ent["recipe_id"])
                for product in sorted(recipe["outputs"]):
                    have = self.qty(ent, product)
                    if have > 0:
                        offers.setdefault(product, []).append((eid, have))
        products = sorted(set(demands) | set(offers))
        self.market_rows = []
        for product in products:
            buyers = demands.get(product, [])
            sellers = offers.get(product, [])
            demand = 0
            for _, gap, _ in buyers:
                demand += gap
            supply = 0
            for _, have in sellers:
                supply += have
            if demand <= 0 and supply <= 0:
                continue
            reference = int(self.catalog.product(product)["reference_price"])
            price = clearing_price(reference, demand, supply)
            bought: list[tuple[str, int]] = []
            bought_total = 0
            for eid, gap, cap in buyers:
                if cap is not None and price > cap:
                    continue
                ent = self.enterprises[eid]
                qty = gap
                free = ent["storage_capacity"] - self.occupied(ent)
                if qty > free:
                    qty = free
                if price > 0:
                    affordable = self.money(ent["player"]) // price
                    if qty > affordable:
                        qty = affordable
                if qty <= 0:
                    continue
                cost = qty * price
                if cost > 0:
                    posted = self.ledger.post(
                        f"market:buy:{self.city_id}:{eid}:{product}:{day}",
                        [(self.account(ent["player"]), -cost), ("system:market", cost)],
                    )
                    if posted is None:
                        continue
                self.add_goods(ent, product, qty, 50)
                bought.append((eid, qty))
                bought_total += qty
            from_players = bought_total if bought_total < supply else supply
            if from_players < 0:
                from_players = 0
            self._pay_sellers(day, product, sellers, from_players, supply, price)
            self.market_rows.append(
                {
                    "product": product,
                    "demand": demand,
                    "player_supply": supply,
                    "price": price,
                    "bought": bought_total,
                    "from_players": from_players,
                    "from_city": bought_total - from_players,
                }
            )

    def _pay_sellers(self, day: int, product: str, sellers: list[tuple[str, int]], sold: int, supply: int, price: int) -> None:
        if sold <= 0 or supply <= 0 or not sellers:
            return
        shares = [sold * have // supply for _, have in sellers]
        left = sold - sum(shares)
        order = sorted(range(len(sellers)), key=lambda index: sellers[index][0])
        cursor = 0
        while left > 0:
            shares[order[cursor % len(order)]] += 1
            left -= 1
            cursor += 1
        for (eid, have), qty in zip(sellers, shares):
            if qty <= 0:
                continue
            if qty > have:
                qty = have
            ent = self.enterprises[eid]
            self.take_goods(ent, product, qty)
            revenue = qty * price
            if revenue <= 0:
                continue
            posted = self.ledger.post(
                f"market:sell:{self.city_id}:{eid}:{product}:{day}",
                [(self.account(ent["player"]), revenue), ("system:market", -revenue)],
            )
            if posted is None:
                raise RuntimeError("выплата продавцу рынка не проведена")

    def _shelf_price(self, cell: dict) -> int:
        spec = cell["price_spec"]
        if spec == "reference":
            return int(self.catalog.product(cell["product"])["reference_price"])
        return _int(spec, "цена полки")

    def _cell_rating(self, cell: dict, ent: dict) -> int:
        product = self.catalog.product(cell["product"])
        price = self._shelf_price(cell)
        score = price_attractiveness(int(product["reference_price"]), price)
        quality = self.quality_of(ent, cell["product"]) if self.qty(ent, cell["product"]) else 50
        return rating(product["rating_weights"], BRAND_M1, quality, score)

    def _retail(self, day: int) -> None:
        if self.m2:
            self._retail_m2(day)
            return
        by_product: dict[str, list[dict]] = {}
        for cell in self.cells:
            ent = self.enterprises.get(cell["enterprise"])
            if ent is None or not self.operational(ent):
                continue
            by_product.setdefault(cell["product"], []).append(cell)
        pop_city = int(self.city["population_estimate"])
        pop = pop_city * _int(self.district["pop_permille"], "pop_permille") // 1000
        layer = _int(self.district["layer_share_permille"], "layer_share_permille")
        income = _int(self.district["income_index"], "income_index")
        traffic = _int(self.district.get("traffic", 0), "traffic")
        appeal = _int(self.district.get("appeal_permille", 1000), "appeal_permille")
        sharp = _int(self.district.get("competition_s", 1), "competition_s")
        if sharp < 1 or sharp > 4:
            raise RuntimeError("острота конкуренции вне 1..4")
        traffic_bonus = traffic * 10
        for product, cells in sorted(by_product.items()):
            info = self.catalog.product(product)
            if not info.get("consumer"):
                continue
            ratings = []
            prices = []
            weights = []
            for cell in cells:
                ent = self.enterprises[cell["enterprise"]]
                rank = self._cell_rating(cell, ent)
                price = self._shelf_price(cell)
                attractiveness = rank * (1000 + traffic_bonus) // 1000 * appeal // 1000
                weight = 1
                for _ in range(sharp):
                    weight *= attractiveness if attractiveness > 0 else 0
                if weight <= 0:
                    weight = 0
                ratings.append(rank)
                prices.append(price)
                weights.append(weight)
            if not cells:
                continue
            avg_price = sum(prices) // len(prices)
            avg_rating = sum(ratings) // len(ratings)
            demand = demand_units(
                pop,
                int(info["base_demand_per_capita"]),
                layer,
                income,
                avg_price,
                int(info["reference_price"]),
                int(info["elasticity"]),
                avg_rating,
                1000,
            )
            weight_sum = sum(weights)
            if weight_sum <= 0 or demand <= 0:
                continue
            shares = [demand * weight // weight_sum for weight in weights]
            left = demand - sum(shares)
            order = sorted(range(len(cells)), key=lambda index: (-weights[index], cells[index]["slot"], cells[index]["enterprise"]))
            cursor = 0
            while left > 0:
                shares[order[cursor % len(order)]] += 1
                left -= 1
                cursor += 1
            for cell, share in zip(cells, shares):
                ent = self.enterprises[cell["enterprise"]]
                have = self.qty(ent, cell["product"])
                sold = share if share < have else have
                if sold <= 0:
                    continue
                self.take_goods(ent, cell["product"], sold)
                gross = sold * self._shelf_price(cell)
                if gross <= 0:
                    continue
                posted = self.ledger.post(
                    f"sale:{ent['id']}:{cell['slot']}:{day}",
                    [(self.account(ent["player"]), gross), ("system:market", -gross)],
                )
                if posted is None:
                    raise RuntimeError("выручка розницы не проведена")
                player = self.players[ent["player"]]
                player["sales"] += sold
                player["revenue"] += gross
                tax = vat_on_gross(gross)
                player["tax"] += tax
                player["vat_month"] += tax
                ent["retail_gross"] += gross
                ent["retail_vat"] += tax
                reference = int(self.catalog.product(cell["product"])["reference_price"])
                ent["va"] += sold * (self._shelf_price(cell) - reference) - tax

    def _retail_m2(self, day: int) -> None:
        by_product: dict[str, list[dict]] = {}
        for cell in self.cells:
            ent = self.enterprises.get(cell["enterprise"])
            if ent is None or not self.operational(ent):
                continue
            info = self.catalog.product(cell["product"])
            if not info.get("consumer"):
                continue
            by_product.setdefault(cell["product"], []).append(cell)
        views = self._district_views(day)
        known = {str(row["id"]): row for row in views}
        book = self.district_book
        sharp = _int(self.scenario.get("competition_s", book["competition_s"]), "competition_s")
        months = _int(self.scenario.get("growth_months", 0), "growth_months")
        reports = []
        for product in sorted(by_product):
            info = self.catalog.product(product)
            stores = []
            for cell in by_product[product]:
                ent = self.enterprises[cell["enterprise"]]
                district_id = ent.get("district")
                if not isinstance(district_id, str) or district_id not in known:
                    raise RuntimeError("магазин M2 без района")
                district = known[district_id]
                allowed = self.catalog.building(ent["building_id"]).get("allowed_goods") or []
                if cell["product"] not in allowed:
                    raise RuntimeError(f"товар {cell['product']} не в специализации {ent['building_id']}")
                stores.append(
                    {
                        "enterprise": ent["id"],
                        "player": ent["player"],
                        "slot": cell["slot"],
                        "district": district_id,
                        "price": self._shelf_price(cell),
                        "rating": self._cell_rating(cell, ent),
                        "traffic": int(district["traffic"]),
                        "appeal_permille": int(district["appeal_permille"]),
                    }
                )
            report = market_demand(
                int(self.city["population_estimate"]),
                info,
                views,
                book["layers"],
                stores,
                sharp,
                int(book["ad_factor_permille"]),
                int(book["growth_bp"]),
                months,
            )
            self._sell_m2(day, report)
            reports.append(report)
        self.demand_report = reports

    def _sell_m2(self, day: int, report: dict) -> None:
        product = str(report["product"])
        reference = int(report["reference_price"])
        for district in report["districts"]:
            sold_total = 0
            revenue_total = 0
            for store in district["stores"]:
                ent = self.enterprises[store["enterprise"]]
                have = self.qty(ent, product)
                share = int(store["share"])
                qty = share if share < have else have
                gross = 0
                tax = 0
                if qty > 0:
                    self.take_goods(ent, product, qty)
                    gross = qty * int(store["price"])
                    if gross > 0:
                        posted = self.ledger.post(
                            f"sale:{ent['id']}:{store['slot']}:{day}",
                            [(self.account(ent["player"]), gross), ("system:market", -gross)],
                        )
                        if posted is None:
                            raise RuntimeError("выручка розницы не проведена")
                        player = self.players[ent["player"]]
                        player["sales"] += qty
                        player["revenue"] += gross
                        tax = vat_on_gross(gross)
                        player["tax"] += tax
                        player["vat_month"] += tax
                        ent["retail_gross"] += gross
                        ent["retail_vat"] += tax
                        ent["va"] += qty * (int(store["price"]) - reference) - tax
                store["sold"] = qty
                store["revenue"] = gross
                store["vat"] = tax
                sold_total += qty
                revenue_total += gross
            district["sold"] = sold_total
            district["revenue"] = revenue_total
            district["unmet"] = int(district["demand"]) - sold_total

    def _projects(self, day: int) -> None:
        # Сервер: POST списывает только фундамент и отказывает, если денег нет.
        # Здесь отказ не теряет намерение сценария: заказ остаётся в очереди
        # и пробуется в каждый следующий день. Уже стоящие здания в этот
        # момент не доплачивают следующие стадии — сначала все фундаменты дня.
        deferred: list[dict] = []
        for row in self.orders:
            if _int(row["day"], "день заказа") > day:
                deferred.append(row)
                continue
            if not self._try_place(row):
                deferred.append(row)
        self.orders = deferred
        for eid in self.enterprises:
            self._advance_build(self.enterprises[eid])

    def _blank_enterprise(self, row: dict, building: dict, recipe_id, build_cost: int) -> dict:
        build_days = int(building["build_days"])
        staffing_raw = row["staffing_bp"] if "staffing_bp" in row else self.scenario_staff
        return {
            "id": str(row["enterprise"]),
            "player": str(row["player"]),
            "building_id": building["id"],
            "recipe_id": None if recipe_id is None else str(recipe_id),
            "stage": 0,
            "days_in_stage": 0,
            "running": True,
            "staffing_bp": self._staffing_value(staffing_raw),
            "storage_capacity": int(building["storage_capacity"]),
            "jobs": int(building["jobs"]),
            "upkeep_month": int(building["upkeep_month"]),
            "build_cost": build_cost,
            "stage_days": stage_day_lengths(build_days),
            "stage_costs": stage_costs(build_cost),
            "stock": {},
            "load_bp": 0,
            "loads": [],
            "arrears_due": 0,
            "arrears_months": 0,
            "wear": 0,
            "sell_to_market": bool(row.get("sell_to_market", False)),
            "made": {},
            "stalled": False,
            "retail_gross": 0,
            "retail_vat": 0,
            "wage_charged": 0,
            "va": 0,
            "invested": 0,
        }

    def _pay_build_stage(self, ent: dict, stage: int, cost: int) -> bool:
        if cost <= 0:
            return True
        if self.money(ent["player"]) < cost:
            return False
        posted = self.ledger.post(
            f"enterprise:build:{ent['id']}:{stage}",
            [(self.account(ent["player"]), -cost), ("system:treasury", cost)],
        )
        if posted is None:
            return False
        ent["invested"] += cost
        return True

    def _try_place(self, row: dict) -> bool:
        """Вход в стадию 0. False — только нехватка фундамента, заказ повторно встанет в очередь."""
        eid = str(row["enterprise"])
        if eid in self.enterprises:
            return True
        building = self.catalog.building(str(row["building"]))
        recipe_id = row.get("recipe")
        if recipe_id is not None:
            recipe = self.catalog.recipe_for(str(recipe_id))
            if recipe["building"] != building["id"]:
                raise RuntimeError(f"рецепт {recipe_id} не для {building['id']}")
        if building.get("retail_cells"):
            for cell in self.cells:
                if cell["enterprise"] != eid:
                    continue
                allowed = building.get("allowed_goods") or []
                if cell["product"] not in allowed:
                    raise RuntimeError(f"товар {cell['product']} не в специализации {building['id']}")
                slot = cell["slot"]
                if slot < 1 or slot > int(building["retail_cells"]):
                    raise RuntimeError("ячейка вне сетки магазина")
        build_days = int(building["build_days"])
        if build_days <= 0:
            raise RuntimeError("build_days должен быть положительным")
        build_cost = self._build_cost_of(building)
        if build_cost < 1:
            raise RuntimeError("build_cost должен быть положительным")
        ent = self._blank_enterprise(row, building, recipe_id, build_cost)
        if not self._pay_build_stage(ent, 0, ent["stage_costs"][0]):
            return False
        self.enterprises[eid] = ent
        return True

    def _advance_build(self, ent: dict) -> None:
        """Как server.enterprises.core._advance_build: платёж при входе в следующую стадию."""
        guard = 0
        while ent["stage"] < STAGE_OPERATIONAL and guard < 8:
            guard += 1
            duration = ent["stage_days"][ent["stage"]]
            if duration:
                if ent["days_in_stage"] < duration:
                    ent["days_in_stage"] += 1
                if ent["days_in_stage"] < duration:
                    ent["stalled"] = False
                    return
            new_stage = ent["stage"] + 1
            if new_stage < STAGE_OPERATIONAL:
                cost = ent["stage_costs"][new_stage]
                if not self._pay_build_stage(ent, new_stage, cost):
                    ent["days_in_stage"] = duration
                    ent["stalled"] = True
                    return
            ent["stage"] = new_stage
            ent["days_in_stage"] = 0
            ent["stalled"] = False
        ent["stalled"] = ent["stage"] < STAGE_OPERATIONAL

    def _close_month(self, month: int) -> None:
        for eid in sorted(self.enterprises):
            ent = self.enterprises[eid]
            if ent["stage"] < STAGE_OPERATIONAL:
                ent["loads"] = []
                continue
            staff = ent["staffing_bp"]
            if staff > self.default_staff:
                staff = self.default_staff
            expense = monthly_expense(
                ent["jobs"],
                ent["upkeep_month"],
                self.salary,
                staff,
                int(self.city["indices_bp"]["salary"]),
            )
            due = ent["arrears_due"] + expense
            ent["wage_charged"] += expense
            if due > 0 and self.money(ent["player"]) >= due:
                posted = self.ledger.post(
                    f"enterprise:upkeep:{eid}:{month}",
                    [(self.account(ent["player"]), -due), ("system:upkeep", due)],
                )
                if posted is not None:
                    ent["arrears_due"] = 0
                    ent["arrears_months"] = 0
                    self.players[ent["player"]]["wages_paid"] += due
                else:
                    self._accrue(ent, expense)
            else:
                self._accrue(ent, expense)
            ent["wear"] = ent["wear"] + self.wear_step
            if ent["wear"] > 100:
                ent["wear"] = 100
            ent["loads"] = []
        for pid in sorted(self.players):
            player = self.players[pid]
            fresh = player["vat_month"]
            player["vat_month"] = 0
            due = player["tax_due"] + fresh
            if due <= 0:
                continue
            if self.money(pid) >= due:
                posted = self.ledger.post(
                    f"vat:{pid}:{month}",
                    [(self.account(pid), -due), ("system:treasury", due)],
                )
                if posted is not None:
                    player["tax_due"] = 0
                    player["tax_paid"] += due
                    continue
            player["tax_due"] = due

    def _accrue(self, ent: dict, expense: int) -> None:
        if expense <= 0 and ent["arrears_due"] <= 0:
            return
        if expense > 0:
            ent["arrears_due"] += expense
            ent["arrears_months"] += 1

    def snapshot(self, day: int) -> dict:
        players = {}
        for pid in sorted(self.players):
            row = self.players[pid]
            players[pid] = {
                "money": self.money(pid),
                "output": {key: row["output"][key] for key in sorted(row["output"])},
                "sales": row["sales"],
                "revenue": row["revenue"],
                "tax": row["tax"],
                "tax_due": row["tax_due"],
                "tax_paid": row["tax_paid"],
                "wages_paid": row["wages_paid"],
            }
        enterprises = {}
        for eid in sorted(self.enterprises):
            ent = self.enterprises[eid]
            stock = {}
            for product in sorted(ent["stock"]):
                qty = ent["stock"][product]["quantity"]
                if qty:
                    stock[product] = qty
            enterprises[eid] = {
                "player": ent["player"],
                "building": ent["building_id"],
                "stage": ent["stage"],
                "stalled": ent["stalled"] and ent["stage"] < STAGE_OPERATIONAL,
                "load_bp": ent["load_bp"],
                "arrears": ent["arrears_due"],
                "stock": stock,
            }
            if "district" in ent:
                enterprises[eid]["district"] = ent["district"]
        payload = {
            "day": day,
            "month_closed": day // 30 if day % 30 == 0 else 0,
            "ledger_sum": sum(self.ledger.balances.values()),
            "players": players,
            "enterprises": enterprises,
            "market": list(getattr(self, "market_rows", [])),
        }
        if self.m2:
            payload["demand"] = self.demand_report
        return payload


def _chain_cost(catalog: Catalog, buildings: list[str]) -> int:
    total = 0
    for building_id in buildings:
        total += int(catalog.building(building_id)["build_cost"])
    return total


def _verdict(scenario: dict, catalog: Catalog, days: list[dict]) -> dict | None:
    check = scenario.get("check_m1")
    if not check:
        return None
    window = _int(check.get("days", 10), "окно приёмки")
    names = [str(item) for item in check["enterprises"]]
    buildings = [str(item) for item in check["buildings"]]
    capital = 0
    for row in scenario["players"]:
        raw = row["capital"]
        if isinstance(raw, dict):
            capital += int(catalog.building(str(raw["equals_build_cost"]))["build_cost"])
        else:
            capital += _int(raw, "капитал")
    revenue = 0
    slice_days = days[:window]
    for row in slice_days:
        for player in row["players"].values():
            revenue += player["revenue"]
    last = slice_days[-1] if slice_days else None
    operational = False
    stages = {}
    if last is not None:
        operational = True
        for name in names:
            ent = last["enterprises"].get(name)
            stage = 0 if ent is None else ent["stage"]
            stages[name] = stage
            if stage < STAGE_OPERATIONAL:
                operational = False
    build_sum = _chain_cost(catalog, buildings)
    accepted = revenue > 0 and operational
    notes = []
    if revenue <= 0:
        notes.append(f"выручка за {window} суток равна {revenue}")
    else:
        notes.append(f"выручка за {window} суток равна {revenue}")
    if not operational:
        notes.append("не все предприятия цепочки введены")
    else:
        notes.append("все предприятия цепочки введены")
    if capital < build_sum:
        notes.append(f"капитал {capital} меньше суммы стройки {build_sum}")
    else:
        notes.append(f"капитал {capital} покрывает сумму стройки {build_sum}")
    return {
        "revenue_first_window": revenue,
        "window_days": window,
        "chain_operational": operational,
        "accepted": accepted,
        "starting_capital": capital,
        "build_cost_sum": build_sum,
        "stages": stages,
        "reason": "; ".join(notes),
    }


def simulate(scenario: dict, catalog: Catalog | None = None, days: int | None = None) -> dict:
    catalog = catalog or Catalog()
    count = _int(scenario["days"] if days is None else days, "сутки")
    if count < 1:
        raise RuntimeError("число суток меньше 1")
    engine = Engine(scenario, catalog, count)
    rows = []
    for day in range(1, count + 1):
        engine.tick(day)
        rows.append(engine.snapshot(day))
    totals = {}
    for pid in engine.players:
        output: dict[str, int] = {}
        revenue = 0
        sales = 0
        tax_paid = 0
        wages_paid = 0
        for row in rows:
            player = row["players"][pid]
            revenue += player["revenue"]
            sales += player["sales"]
            tax_paid += player["tax_paid"]
            wages_paid += player["wages_paid"]
            for product, qty in player["output"].items():
                output[product] = output.get(product, 0) + qty
        totals[pid] = {
            "money": engine.money(pid),
            "revenue": revenue,
            "sales": sales,
            "tax_paid": tax_paid,
            "wages_paid": wages_paid,
            "output": {key: output[key] for key in sorted(output)},
            "min_money": engine.ledger.min_player.get(engine.account(pid), engine.money(pid)),
        }
    return {
        "sim_version": SIM_VERSION,
        "scenario": scenario["id"],
        "days_run": count,
        "city": engine.city_id,
        "salary_worker": engine.salary,
        "salary_index_bp": int(engine.city["indices_bp"]["salary"]),
        "days": rows,
        "totals": totals,
        "verdict": _verdict(scenario, catalog, rows),
    }


def load_scenario(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def render_table(report: dict) -> str:
    lines = [
        f"{'день':>4}  {'игрок':<12}  {'деньги':>12}  {'выпуск':<22}  {'продажи':>8}  {'выручка':>10}  {'налог':>8}"
    ]
    for row in report["days"]:
        for pid, player in row["players"].items():
            if player["output"]:
                output = ",".join(f"{name}:{qty}" for name, qty in player["output"].items())
            else:
                output = "-"
            lines.append(
                f"{row['day']:4d}  {pid:<12}  {player['money']:12d}  {output:<22}  {player['sales']:8d}  {player['revenue']:10d}  {player['tax']:8d}"
            )
    lines.append("ИТОГ")
    for pid, total in report["totals"].items():
        if total["output"]:
            output = ",".join(f"{name}:{qty}" for name, qty in total["output"].items())
        else:
            output = "-"
        lines.append(
            f"{pid}: деньги={total['money']} выпуск={output} продажи={total['sales']} выручка={total['revenue']} налог_уплачен={total['tax_paid']} зарплата_и_содержание={total['wages_paid']}"
        )
    verdict = report.get("verdict")
    if verdict is not None:
        flag = "да" if verdict["accepted"] else "нет"
        lines.append(
            f"ПРИЁМКА M1: {flag}. выручка_{verdict['window_days']}={verdict['revenue_first_window']}; цепочка_введена={verdict['chain_operational']}; {verdict['reason']}"
        )
    return "\n".join(lines) + "\n"
