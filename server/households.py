"""Aggregated households, one row per city (EX-05, docs/POPULATION.md).

The live labour market (`production.labor_market`, the `population` table, base 200 in Ufa) is not replaced.
`POPULATION_SCALE` turns the real 2024 headcount in `geo.CITY_DATA` into a household stock. While
`HOUSEHOLDS_ENABLED` is off, `monthly` returns before any write and `consumer_demand` is exactly
`economy.demand_for`.
"""
import balance
import economy
import geo
import housing_market
import regional_prices

PROFESSIONS = ("agro", "industry", "service", "construction", "public")
CHILD_MONTHS = 18 * 12
WORK_MONTHS = 42 * 12

_CITY_STATE = (
    "children", "working", "retired", "families", "income", "savings", "skill_ppm", "employed",
    "satisfaction_ppm", "births", "deaths", "aged", "migrants_in", "migrants_out",
    "birth_acc", "death_acc", "child_age_acc", "work_age_acc", "updated_month",
)


def _q(sql, ph):
    return sql.replace("%s", ph)


def enabled():
    return bool(balance.get("HOUSEHOLDS_ENABLED"))


def scale_of(real, scale=None):
    """Game household people for a real headcount. Half-integers follow Python round (half to even)."""
    divisor = int(balance.get("POPULATION_SCALE") if scale is None else scale)
    divisor = max(1, divisor)
    return max(1, int(round(float(real) / divisor)))


def city_table():
    return [{"id": cid, "name": name, "real": residents, "tag": tag}
            for cid, name, _lat, _lon, residents, tag in geo.CITY_DATA]


def scale_preview(scale=None):
    return [{**row, "scaled": scale_of(row["real"], scale)} for row in city_table()]


def ensure(db, ph):
    statements = (
        "CREATE TABLE IF NOT EXISTS household_cities("
        "city_id TEXT PRIMARY KEY, children INTEGER NOT NULL, working INTEGER NOT NULL, retired INTEGER NOT NULL,"
        "families INTEGER NOT NULL, income BIGINT NOT NULL, savings BIGINT NOT NULL, skill_ppm INTEGER NOT NULL,"
        "employed INTEGER NOT NULL, satisfaction_ppm INTEGER NOT NULL, births INTEGER NOT NULL, deaths INTEGER NOT NULL,"
        "aged INTEGER NOT NULL, migrants_in INTEGER NOT NULL, migrants_out INTEGER NOT NULL,"
        "birth_acc INTEGER NOT NULL, death_acc INTEGER NOT NULL, child_age_acc INTEGER NOT NULL,"
        "work_age_acc INTEGER NOT NULL, updated_month BIGINT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS household_months(month_index BIGINT PRIMARY KEY)",
        "CREATE TABLE IF NOT EXISTS household_jobs(city_id TEXT NOT NULL, profession TEXT NOT NULL,"
        "headcount INTEGER NOT NULL, skill_ppm INTEGER NOT NULL, PRIMARY KEY(city_id, profession))",
    )
    for statement in statements:
        db.execute(statement)
    housing_market.ensure(db, ph)
    import banking
    banking.ensure(db, ph)


def _blank(city, month):
    scaled = scale_of(city["real"])
    children = int(round(scaled * float(balance.get("HH_CHILD_SHARE"))))
    retired = int(round(scaled * float(balance.get("HH_RETIRED_SHARE"))))
    if children + retired > scaled:
        retired = max(0, scaled - children)
    working = scaled - children - retired
    return {
        "city_id": city["id"], "name": city["name"], "tag": city["tag"], "real": city["real"],
        "children": children, "working": working, "retired": retired,
        "families": 0, "income": 0, "savings": 0,
        "skill_ppm": int(balance.get("HH_SKILL_PPM")), "employed": 0, "satisfaction_ppm": 0,
        "births": 0, "deaths": 0, "aged": 0, "migrants_in": 0, "migrants_out": 0,
        "birth_acc": 0, "death_acc": 0, "child_age_acc": 0, "work_age_acc": 0,
        "updated_month": month, "capacity": 0,
    }


def _load(db, ph):
    rows = db.execute("SELECT city_id," + ",".join(_CITY_STATE) + " FROM household_cities").fetchall()
    known = {row["id"]: row for row in city_table()}
    out = {}
    for record in rows:
        city = known.get(record[0])
        if city is None:
            continue
        state = {"city_id": record[0], "name": city["name"], "tag": city["tag"], "real": city["real"], "capacity": 0}
        for key, value in zip(_CITY_STATE, record[1:]):
            state[key] = int(value)
        out[record[0]] = state
    for city in city_table():
        out.setdefault(city["id"], _blank(city, -1))
    return out


def _headcount(state):
    return state["children"] + state["working"] + state["retired"]


def _take(state, group, count):
    take = min(state[group], count)
    state[group] -= take
    return count - take


def _vital(state):
    pop = _headcount(state)
    state["birth_acc"] += pop * int(balance.get("BIRTHS_PER_1000"))
    births = state["birth_acc"] // 12000
    state["birth_acc"] %= 12000
    state["death_acc"] += pop * int(balance.get("DEATHS_PER_1000"))
    deaths = state["death_acc"] // 12000
    state["death_acc"] %= 12000
    state["children"] += births
    left = deaths
    for group in ("retired", "working", "children"):
        left = _take(state, group, left)
    state["births"] = births
    state["deaths"] = deaths - left
    state["child_age_acc"] += state["children"]
    to_work = min(state["children"], state["child_age_acc"] // CHILD_MONTHS)
    state["child_age_acc"] %= CHILD_MONTHS
    state["children"] -= to_work
    state["working"] += to_work
    state["work_age_acc"] += state["working"]
    to_retired = min(state["working"], state["work_age_acc"] // WORK_MONTHS)
    state["work_age_acc"] %= WORK_MONTHS
    state["working"] -= to_retired
    state["retired"] += to_retired
    state["aged"] = to_work + to_retired


def _attract(state, jobs):
    wage = regional_prices.wage(state["city_id"], int(balance.get("BASE_WAGE")))
    pop = max(_headcount(state), 1)
    cap = state.get("capacity", 0)
    if int(balance.get("HH_HOUSING_STRESS") or 0):
        cap = cap * 40 // 100
    comfort = min(1.5, cap / pop)
    seekers = max(state["working"] * int(balance.get("HH_PARTICIPATION_PPM")) // 1000, 1)
    if int(balance.get("HH_RECESSION") or 0):
        jobs = jobs * 70 // 100
    employed = min(seekers, jobs)
    return wage * (0.6 + 0.4 * comfort) * (0.5 + 0.5 * employed / seekers)


def _migrate(states, jobs):
    ppm = int(balance.get("HH_MIGRATION_PPM"))
    if ppm <= 0 or len(states) < 2:
        return
    ranked = sorted((_attract(state, jobs.get(cid, 0)), cid) for cid, state in states.items())
    half = len(ranked) // 2
    donors, receivers = ranked[:half], ranked[half:]
    if not receivers:
        return
    pool = 0
    leaving = {}
    for _score, cid in donors:
        leave = min(states[cid]["working"], states[cid]["working"] * ppm // 1000)
        if leave <= 0:
            continue
        leaving[cid] = leave
        pool += leave
    if pool <= 0:
        return
    weights = [(max(score, 0.001), cid) for score, cid in receivers]
    total_w = sum(score for score, _cid in weights)
    assigned = {}
    used = 0
    for score, cid in weights:
        got = int(pool * score // total_w) if total_w else 0
        assigned[cid] = got
        used += got
    left = pool - used
    order = sorted(weights, key=lambda item: (-((pool * item[0]) % total_w if total_w else 0), item[1]))
    for index in range(left):
        assigned[order[index % len(order)][1]] += 1
    for cid, leave in leaving.items():
        states[cid]["working"] -= leave
        states[cid]["migrants_out"] += leave
    for cid, got in assigned.items():
        states[cid]["working"] += got
        states[cid]["migrants_in"] += got


def _weights(tag):
    weights = {"agro": 20, "industry": 25, "service": 30, "construction": 10, "public": 15}
    text = tag or ""
    if "агро" in text:
        weights["agro"] += 25
    if any(word in text for word in ("нефт", "хим", "маш", "метал", "добыч", "энерг", "горно")):
        weights["industry"] += 25
    if "образован" in text:
        weights["public"] += 15
    if any(word in text for word in ("логист", "управлен")):
        weights["service"] += 15
    return weights


def _split(working, weights):
    total = sum(weights.values()) or 1
    counts = {key: working * weights[key] // total for key in PROFESSIONS}
    left = working - sum(counts.values())
    order = sorted(PROFESSIONS, key=lambda key: (-weights[key], key))
    for index in range(left):
        counts[order[index % len(order)]] += 1
    return counts


def _finish(state, jobs):
    if int(balance.get("HH_RECESSION") or 0):
        jobs = jobs * 70 // 100
    if int(balance.get("HH_HOUSING_STRESS") or 0):
        state["comfort_capacity"] = state.get("capacity", 0) * 40 // 100
    else:
        state["comfort_capacity"] = state.get("capacity", 0)
    seekers = state["working"] * int(balance.get("HH_PARTICIPATION_PPM")) // 1000
    state["employed"] = min(seekers, max(0, int(jobs)))
    wage = regional_prices.wage(state["city_id"], int(balance.get("BASE_WAGE")))
    skill = max(700, min(1500, state["skill_ppm"]))
    if seekers > 0 and state["employed"] * 1000 >= seekers * 900:
        skill = min(1500, skill + 1)
    elif seekers > state["employed"]:
        skill = max(700, skill - 1)
    state["skill_ppm"] = skill
    state["income"] = int(state["employed"] * wage * skill // 1000)
    state["savings"] += state["income"] * int(balance.get("HH_SAVINGS_PPM")) // 1000
    pop = max(_headcount(state), 1)
    state["families"] = pop * int(balance.get("FAMILY_PER_1000")) // 1000
    comfort = min(1.5, state["comfort_capacity"] / pop)
    emp = state["employed"] / seekers if seekers else 1.0
    wage_k = min(1.2, wage / max(int(balance.get("BASE_WAGE")), 1))
    sat = 0.45 * emp + 0.30 * min(1.0, comfort) + 0.25 * (wage_k / 1.2)
    state["satisfaction_ppm"] = int(round(min(1.0, max(0.0, sat)) * 1000))
    state["professions"] = _split(state["working"], _weights(state["tag"]))


def _save(db, ph, state, month):
    columns = ("city_id",) + _CITY_STATE
    state["updated_month"] = month
    values = [state["city_id"]] + [int(state[key]) for key in _CITY_STATE]
    marks = ",".join(["%s"] * len(columns))
    updates = ",".join("%s=excluded.%s" % (key, key) for key in _CITY_STATE)
    db.execute(_q(
        "INSERT INTO household_cities(" + ",".join(columns) + ") VALUES(" + marks + ") "
        "ON CONFLICT(city_id) DO UPDATE SET " + updates, ph), tuple(values))
    db.execute(_q("DELETE FROM household_jobs WHERE city_id=%s", ph), (state["city_id"],))
    for name, count in state["professions"].items():
        db.execute(_q(
            "INSERT INTO household_jobs(city_id,profession,headcount,skill_ppm) VALUES(%s,%s,%s,%s)", ph),
            (state["city_id"], name, int(count), int(state["skill_ppm"])))


def jobs_by_city(db, ph):
    import regions
    out = {row["id"]: 0 for row in city_table()}
    rows = db.execute(
        "SELECT o.kind,b.x,b.y FROM building_ops o LEFT JOIN buildings b ON b.id=o.object_id "
        "LEFT JOIN construction_stages cs ON cs.object_id=o.object_id "
        "WHERE cs.stage IS NULL OR cs.stage='complete'").fetchall()
    for kind, x, y in rows:
        city = regions.HOME if x is None else regions.region_of(int(x), int(y))
        if city in out:
            out[city] += economy.kind_jobs(kind)
    return out


def monthly(db, ph, month, now):
    """One city-month. Idempotent on month_index. No-op, and no writes, while the flag is off."""
    if not enabled():
        return {"enabled": False}
    ensure(db, ph)
    if db.execute(_q("SELECT 1 FROM household_months WHERE month_index=%s", ph), (int(month),)).fetchone():
        return {"enabled": True, "idempotent": True}
    states = _load(db, ph)
    for state in states.values():
        state["births"] = state["deaths"] = state["aged"] = state["migrants_in"] = state["migrants_out"] = 0
        _vital(state)
    jobs = jobs_by_city(db, ph)
    caps = housing_market.capacity_by_city(db, ph)
    for cid, state in states.items():
        state["capacity"] = caps.get(cid, 0)
    _migrate(states, jobs)
    for cid, state in states.items():
        _finish(state, jobs.get(cid, 0))
        _save(db, ph, state, int(month))
    housing_market.monthly(db, ph, month, now)
    db.execute(_q("INSERT INTO household_months(month_index) VALUES(%s)", ph), (int(month),))
    return {"enabled": True, "cities": len(states)}


def demand_factor(db, ph, city_id):
    """Bounded multiplier on consumer demand. Exactly 1 while households are off or not yet seeded."""
    if not enabled():
        return 1.0
    row = db.execute(_q("SELECT satisfaction_ppm FROM household_cities WHERE city_id=%s", ph), (city_id,)).fetchone()
    if row is None:
        return 1.0
    nudge = int(balance.get("HH_DEMAND_NUDGE_PPM")) / 1000.0
    if nudge <= 0:
        return 1.0
    delta = max(-1.0, min(1.0, (int(row[0]) / 1000.0 - 0.55) / 0.55))
    return 1.0 + nudge * delta


def consumer_demand(db, ph, product, month, scale, city_id=None):
    """`economy.demand_for` plus the household nudge. Identical to the old call while the flag is off."""
    base = economy.demand_for(product, month, scale)
    if not enabled() or not city_id:
        return base
    factor = demand_factor(db, ph, city_id)
    if abs(factor - 1.0) < 1e-12:
        return base
    return int(round(base * factor))


def legacy_headcount(db, ph, city_id):
    import regions
    if city_id == regions.HOME:
        row = db.execute("SELECT population FROM population ORDER BY month_index DESC LIMIT 1").fetchone()
        if row:
            return int(row[0])
        return int(balance.get("BASE_POPULATION"))
    row = db.execute(_q(
        "SELECT population FROM region_population WHERE region=%s ORDER BY month_index DESC LIMIT 1", ph), (city_id,)).fetchone()
    if row:
        return int(row[0])
    return int(balance.get("BASE_POPULATION"))


def _public_state(db, ph, state):
    pop = _headcount(state)
    jobs = db.execute(_q(
        "SELECT profession,headcount,skill_ppm FROM household_jobs WHERE city_id=%s ORDER BY profession", ph),
        (state["city_id"],)).fetchall()
    wage = regional_prices.wage(state["city_id"], int(balance.get("BASE_WAGE")))
    rent = housing_market.rent_per_person(state["city_id"])
    income = int(state["income"])
    return {
        "city": state["city_id"], "name": state["name"],
        "real_population": state["real"], "scaled": pop, "scale": int(balance.get("POPULATION_SCALE")),
        "legacy_population": legacy_headcount(db, ph, state["city_id"]),
        "groups": {"children": state["children"], "working": state["working"], "retired": state["retired"]},
        "families": state["families"],
        "professions": [{"id": name, "headcount": int(count), "skill": round(int(skill) / 1000.0, 3)} for name, count, skill in jobs],
        "employed": state["employed"],
        "unemployment": round(1.0 - state["employed"] / max(state["working"] * int(balance.get("HH_PARTICIPATION_PPM")) // 1000, 1), 4),
        "income": income, "savings": state["savings"], "wage": wage,
        "births": state["births"], "deaths": state["deaths"], "aged": state["aged"],
        "migrants_in": state["migrants_in"], "migrants_out": state["migrants_out"],
        "satisfaction": round(state["satisfaction_ppm"] / 1000.0, 3),
        "housing_share": None if income <= 0 else round(rent * pop / income, 4),
        "month": state["updated_month"],
    }


def view(db, ph, city_id=None):
    """Read model. Does not write. Empty stock falls back to the scale projection."""
    ensure(db, ph)
    wanted = city_table() if not city_id else [row for row in city_table() if row["id"] == city_id]
    if city_id and not wanted:
        return None
    stored_ids = {row[0] for row in db.execute("SELECT city_id FROM household_cities")}
    stored = _load(db, ph) if stored_ids else {}
    cities = []
    for city in wanted:
        if city["id"] not in stored_ids:
            preview = _blank(city, None)
            cities.append({
                "city": city["id"], "name": city["name"], "real_population": city["real"],
                "scaled": _headcount(preview), "scale": int(balance.get("POPULATION_SCALE")),
                "legacy_population": legacy_headcount(db, ph, city["id"]),
                "groups": {"children": preview["children"], "working": preview["working"], "retired": preview["retired"]},
                "simulated": False,
            })
        else:
            item = _public_state(db, ph, stored[city["id"]])
            item["simulated"] = True
            cities.append(item)
    return {"enabled": enabled(), "scale": int(balance.get("POPULATION_SCALE")), "cities": cities}
