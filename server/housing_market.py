"""Housing stock, rent and mortgage quotes (EX-05, docs/POPULATION.md).

Supply is read from `buildings`: legacy `house` (owner `town:<city>`, capacity `HOUSE_LEGACY_CAPACITY`)
and any `city_catalog` housing kind. Construction should call `on_commissioned` when a house is delivered;
until that hook exists, `monthly` notices completed buildings itself. Money moves only while
`HOUSEHOLDS_ENABLED` is on, and only out of `system:residents` (no new cash).
"""
import balance
import city_catalog
import economy
import regional_prices

_HOUSING_IDS = {row[0] for row in city_catalog.HOUSING}


def _q(sql, ph):
    return sql.replace("%s", ph)


def ensure(db, ph):
    db.execute(
        "CREATE TABLE IF NOT EXISTS housing_stock(object_id TEXT PRIMARY KEY, city_id TEXT NOT NULL, kind TEXT NOT NULL,"
        "capacity INTEGER NOT NULL, owner TEXT NOT NULL, commissioned_month BIGINT NOT NULL)")
    db.execute(
        "CREATE TABLE IF NOT EXISTS housing_events(object_id TEXT PRIMARY KEY, city_id TEXT NOT NULL, kind TEXT NOT NULL,"
        "month_index BIGINT NOT NULL, created BIGINT NOT NULL)")
    db.execute(
        "CREATE TABLE IF NOT EXISTS housing_rent_log(city_id TEXT NOT NULL, month_index BIGINT NOT NULL, amount BIGINT NOT NULL,"
        "PRIMARY KEY(city_id, month_index))")
    db.execute(
        "CREATE TABLE IF NOT EXISTS housing_mortgages(id TEXT PRIMARY KEY, city_id TEXT NOT NULL, owner TEXT NOT NULL,"
        "principal BIGINT NOT NULL, balance BIGINT NOT NULL, payment BIGINT NOT NULL, rate_ppm INTEGER NOT NULL,"
        "term_months INTEGER NOT NULL, paid_months INTEGER NOT NULL, collateral TEXT NOT NULL)")


def capacity_of(kind):
    if kind == "house":
        return int(balance.get("HOUSE_LEGACY_CAPACITY"))
    item = city_catalog.get(kind)
    if item and item.get("category") == "housing":
        return int(item["capacity"])
    return 0


def is_housing(kind):
    return kind == "house" or kind in _HOUSING_IDS


def _completed(db):
    return db.execute(
        "SELECT b.id,b.owner,b.kind,b.x,b.y FROM buildings b "
        "LEFT JOIN construction_stages cs ON cs.object_id=b.id "
        "WHERE cs.stage IS NULL OR cs.stage='complete'").fetchall()


def _city_of(x, y):
    import regions
    if x is None or y is None:
        return regions.HOME
    return regions.region_of(int(x), int(y))


def capacity_by_city(db, ph):
    out = {}
    for _oid, _owner, kind, x, y in _completed(db):
        cap = capacity_of(kind)
        if cap <= 0:
            continue
        city = _city_of(x, y)
        out[city] = out.get(city, 0) + cap
    return out


def housing_supply(db, ph, city_id):
    """Units and resident-capacity standing in a city. Read-only."""
    by_kind = {}
    owners = {}
    for oid, owner, kind, x, y in _completed(db):
        cap = capacity_of(kind)
        if cap <= 0 or _city_of(x, y) != city_id:
            continue
        slot = by_kind.setdefault(kind, {"units": 0, "capacity": 0})
        slot["units"] += 1
        slot["capacity"] += cap
        owners[owner] = owners.get(owner, 0) + cap
    capacity = sum(item["capacity"] for item in by_kind.values())
    row = db.execute(_q("SELECT children+working+retired FROM household_cities WHERE city_id=%s", ph), (city_id,)).fetchone()
    if row:
        people = int(row[0])
    else:
        people = None
    return {
        "city": city_id, "units": sum(item["units"] for item in by_kind.values()), "capacity": capacity,
        "by_kind": by_kind, "owners": owners,
        "people": people,
        "occupied": None if people is None else min(people, capacity),
        "deficit": None if people is None else max(0, people - capacity),
        "surplus": None if people is None else max(0, capacity - people),
    }


def on_commissioned(db, ph, object_id, city_id, kind, owner, month, now, capacity=None):
    """Record a delivered house once. Safe to call from construction; also used by the monthly scan."""
    ensure(db, ph)
    if db.execute(_q("SELECT 1 FROM housing_events WHERE object_id=%s", ph), (object_id,)).fetchone():
        return False
    cap = capacity_of(kind) if capacity is None else int(capacity)
    if cap <= 0:
        return False
    db.execute(_q(
        "INSERT INTO housing_stock(object_id,city_id,kind,capacity,owner,commissioned_month) VALUES(%s,%s,%s,%s,%s,%s)", ph),
        (object_id, city_id, kind, cap, owner, int(month)))
    db.execute(_q(
        "INSERT INTO housing_events(object_id,city_id,kind,month_index,created) VALUES(%s,%s,%s,%s,%s)", ph),
        (object_id, city_id, kind, int(month), int(now)))
    return True


def _scan(db, ph, month, now):
    for oid, owner, kind, x, y in _completed(db):
        if not is_housing(kind):
            continue
        on_commissioned(db, ph, oid, _city_of(x, y), kind, owner, month, now)


def rent_per_person(city_id):
    return int(round(float(regional_prices.rent_m2_month(city_id)) * regional_prices.AREA_PER_RESIDENT))


def price_per_person(city_id):
    return int(regional_prices.market_price_m2(city_id)) * regional_prices.AREA_PER_RESIDENT


def _split(total, weights):
    whole = sum(weights.values())
    if total <= 0 or whole <= 0:
        return {}
    out = {key: total * value // whole for key, value in weights.items()}
    left = total - sum(out.values())
    order = sorted(weights, key=lambda key: (-(total * weights[key] % whole), key))
    for key in order:
        if left <= 0:
            break
        out[key] += 1
        left -= 1
    return {key: value for key, value in out.items() if value}


def _rent(db, ph, month, now):
    import geo
    row = db.execute(_q("SELECT balance FROM wallets WHERE account=%s", ph), (economy.RESIDENTS,)).fetchone()
    pool = max(0, int(row[0])) if row else 0
    for city in geo.CITY_DATA:
        city_id = city[0]
        if db.execute(_q("SELECT 1 FROM housing_rent_log WHERE city_id=%s AND month_index=%s", ph), (city_id, int(month))).fetchone():
            continue
        supply = housing_supply(db, ph, city_id)
        people = supply["people"] or 0
        occupied = min(people, supply["capacity"])
        due = occupied * rent_per_person(city_id)
        pay = min(due, pool)
        parts = _split(pay, supply["owners"])
        paid = sum(parts.values())
        if paid:
            entries = [(economy.RESIDENTS, -paid)]
            for owner, part in sorted(parts.items()):
                entries.append((economy.player_account(owner), part))
            economy.post(db, ph, "rent", "Аренда жилья, %s: %d" % (city_id, paid), entries, now)
            pool -= paid
        db.execute(_q("INSERT INTO housing_rent_log(city_id,month_index,amount) VALUES(%s,%s,%s)", ph), (city_id, int(month), paid))


def monthly(db, ph, month, now):
    if not balance.get("HOUSEHOLDS_ENABLED"):
        return
    ensure(db, ph)
    _scan(db, ph, month, now)
    _rent(db, ph, month, now)


def clamp_rate(annual):
    return min(float(balance.get("MORTGAGE_RATE_MAX_YEAR")), max(float(balance.get("MORTGAGE_RATE_MIN_YEAR")), float(annual)))


def annuity(principal, annual_rate, months):
    principal = int(principal)
    months = int(months)
    if principal <= 0 or months <= 0:
        return 0
    rate = clamp_rate(annual_rate)
    monthly = rate / 12.0
    if monthly <= 0:
        return max(1, (principal + months - 1) // months)
    growth = (1.0 + monthly) ** months
    return max(1, int(round(principal * monthly * growth / (growth - 1.0))))


def quote_mortgage(principal, annual_rate=None, months=None, income_year=0, city_id="ufa"):
    """Annuity quote. Burden is annual payments / annual income; the corridor cap is 45%."""
    principal = int(principal)
    term = int(balance.get("MORTGAGE_TERM_MONTHS") if months is None else months)
    rate = clamp_rate(balance.get("MORTGAGE_RATE_YEAR") if annual_rate is None else annual_rate)
    payment = annuity(principal, rate, term)
    income_year = int(income_year or 0)
    burden = None if income_year <= 0 else round(payment * 12 / income_year, 4)
    cap = int(balance.get("MORTGAGE_BURDEN_MAX_PPM")) / 1000.0
    return {
        "city": city_id, "principal": principal, "payment": payment, "term_months": term,
        "rate_year": round(rate, 4), "income_year": income_year, "burden": burden,
        "within_burden": None if burden is None else burden <= cap + 1e-9,
        "ltv": int(balance.get("MORTGAGE_LTV_PPM")) / 1000.0,
        "price_per_person": price_per_person(city_id), "rent_per_person": rent_per_person(city_id),
    }


def view(db, ph, city_id):
    ensure(db, ph)
    supply = housing_supply(db, ph, city_id)
    events = db.execute(_q(
        "SELECT object_id,kind,month_index FROM housing_events WHERE city_id=%s ORDER BY object_id", ph), (city_id,)).fetchall()
    sample = quote_mortgage(max(price_per_person(city_id), 1), city_id=city_id, income_year=int(balance.get("BASE_WAGE")) * 12)
    return {
        "enabled": bool(balance.get("HOUSEHOLDS_ENABLED")),
        "city": city_id,
        "price_m2": regional_prices.market_price_m2(city_id),
        "rent_m2": regional_prices.rent_m2_month(city_id),
        "supply": supply,
        "events": [{"object_id": oid, "kind": kind, "month": int(month)} for oid, kind, month in events],
        "mortgage_sample": sample,
    }
