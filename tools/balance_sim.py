#!/usr/bin/env python3
"""Симулятор баланса и стресс-тест экономики «Башкирия: Мёд и Нефть».

Гоняет серверную логику (production.advance / step_month, NPC, стройка, кредиты)
на временной SQLite без HTTP. Время подменяется, реальных ожиданий нет.
Игровой код не меняет: только читает его. Соединения — через sqlite_util
(game_server.connect). PostgreSQL этот модуль не открывает.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import os
import sys
import tempfile
import time
import uuid
from unittest import mock

_SERVER = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server"))
if _SERVER not in sys.path:
    sys.path.insert(0, _SERVER)

import clock  # noqa: E402
import economy  # noqa: E402
import game_server  # noqa: E402
import npc  # noqa: E402
import production  # noqa: E402
import roads  # noqa: E402

T0 = 1_800_000_000
CYCLE = ("farm", "mine", "factory", "warehouse")
STRATEGIES = ("rotate", "hoard", "loan", "idle")
_PREFIX = {"rotate": "rot", "hoard": "hor", "loan": "lon", "idle": "idl"}

# Целые метрики месяца. Время шага сюда не входит: оно не детерминировано.
METRIC_FIELDS = (
    "month",
    "honey_price", "oil_price", "goods_price",
    "honey_supply", "oil_supply", "goods_supply",
    "honey_demand", "oil_demand", "goods_demand",
    "population", "next_population", "labor_force", "jobs", "wage", "unemployment_ppm",
    "buildings", "npc_buildings", "player_buildings", "city_buildings",
    "player_money", "npc_money", "treasury", "city_budget",
    "market", "bank", "residents", "construction", "upkeep",
    "wallet_sum", "ledger_sum", "unbalanced_tx", "wallet_mismatch",
    "negative_players", "negative_stock",
    "bankruptcies", "bankrupt_this_month", "npc_broke",
    "tax_paid", "tax_vat", "tax_profit", "tax_property",
    "tx_count",
)
TIMING_FIELDS = ("step_ms", "tick_ms")
CSV_FIELDS = METRIC_FIELDS + TIMING_FIELDS

# Население «раздулось», если выросло сильнее чем в 8 раз от базы (200 → 1600).
DEFAULT_POP_CAP = economy.BASE_POPULATION * 8
DEFAULT_PIN_MONTHS = 6
DEFAULT_STEP_BUDGET_MS = 500.0
WHIPSAW_MIN = 4
MASS_DEFAULT_MIN = 3


def price_limits(product):
    ref = economy.MARKET[product]["reference_price"]
    return int(round(ref * economy.MIN_PRICE_K)), int(round(ref * economy.MAX_PRICE_K))


def _clear_block(x, y, w=3, h=3):
    for dx in range(w):
        for dy in range(h):
            if roads.is_base_road(x + dx, y + dy) or roads.is_water(x + dx, y + dy):
                return False
    return True


def build_sites(limit=800):
    """Площадки 3×3 рядом с дорожной сеткой: детерминированный порядок, без воды и дорог."""
    sites = []
    ys = range(-80, 220, 4)
    xs = []
    for band in range(0, 30):
        xs.append(1 + band * 4)
        xs.append(-4 - band * 4)
    for x in xs:
        for y in ys:
            if _clear_block(x, y):
                sites.append((x, y))
                if len(sites) >= limit:
                    return sites
    if not sites:
        raise RuntimeError("не нашлось ни одной площадки под строительство")
    return sites


def economic_tuple(row):
    return tuple(int(row[key]) for key in METRIC_FIELDS)


def canonical_digest(rows):
    blob = "\n".join(",".join(str(v) for v in economic_tuple(row)) for row in rows).encode()
    return hashlib.sha256(blob).hexdigest()


class Bot:
    def __init__(self, name, strategy, index):
        self.name = name
        self.strategy = strategy
        self.index = index
        self.built = 0

    def act(self, world, month):
        if self.strategy == "idle":
            if month == 0:
                game_server.wallet(self.name)
            return
        if self.strategy == "hoard":
            if self.built < 1 and world.try_build(self.name, "farm", month):
                self.built += 1
            elif month == 0 and self.built < 1:
                game_server.wallet(self.name)
            return
        if self.strategy == "loan":
            _status, data = game_server.wallet(self.name)
            loan = data["loan"]
            if loan["available"] >= economy.LOAN_MIN and not loan["in_default"]:
                game_server.loan(self.name, {
                    "action": "take",
                    "amount": int(loan["available"]),
                    "request_id": world.request_id(self.name, month, "loan"),
                })
            if self.built < world.build_cap:
                balance = game_server.wallet(self.name)[1]["balance"]
                for kind in ("factory", "mine", "farm", "warehouse"):
                    if balance < economy.BUILD_COST[kind]:
                        continue
                    if world.try_build(self.name, kind, month):
                        self.built += 1
                        break
            return
        if self.strategy == "rotate":
            if self.built >= world.build_cap:
                return
            kind = CYCLE[(month + self.index) % len(CYCLE)]
            if world.try_build(self.name, kind, month):
                self.built += 1
            return
        raise ValueError("неизвестная стратегия: %s" % self.strategy)


class World:
    """Один прогон на своей SQLite. Время — подмена game_server.time.time."""

    def __init__(self, db_path, month_seconds, t0, seed, npc_on, strategies, build_cap, months):
        self.db_path = db_path
        self.month_seconds = max(int(month_seconds), clock.MIN_MONTH_SECONDS)
        self.t0 = int(t0)
        self.now = int(t0)
        self.seed = int(seed)
        self.npc_on = bool(npc_on)
        self.build_cap = int(build_cap)
        self.months = int(months)
        self.sites = build_sites()
        self.attempt = 0
        self.builds_ok = 0
        self.builds_fail = 0
        self.bots = []
        for index, strategy in enumerate(strategies):
            if strategy not in STRATEGIES:
                raise ValueError("неизвестная стратегия: %s" % strategy)
            self.bots.append(Bot("%s%02d" % (_PREFIX[strategy], index), strategy, index))
        self._patch = None
        self._old_db = None
        self._old_env = None

    def __enter__(self):
        self._old_db = game_server.DB
        self._old_env = os.environ.get("LUNEX_MONTH_SECONDS")
        self._patch = mock.patch.object(game_server.time, "time", side_effect=lambda: self.now)
        self._patch.start()
        try:
            game_server.DB = self.db_path
            os.environ["LUNEX_MONTH_SECONDS"] = str(self.month_seconds)
        except BaseException:
            self._patch.stop()
            raise
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._patch is not None:
            self._patch.stop()
        if self._old_db is not None:
            game_server.DB = self._old_db
        if self._old_env is None:
            os.environ.pop("LUNEX_MONTH_SECONDS", None)
        else:
            os.environ["LUNEX_MONTH_SECONDS"] = self._old_env
        return False

    def request_id(self, owner, month, salt):
        token = "sim/%s/%s/%s/%s/%s" % (self.seed, owner, month, salt, self.attempt)
        return str(uuid.uuid5(uuid.NAMESPACE_URL, token))

    def next_site(self):
        site = self.sites[(self.seed + self.attempt) % len(self.sites)]
        self.attempt += 1
        return site

    def try_build(self, owner, kind, month):
        """До 12 детерминированных попыток. 402 — денег нет, дальше не ищем."""
        for _ in range(12):
            x, y = self.next_site()
            status, _res = game_server.build(owner, {
                "kind": kind, "x": int(x), "y": int(y),
                "request_id": self.request_id(owner, month, "build"),
            })
            if status in (200, 201):
                self.builds_ok += 1
                return True
            self.builds_fail += 1
            if status == 402 or status == 400:
                return False
        return False

    def _advance(self):
        started = time.perf_counter()
        with game_server.LOCK, game_server.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            clk = clock.state(db, "?", self.now)
            processed = production.advance(db, "?", clk, self.now)
            done = db.execute("SELECT processed_through FROM world_state WHERE id=1").fetchone()
            db.commit()
        elapsed = (time.perf_counter() - started) * 1000.0
        return elapsed, clk, int(processed), int(done[0]) if done else None

    def _npc_tick(self):
        """Прямой вызов npc.tick: в отличие от game_server.npc_tick ошибка не глотается."""
        started = time.perf_counter()
        built = npc.tick(
            game_server.connect, "?", game_server.clock_state,
            lambda: game_server.market_state()[1],
            lambda owner: game_server.wallet(owner)[1],
            game_server.build,
            lambda: game_server.city_state()[1],
        )
        return (time.perf_counter() - started) * 1000.0, built

    def seed_buildings(self, count, per_company=10):
        """Прямая вставка зданий для замера шага (без поиска дороги). Схема уже создана."""
        kinds = CYCLE
        with game_server.LOCK, game_server.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for i in range(count):
                owner = "co%03d" % (i // per_company)
                kind = kinds[i % len(kinds)]
                db.execute(
                    "INSERT INTO buildings(id,owner,kind,x,y,created) VALUES(?,?,?,?,?,?)",
                    ("b%05d" % i, owner, kind, (i % 50) * 4 + 2, (i // 50) * 4 + 2, self.now),
                )
                db.execute(
                    "INSERT INTO building_ops(object_id,owner,kind,start_month,start_permille) VALUES(?,?,?,?,?)",
                    ("b%05d" % i, owner, kind, 0, 0),
                )
                economy.ensure_wallet(db, "?", owner, self.now)
            db.commit()

    def snapshot(self, month, step_ms, tick_ms):
        with game_server.connect() as db:
            prices = {p: None for p in ("honey", "oil", "goods")}
            supply = dict(prices)
            demand = dict(prices)
            for product, price, sup, dem in db.execute(
                    "SELECT product,price,supply,demand FROM market_prices WHERE month_index=?", (month,)):
                prices[product] = int(price)
                supply[product] = int(sup)
                demand[product] = int(dem)
            pop = db.execute(
                "SELECT population,labor_force,jobs,wage,staffing_permille,next_population "
                "FROM population WHERE month_index=?", (month,)).fetchone()
            if pop is None:
                population = labor = jobs = wage = next_pop = unemployment_ppm = None
            else:
                population, labor, jobs, wage, staffing_pm, next_pop = (int(v) for v in pop)
                employed = jobs * staffing_pm // 1000
                unemployment_ppm = 0 if labor <= 0 else max(0, (labor - employed) * 1000 // labor)
            counts = dict(db.execute("SELECT owner,COUNT(*) FROM buildings GROUP BY owner").fetchall())
            npc_buildings = sum(n for owner, n in counts.items() if str(owner).startswith("npc:"))
            city_buildings = int(counts.get(economy.CITY, 0))
            buildings = sum(counts.values())
            wallets = dict(db.execute("SELECT account,balance FROM wallets").fetchall())
            player_money = npc_money = 0
            negative = []
            for account, balance in wallets.items():
                balance = int(balance)
                if account.startswith("player:npc:"):
                    npc_money += balance
                elif account.startswith("player:") and account != economy.player_account(economy.CITY):
                    player_money += balance
                if account.startswith("player:") and balance < 0:
                    negative.append(account)
            ledger_sum = int(db.execute("SELECT COALESCE(SUM(amount),0) FROM ledger_entries").fetchone()[0])
            unbalanced = int(db.execute(
                "SELECT COUNT(*) FROM (SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0)"
            ).fetchone()[0])
            mismatch = int(db.execute(
                "SELECT COUNT(*) FROM ("
                " SELECT w.account FROM wallets w LEFT JOIN ("
                "   SELECT account, SUM(amount) AS total FROM ledger_entries GROUP BY account"
                " ) e ON e.account=w.account WHERE w.balance<>COALESCE(e.total,0)"
                " UNION"
                " SELECT e.account FROM ("
                "   SELECT account, SUM(amount) AS total FROM ledger_entries GROUP BY account"
                " ) e LEFT JOIN wallets w ON w.account=e.account WHERE w.account IS NULL)"
            ).fetchone()[0])
            negative_stock = int(db.execute(
                "SELECT COUNT(*) FROM inventory WHERE qty<0").fetchone()[0])
            bankruptcies = int(db.execute(
                "SELECT COALESCE(SUM(bankruptcies),0) FROM company_status").fetchone()[0])
            bankrupt_this = int(db.execute(
                "SELECT COUNT(*) FROM company_status WHERE last_bankruptcy_month=?", (month,)).fetchone()[0])
            npc_broke = 0
            for persona in npc.PERSONAS:
                have = int(db.execute(
                    "SELECT COUNT(*) FROM buildings WHERE owner=?", (persona["owner"],)).fetchone()[0])
                row = db.execute(
                    "SELECT bankruptcies FROM company_status WHERE owner=?", (persona["owner"],)).fetchone()
                if have == 0 and row is not None and int(row[0]) > 0:
                    npc_broke += 1
            tax = db.execute(
                "SELECT COALESCE(SUM(paid),0),COALESCE(SUM(vat),0),COALESCE(SUM(profit_tax),0),"
                "COALESCE(SUM(property_tax),0) FROM company_taxes WHERE month_index=?", (month,)).fetchone()
            tx_count = int(db.execute("SELECT COUNT(*) FROM ledger_tx").fetchone()[0])
            done = db.execute("SELECT processed_through FROM world_state WHERE id=1").fetchone()
        row = {
            "month": month,
            "honey_price": prices["honey"], "oil_price": prices["oil"], "goods_price": prices["goods"],
            "honey_supply": supply["honey"], "oil_supply": supply["oil"], "goods_supply": supply["goods"],
            "honey_demand": demand["honey"], "oil_demand": demand["oil"], "goods_demand": demand["goods"],
            "population": population, "next_population": int(next_pop) if pop else None,
            "labor_force": labor, "jobs": jobs, "wage": wage, "unemployment_ppm": unemployment_ppm,
            "buildings": buildings, "npc_buildings": npc_buildings,
            "player_buildings": buildings - npc_buildings - city_buildings, "city_buildings": city_buildings,
            "player_money": player_money, "npc_money": npc_money,
            "treasury": int(wallets.get(economy.TREASURY, 0)),
            "city_budget": int(wallets.get(economy.player_account(economy.CITY), 0)),
            "market": int(wallets.get(economy.MARKET_ACCOUNT, 0)),
            "bank": int(wallets.get(economy.BANK, 0)),
            "residents": int(wallets.get(economy.RESIDENTS, 0)),
            "construction": int(wallets.get(economy.CONSTRUCTION, 0)),
            "upkeep": int(wallets.get(economy.UPKEEP, 0)),
            "wallet_sum": int(sum(int(v) for v in wallets.values())),
            "ledger_sum": ledger_sum, "unbalanced_tx": unbalanced, "wallet_mismatch": mismatch,
            "negative_players": len(negative), "negative_stock": negative_stock,
            "bankruptcies": bankruptcies, "bankrupt_this_month": bankrupt_this, "npc_broke": npc_broke,
            "tax_paid": int(tax[0]), "tax_vat": int(tax[1]), "tax_profit": int(tax[2]), "tax_property": int(tax[3]),
            "tx_count": tx_count,
            "step_ms": round(step_ms, 3), "tick_ms": round(tick_ms, 3),
            "processed_through": int(done[0]) if done else None,
            "negative_accounts": negative,
        }
        return row

    def actors(self):
        owners = [bot.name for bot in self.bots] + [p["owner"] for p in npc.PERSONAS] + [economy.CITY]
        out = []
        with game_server.connect() as db:
            for owner in owners:
                bal = db.execute("SELECT balance FROM wallets WHERE account=?", (economy.player_account(owner),)).fetchone()
                holdings = dict(db.execute("SELECT kind,COUNT(*) FROM buildings WHERE owner=? GROUP BY kind", (owner,)).fetchall())
                loan = db.execute("SELECT balance FROM loans WHERE owner=?", (owner,)).fetchone()
                status = db.execute(
                    "SELECT bankruptcies,missed,written_off FROM company_status WHERE owner=?", (owner,)).fetchone()
                out.append({
                    "owner": owner,
                    "balance": int(bal[0]) if bal else None,
                    "buildings": int(sum(holdings.values())),
                    "holdings": {k: int(v) for k, v in holdings.items()},
                    "loan": int(loan[0]) if loan else 0,
                    "bankruptcies": int(status[0]) if status else 0,
                    "missed": int(status[1]) if status else 0,
                    "written_off": int(status[2]) if status else 0,
                })
        return out

    def run(self):
        started = time.perf_counter()
        self._advance()
        if self.npc_on:
            self._npc_tick()
        for bot in self.bots:
            bot.act(self, 0)
        rows = []
        for index in range(self.months):
            self.now += self.month_seconds
            step_ms, _clk, _processed, _done = self._advance()
            tick_ms = 0.0
            if self.npc_on:
                tick_ms, _built = self._npc_tick()
            for bot in self.bots:
                bot.act(self, index + 1)
            rows.append(self.snapshot(index, step_ms, tick_ms))
        elapsed = time.perf_counter() - started
        return {
            "rows": rows,
            "actors": self.actors(),
            "builds_ok": self.builds_ok,
            "builds_fail": self.builds_fail,
            "elapsed_s": round(elapsed, 3),
            "bots": [{"name": b.name, "strategy": b.strategy, "built": b.built} for b in self.bots],
        }


def row_invariants(row):
    """Жёсткие инварианты одного месяца. Красные флаги баланса сюда не входят."""
    bad = []
    month = row.get("month")
    missing = [key for key in ("honey_price", "oil_price", "goods_price", "population", "ledger_sum") if row.get(key) is None]
    if missing:
        bad.append("месяц %s: нет данных (%s)" % (month, ", ".join(missing)))
        return bad
    if row["ledger_sum"] != 0 or row["wallet_sum"] != 0 or row["unbalanced_tx"] or row["wallet_mismatch"]:
        bad.append(
            "месяц %s: деньги из воздуха (ledger=%s, кошельки=%s, кривых проводок=%s, расхождений=%s)"
            % (month, row["ledger_sum"], row["wallet_sum"], row["unbalanced_tx"], row["wallet_mismatch"]))
    if row["negative_players"]:
        bad.append("месяц %s: отрицательные деньги игрока %s" % (month, ",".join(row.get("negative_accounts") or [])))
    if row["negative_stock"]:
        bad.append("месяц %s: отрицательный запас (%s позиций)" % (month, row["negative_stock"]))
    if row["city_budget"] < 0:
        bad.append("месяц %s: бюджет города %s < 0" % (month, row["city_budget"]))
    if row.get("processed_through") not in (None, month):
        bad.append("месяц %s: processed_through=%s" % (month, row.get("processed_through")))
    return bad


def _longest(rows, pred):
    best = (0, None, None)
    cur = 0
    start = None
    for row in rows:
        if pred(row):
            if cur == 0:
                start = row["month"]
            cur += 1
            if cur > best[0]:
                best = (cur, start, row["month"])
        else:
            cur = 0
    return best


def _whipsaw_hits(rows, key, product):
    """Месяцы, где цена на потолке, а соседний месяц ниже порога удержания склада."""
    _floor, ceil = price_limits(product)
    hold = economy.MARKET[product]["reference_price"] * economy.HOLD_BELOW
    hits = []
    for index, row in enumerate(rows):
        if row.get(key) != ceil:
            continue
        neighbors = []
        if index:
            neighbors.append(rows[index - 1].get(key))
        if index + 1 < len(rows):
            neighbors.append(rows[index + 1].get(key))
        if any(value is not None and value < hold for value in neighbors):
            hits.append(row)
    return hits


def analyze(rows, pin_months=DEFAULT_PIN_MONTHS, step_budget_ms=DEFAULT_STEP_BUDGET_MS,
            pop_cap=DEFAULT_POP_CAP, npc_count=None):
    """Красные флаги по ряду месяцев. Инварианты журнала сюда не дублируются."""
    if npc_count is None:
        npc_count = len(npc.PERSONAS)
    flags = []
    if not rows:
        return flags
    names = {"honey_price": "мёд", "oil_price": "нефть", "goods_price": "товары"}
    products = (("honey_price", "honey"), ("oil_price", "oil"), ("goods_price", "goods"))
    for key, product in products:
        floor, ceil = price_limits(product)
        for bound, label in ((floor, "нижней"), (ceil, "верхней")):
            length, start, end = _longest(rows, lambda row, key=key, bound=bound: row.get(key) == bound)
            if length >= pin_months:
                flags.append({
                    "code": "price_pin", "month": end, "metric": key, "value": bound,
                    "detail": "%s на %s границе %s ₽ %s мес. подряд (месяцы %s–%s)"
                              % (names[key], label, bound, length, start, end),
                })
    for key, product in products:
        hits = _whipsaw_hits(rows, key, product)
        if len(hits) >= WHIPSAW_MIN:
            supply_key = key.replace("_price", "_supply")
            supplies = [hit.get(supply_key) for hit in hits]
            zero = sum(1 for value in supplies if value == 0)
            flags.append({
                "code": "price_whipsaw", "month": hits[0]["month"], "metric": key, "value": hits[0][key],
                "detail": "%s %s %s бьётся в потолок %s ₽ и рядом падает ниже порога склада %.0f ₽ "
                          "(месяцы %s%s). Это не «залипание»: месяцы чередуются."
                          % (names[key], len(hits), _times(len(hits)), hits[0][key],
                             economy.MARKET[product]["reference_price"] * economy.HOLD_BELOW,
                             ", ".join(str(hit["month"]) for hit in hits[:12]),
                             "" if len(hits) <= 12 else ", …",
                             ) + (" В %s из этих месяцев предложение на рынке 0." % zero if zero else ""),
            })
    burst = [row for row in rows if (row.get("bankrupt_this_month") or 0) >= MASS_DEFAULT_MIN]
    if burst:
        row = burst[0]
        flags.append({
            "code": "mass_default", "month": row["month"], "metric": "bankrupt_this_month",
            "value": row["bankrupt_this_month"],
            "detail": "за один месяц обанкротились %s компании (месяц %s); всего таких месяцев %s"
                      % (row["bankrupt_this_month"], row["month"], len(burst)),
        })
    length, start, end = _longest(rows, lambda row: (row.get("next_population") or 0) <= 0 or (row.get("population") or 0) <= 0)
    if length:
        flags.append({
            "code": "population_zero", "month": end, "metric": "population", "value": 0,
            "detail": "население 0 (месяцы %s–%s)" % (start, end),
        })
    length, start, end = _longest(
        rows, lambda row: row.get("population") is not None and row["population"] <= economy.MIN_POPULATION)
    if length >= pin_months:
        flags.append({
            "code": "population_floor", "month": end, "metric": "population", "value": economy.MIN_POPULATION,
            "detail": "население на минимуме %s %s мес. подряд (месяцы %s–%s); ниже пол код не пускает"
                      % (economy.MIN_POPULATION, length, start, end),
        })
    exploded = [row for row in rows if (row.get("next_population") or 0) > pop_cap]
    if exploded:
        row = exploded[0]
        flags.append({
            "code": "population_explode", "month": row["month"], "metric": "next_population",
            "value": row["next_population"],
            "detail": "население %s больше порога %s (месяц %s)" % (row["next_population"], pop_cap, row["month"]),
        })
    wiped = [row for row in rows if row.get("npc_broke", 0) >= npc_count and npc_count > 0]
    if wiped:
        row = wiped[0]
        flags.append({
            "code": "npc_wiped", "month": row["month"], "metric": "npc_broke", "value": row["npc_broke"],
            "detail": "все NPC-конкуренты без зданий после банкротства (месяц %s)" % row["month"],
        })
    slow = [row for row in rows if row.get("step_ms", 0) > step_budget_ms]
    if slow:
        worst = max(slow, key=lambda row: row["step_ms"])
        flags.append({
            "code": "slow_step", "month": worst["month"], "metric": "step_ms", "value": worst["step_ms"],
            "detail": "шаг месяца %s мс > бюджета %s мс (месяц %s, таких месяцев %s)"
                      % (worst["step_ms"], step_budget_ms, worst["month"], len(slow)),
        })
    last = rows[-1]
    if last.get("market", 0) < 0 and last.get("residents", 0) > 0:
        flags.append({
            "code": "open_loop", "month": last["month"], "metric": "market", "value": last["market"],
            "detail": "денежный круг не замкнут: рынок %s ₽ (источник оплаты продукции), "
                      "жители накопили зарплат %s ₽ и не тратят; сумма кошельков при этом %s"
                      % (last["market"], last["residents"], last["wallet_sum"]),
        })
    return flags


def run_scenario(months=24, seed=20261114, strategies=(), npc_on=True, month_seconds=86400,
                 build_cap=16, t0=T0, pin_months=DEFAULT_PIN_MONTHS, step_budget_ms=DEFAULT_STEP_BUDGET_MS,
                 pop_cap=DEFAULT_POP_CAP, db_path=None):
    """Прогон. db_path=None — временный файл, который будет удалён."""
    if os.environ.get("LUNEX_DB_ENGINE") == "postgres" and os.environ.get("LUNEX_PG_DB") != "lunex_ci":
        raise RuntimeError("PostgreSQL разрешён только для одноразовой базы lunex_ci; симулятор её сам не открывает")
    own_tmp = db_path is None
    tmp = tempfile.TemporaryDirectory() if own_tmp else None
    path = db_path or os.path.join(tmp.name, "world.sqlite3")
    config = {
        "months": int(months), "seed": int(seed), "strategies": tuple(strategies), "npc": bool(npc_on),
        "month_seconds": max(int(month_seconds), clock.MIN_MONTH_SECONDS), "build_cap": int(build_cap), "t0": int(t0),
        "pin_months": int(pin_months), "step_budget_ms": float(step_budget_ms), "pop_cap": int(pop_cap),
    }
    try:
        with World(path, config["month_seconds"], t0, seed, npc_on, tuple(strategies), build_cap, months) as world:
            payload = world.run()
    finally:
        if tmp is not None:
            tmp.cleanup()
    invariants = []
    for row in payload["rows"]:
        invariants.extend(row_invariants(row))
    flags = analyze(payload["rows"], pin_months=pin_months, step_budget_ms=step_budget_ms, pop_cap=pop_cap)
    payload.update(config=config, invariants=invariants, flags=flags, digest=canonical_digest(payload["rows"]))
    return payload


def perf_probe(counts=(50, 200, 1000), month_seconds=86400, t0=T0, per_company=10):
    """Сколько миллисекунд занимает один step_month при N уже построенных зданиях."""
    results = []
    for count in counts:
        tmp = tempfile.TemporaryDirectory()
        try:
            path = os.path.join(tmp.name, "world.sqlite3")
            with World(path, month_seconds, t0, seed=1, npc_on=False, strategies=(), build_cap=0, months=1) as world:
                world._advance()
                world.seed_buildings(int(count), per_company=per_company)
                world.now += world.month_seconds
                step_ms, _clk, processed, _done = world._advance()
                row = world.snapshot(0, step_ms, 0.0)
            results.append({
                "buildings": int(count),
                "companies": (int(count) + per_company - 1) // per_company,
                "step_ms": row["step_ms"],
                "processed": processed,
                "invariants": row_invariants(row),
                "honey_price": row["honey_price"], "oil_price": row["oil_price"], "goods_price": row["goods_price"],
                "population": row["population"], "jobs": row["jobs"], "tax_paid": row["tax_paid"],
                "wallet_sum": row["wallet_sum"],
            })
        finally:
            tmp.cleanup()
    return results


def write_csv(rows, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in CSV_FIELDS})


def _times(count):
    rest = abs(int(count)) % 100
    if 10 < rest < 20 or rest % 10 in (0, 1, 5, 6, 7, 8, 9):
        return "раз"
    return "раза"


def _fmt(value):
    if isinstance(value, float):
        return ("%.1f" % value).rstrip("0").rstrip(".")
    return str(value)


def render_report(runs, perf, compares):
    """Краткий отчёт по уже посчитанным прогонам. Числа не выдумываются."""
    lines = []
    lines.append("# Отчёт симулятора баланса")
    lines.append("")
    lines.append("Инструмент: `tools/balance_sim.py`. Игровые константы и серверный код не менялись.")
    lines.append("Мир считается на временной SQLite вызовами `production.advance` (внутри — `step_month`);")
    lines.append("часы подменены, реальная пауза не используется. NPC ходят через `npc.tick` (ошибка не глотается,")
    lines.append("в отличие от `game_server.npc_tick`). Сумма всех проводок и сумма всех кошельков должны быть 0:")
    lines.append("стартовый капитал, кредиты и оплата рынком — двойная запись, а не дырка в журнале.")
    lines.append("Цена, налоги, население и проводки месяца — это закрытый месяц. Число зданий и деньги")
    lines.append("сняты сразу после решений NPC и ботов на границе следующего месяца (так же сервер")
    lines.append("вызывает npc_tick перед действием игрока), поэтому новое здание ещё не входило в выпуск.")
    lines.append("")
    lines.append("Воспроизведение одного прогона:")
    lines.append("")
    lines.append("```bash")
    lines.append("cd tools && python balance_sim.py --months 72 --seed 20261114 --csv /tmp/npc72.csv")
    lines.append("cd tools && python -m unittest discover -p 'test_*.py' -v")
    lines.append("```")
    lines.append("")
    lines.append("Пороги красных флагов: цена на границе %s мес. подряд; качели потолок/ниже склада — от %s раз;"
                 % (DEFAULT_PIN_MONTHS, WHIPSAW_MIN))
    lines.append("население > %s; шаг месяца > %s мс; все %s NPC без зданий после банкротства;"
                 % (DEFAULT_POP_CAP, _fmt(DEFAULT_STEP_BUDGET_MS), len(npc.PERSONAS)))
    lines.append("бюджет города < 0; %s и больше банкротств за один месяц." % MASS_DEFAULT_MIN)
    lines.append("Границы цены: мёд %s–%s, нефть %s–%s, товары %s–%s."
                 % (price_limits("honey") + price_limits("oil") + price_limits("goods")))
    lines.append("")
    lines.append("## Сценарии")
    lines.append("")
    lines.append("| Прогон | Месяцев | seed | Длина месяца | NPC | Стратегии ботов | Инварианты | Красные флаги | Шаг, мс (макс) |")
    lines.append("|---|---:|---:|---:|---|---|---:|---:|---:|")
    for name, run in runs:
        cfg = run["config"]
        strategies = ", ".join(cfg["strategies"]) if cfg["strategies"] else "— только NPC" if cfg["npc"] else "—"
        worst = max((row["step_ms"] for row in run["rows"]), default=0)
        lines.append("| %s | %s | %s | %s с | %s | %s | %s | %s | %s |" % (
            name, cfg["months"], cfg["seed"], cfg["month_seconds"], "да" if cfg["npc"] else "нет",
            strategies, len(run["invariants"]), len(run["flags"]), _fmt(worst)))
    lines.append("")
    for name, run in runs:
        lines.append("## %s" % name)
        lines.append("")
        cfg = run["config"]
        lines.append("Воспроизведение: `python balance_sim.py --months %s --seed %s --month-seconds %s%s%s --build-cap %s`"
                     % (cfg["months"], cfg["seed"], cfg["month_seconds"],
                        "" if cfg["npc"] else " --no-npc",
                        (" --strategies " + ",".join(cfg["strategies"])) if cfg["strategies"] else "",
                        cfg["build_cap"]))
        lines.append("")
        lines.append("Построено ботами успешно %s, неудачных попыток %s, время прогона %s с, отпечаток ряда `%s`."
                     % (run["builds_ok"], run["builds_fail"], run["elapsed_s"], run["digest"][:16]))
        lines.append("")
        last = run["rows"][-1]
        first = run["rows"][0]
        lines.append("| | Месяц 0 | Последний (%s) |" % last["month"])
        lines.append("|---|---:|---:|")
        for label, key in (
            ("Мёд, ₽", "honey_price"), ("Нефть, ₽", "oil_price"), ("Товары, ₽", "goods_price"),
            ("Население (след.)", "next_population"), ("Безработица, ‰", "unemployment_ppm"),
            ("Здания", "buildings"), ("из них NPC", "npc_buildings"), ("игроков", "player_buildings"),
            ("города", "city_buildings"),
            ("Деньги игроков", "player_money"), ("Деньги NPC", "npc_money"),
            ("Казна `system:treasury`", "treasury"), ("Бюджет города", "city_budget"),
            ("Рынок `system:market`", "market"), ("Жители `system:residents`", "residents"),
            ("Банк `system:bank`", "bank"), ("Налоги за месяц", "tax_paid"),
            ("Банкротства (накоплено)", "bankruptcies"), ("Сумма кошельков", "wallet_sum"),
            ("Сумма проводок", "ledger_sum"), ("Проводок всего", "tx_count"),
        ):
            lines.append("| %s | %s | %s |" % (label, _fmt(first[key]), _fmt(last[key])))
        lines.append("")
        if run["actors"]:
            lines.append("| Участник | Баланс | Здания | Кредит | Банкротства | Списано |")
            lines.append("|---|---:|---:|---:|---:|---:|")
            for actor in run["actors"]:
                if actor["balance"] is None and actor["buildings"] == 0 and actor["bankruptcies"] == 0:
                    continue
                lines.append("| %s | %s | %s | %s | %s | %s |" % (
                    actor["owner"], _fmt(actor["balance"]), actor["buildings"], actor["loan"],
                    actor["bankruptcies"], actor["written_off"]))
            lines.append("")
        if run["invariants"]:
            lines.append("**Инварианты нарушены:**")
            lines.append("")
            for item in run["invariants"]:
                lines.append("- %s" % item)
            lines.append("")
        if run["flags"]:
            lines.append("**Красные флаги:**")
            lines.append("")
            for flag in run["flags"]:
                lines.append("- `%s` месяц %s, %s=%s — %s" % (
                    flag["code"], flag["month"], flag["metric"], _fmt(flag["value"]), flag["detail"]))
            lines.append("")
        else:
            lines.append("Красных флагов нет.")
            lines.append("")
    if compares:
        lines.append("## Длина месяца")
        lines.append("")
        lines.append("Действия стоят на границе месяца (доля месяца = 0), поэтому экономика не должна")
        lines.append("зависеть от `LUNEX_MONTH_SECONDS`. Отличается только подпись часов.")
        lines.append("")
        for left_name, right_name, diffs in compares:
            if diffs:
                lines.append("- **%s ≠ %s**, первых расхождений: %s." % (left_name, right_name, len(diffs)))
                for diff in diffs[:8]:
                    lines.append("  - %s" % diff)
            else:
                lines.append("- **%s = %s** по всем целым метрикам." % (left_name, right_name))
        lines.append("")
    lines.append("## Производительность шага")
    lines.append("")
    lines.append("Здания вставлены напрямую в `buildings` / `building_ops` (без поиска дороги),")
    lines.append("примерно по %s на компанию, у каждой стартовый капитал. Замеряется один `production.advance`"
                 % 10)
    lines.append("ровно на один игровой месяц. Это стоимость месячного расчёта, не стоимость стройки.")
    lines.append("")
    lines.append("| Здания | Компании | Шаг, мс | Мёд | Нефть | Товары | Население | Места | Инварианты |")
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for item in perf:
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            item["buildings"], item["companies"], _fmt(item["step_ms"]),
            item["honey_price"], item["oil_price"], item["goods_price"],
            item["population"], item["jobs"], len(item["invariants"])))
    lines.append("")
    if any(item["invariants"] for item in perf):
        lines.append("Нарушения на замере:")
        lines.append("")
        for item in perf:
            for text in item["invariants"]:
                lines.append("- %s зданий: %s" % (item["buildings"], text))
        lines.append("")
    lines.append("## Что с этим делать")
    lines.append("")
    lines.append("Ниже только наблюдения этого прогона и предложения. Константы `economy.py` отсюда не менялись;")
    lines.append("решение о правках — за владельцем. Подробности флагов — в сценариях выше (seed, месяц, метрика).")
    lines.append("")
    codes = []
    for _name, run in runs:
        for flag in run["flags"]:
            if flag["code"] not in codes:
                codes.append(flag["code"])
    suggestions = {
        "open_loop": "Замкнуть круг: жители тратят `system:residents` на мёд и товары (это уже пункт дорожной карты). "
                     "Пока рынок — бездонный покупатель, частные деньги растут вместе с выпуском, а зарплата исчезает из оборота.",
        "price_pin": "Цена упёрлась в `MIN_PRICE_K`/`MAX_PRICE_K` несколько месяцев подряд и больше не несёт сигнала. "
                     "Имеет смысл сузить выпуск или усилить реакцию спроса, а не только расширить коридор.",
        "price_whipsaw": "Склады держат весь выпуск, если прошлая цена ниже 0,9 от базовой, и продают всё, когда цена выше. "
                         "Компании делают это синхронно, поэтому предложение то обнуляется (цена в потолок 2,5×), "
                         "то выплёскивается (цена ниже порога) — через месяц. Так нефть ведёт себя с месяца 64 "
                         "в прогоне только NPC (seed 20261114), мёд — с месяца 37, если игроки разогнали фермы. "
                         "Предложение владельцу: прятать долю, а не 100 %, и сглаживать порог по нескольким месяцам. Константу отсюда не меняли.",
        "mass_default": "Одинаковые боты умирают в один месяц: кредит «бери максимум и строй самое дорогое» (seed 3, месяц 6, три компании) "
                        "и «строй по кругу», если очередь дошла до завода без своей нефти. NPC при этом живы. "
                        "После списания кредита `system:bank` остаётся отрицательным: непогашенное тело так и крутится в экономике "
                        "(прогон credit_60, seed 3, месяц 59: банк −688689 ₽ при нулевых остатках кредитов).",
        "population_floor": "Пол `MIN_POPULATION` прячет вымирание. Если город сидит на 140 много месяцев, спрос мёртвый — "
                            "смотреть безработицу и то, не режут ли NPC рабочие места быстрее, чем спрос.",
        "population_explode": "Миграция при нехватке рабочих до +3 %/мес плюс соцэффект может разогнать город. "
                              "Имеет смысл потолок населения или более быстрый найм, чтобы нехватка не держалась годами.",
        "population_zero": "Население 0 при живом поле `MIN_POPULATION` — ошибка кода, не баланс. Чинить `next_population`.",
        "npc_wiped": "Все три конкурента обанкротились. Проверить, не душит ли налог/кредит/перепроизводство; "
                     "перезапуск инвестора через 6 мес. может не успевать.",
        "slow_step": "Месячный шаг дороже бюджета. Смотреть число компаний, а не только зданий: расчёт идёт по компании "
                     "и пишет проводку. На боевом месяце (сутки) это терпимо, на тестовых 60 с — уже нет.",
    }
    if not codes:
        lines.append("Жёстких красных флагов, кроме разобранных в таблицах, генератор не собрал.")
    for code in codes:
        if code in suggestions:
            lines.append("- **%s.** %s" % (code, suggestions[code]))
    lines.append("")
    lines.append("Отдельно, даже если флага нет: казна `system:treasury` отрицательная ровно на выданный стартовый капитал")
    lines.append("(и награды мэра, если они были). Это не ошибка журнала. Ошибка — ненулевая сумма кошельков.")
    lines.append("")
    lines.append("## Не проверялось")
    lines.append("")
    lines.append("- PostgreSQL (симулятор сознательно только SQLite; боевую базу не открывает).")
    lines.append("- Клиент Godot и HTTP.")
    lines.append("- Сценарии с контрактами между игроками (их ещё нет в этой ветке).")
    lines.append("- Несколько городов и логистика.")
    lines.append("")
    return "\n".join(lines) + "\n"


def compare_runs(left, right, left_name, right_name):
    diffs = []
    if len(left["rows"]) != len(right["rows"]):
        diffs.append("разная длина ряда: %s и %s" % (len(left["rows"]), len(right["rows"])))
    for a, b in zip(left["rows"], right["rows"]):
        if economic_tuple(a) != economic_tuple(b):
            for key in METRIC_FIELDS:
                if a[key] != b[key]:
                    diffs.append("месяц %s поле %s: %s=%s, %s=%s" % (a["month"], key, left_name, a[key], right_name, b[key]))
            if len(diffs) > 40:
                break
    return diffs


def _strategies_from_args(args):
    if args.strategies:
        items = tuple(part.strip() for part in args.strategies.split(",") if part.strip())
    elif args.bots:
        items = tuple(STRATEGIES[i % len(STRATEGIES)] for i in range(args.bots))
    else:
        items = ()
    return items


def main(argv=None):
    parser = argparse.ArgumentParser(description="Симулятор баланса экономики LunexEconom (SQLite, без HTTP).")
    parser.add_argument("--months", type=int, default=72)
    parser.add_argument("--seed", type=int, default=20261114)
    parser.add_argument("--bots", type=int, default=0, help="число ботов, стратегии по кругу: %s" % ",".join(STRATEGIES))
    parser.add_argument("--strategies", default="", help="явный список через запятую, вместо --bots")
    parser.add_argument("--no-npc", action="store_true")
    parser.add_argument("--month-seconds", type=int, default=86400)
    parser.add_argument("--build-cap", type=int, default=16)
    parser.add_argument("--pin-months", type=int, default=DEFAULT_PIN_MONTHS)
    parser.add_argument("--step-budget-ms", type=float, default=DEFAULT_STEP_BUDGET_MS)
    parser.add_argument("--csv", default="")
    parser.add_argument("--md", default="", help="короткая сводка одного прогона")
    parser.add_argument("--perf", action="store_true", help="замер шага на 50/200/1000 зданиях и выход")
    parser.add_argument("--suite", action="store_true", help="набор сценариев для docs/BALANCE_REPORT.md")
    parser.add_argument("--report", default="", help="куда записать отчёт набора (вместе с --suite)")
    parser.add_argument("--out-dir", default="", help="каталог CSV для --suite")
    args = parser.parse_args(argv)

    if args.perf:
        for item in perf_probe():
            print("buildings=%s companies=%s step_ms=%s invariants=%s prices=%s/%s/%s" % (
                item["buildings"], item["companies"], item["step_ms"], len(item["invariants"]),
                item["honey_price"], item["oil_price"], item["goods_price"]))
            for text in item["invariants"]:
                print("  " + text)
        return 0

    if args.suite:
        return _suite(args)

    run = run_scenario(
        months=args.months, seed=args.seed, strategies=_strategies_from_args(args), npc_on=not args.no_npc,
        month_seconds=args.month_seconds, build_cap=args.build_cap, pin_months=args.pin_months,
        step_budget_ms=args.step_budget_ms,
    )
    last = run["rows"][-1]
    print("months=%s digest=%s invariants=%s flags=%s buildings=%s pop=%s honey=%s oil=%s goods=%s wallet_sum=%s" % (
        run["config"]["months"], run["digest"][:16], len(run["invariants"]), len(run["flags"]),
        last["buildings"], last["next_population"], last["honey_price"], last["oil_price"], last["goods_price"],
        last["wallet_sum"]))
    for item in run["invariants"]:
        print("INVARIANT " + item)
    for flag in run["flags"]:
        print("FLAG %s month=%s %s" % (flag["code"], flag["month"], flag["detail"]))
    if args.csv:
        write_csv(run["rows"], args.csv)
        print("csv " + args.csv)
    if args.md:
        text = render_report([("прогон", run)], [], [])
        os.makedirs(os.path.dirname(os.path.abspath(args.md)), exist_ok=True)
        with open(args.md, "w", encoding="utf-8") as handle:
            handle.write(text)
        print("md " + args.md)
    return 2 if run["invariants"] else 0


def _suite(args):
    out = args.out_dir or os.path.join(os.path.dirname(__file__), "samples")
    os.makedirs(out, exist_ok=True)
    specs = [
        ("npc_72", dict(months=72, seed=20261114, strategies=(), npc_on=True)),
        ("bots_72", dict(months=72, seed=20261114, strategies=("rotate", "hoard", "loan", "idle"), npc_on=True)),
        ("expand_48", dict(months=48, seed=7, strategies=("rotate",) * 6, npc_on=True, build_cap=10)),
        ("credit_60", dict(months=60, seed=3, strategies=("loan",) * 3, npc_on=True, build_cap=6)),
    ]
    runs = []
    for name, spec in specs:
        print("run " + name, flush=True)
        run = run_scenario(**spec)
        runs.append((name, run))
        write_csv(run["rows"], os.path.join(out, name + ".csv"))
        print("  invariants=%s flags=%s digest=%s elapsed=%ss" % (
            len(run["invariants"]), [f["code"] for f in run["flags"]], run["digest"][:12], run["elapsed_s"]), flush=True)
    print("compare month lengths", flush=True)
    slow = run_scenario(months=24, seed=20261114, strategies=(), npc_on=True, month_seconds=86400)
    fast = run_scenario(months=24, seed=20261114, strategies=(), npc_on=True, month_seconds=60)
    testmode = run_scenario(months=24, seed=20261114, strategies=(), npc_on=True, month_seconds=600)
    compares = [
        ("86400 с", "60 с", compare_runs(slow, fast, "86400", "60")),
        ("86400 с", "600 с", compare_runs(slow, testmode, "86400", "600")),
    ]
    for left, right, diffs in compares:
        print("  %s vs %s diffs=%s" % (left, right, len(diffs)), flush=True)
    print("perf", flush=True)
    perf = perf_probe()
    for item in perf:
        print("  buildings=%s step_ms=%s invariants=%s" % (item["buildings"], item["step_ms"], len(item["invariants"])), flush=True)
    report_path = args.report or os.path.join(os.path.dirname(__file__), "..", "docs", "BALANCE_REPORT.md")
    text = render_report(runs, perf, compares)
    os.makedirs(os.path.dirname(os.path.abspath(report_path)), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as handle:
        handle.write(text)
    print("report " + os.path.abspath(report_path))
    broken = sum(len(run["invariants"]) for _name, run in runs) + sum(len(item["invariants"]) for item in perf)
    return 2 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
