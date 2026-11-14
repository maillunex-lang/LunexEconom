"""City government: the mayor, tax policy within legal limits, social service coverage and the monthly city budget.

The budget is the wallet of the pseudo-owner economy.CITY (taxes flow in, see taxes.py). The mayor can change profit and
property tax (inside economy.PROFIT_TAX_LIMITS / PROPERTY_TAX_LIMITS, once per game month) and order social buildings
(school, hospital, park) that are paid from the budget. VAT is federal law and cannot be changed by the mayor.
Shared by SQLite and PostgreSQL (`ph` = SQL placeholder).
"""
import economy
import taxes

ADMIN = "npc:administration"
ADMIN_NAME = "Городская администрация"
DEFAULT_SOCIAL_SHARE = 0.30


def _q(sql, ph):
    return sql.replace("%s", ph)


def ensure(db, ph, month=0):
    """Create the default mayor (the administration) and the default policy once."""
    if db.execute("SELECT 1 FROM city_state WHERE id=1").fetchone() is None:
        db.execute(_q("INSERT INTO city_state(id,mayor,mayor_name,since_month,term_end_month) VALUES(1,%s,%s,%s,%s)", ph),
                   (ADMIN, ADMIN_NAME, month, month + economy.ELECTION_PERIOD))
    if db.execute("SELECT 1 FROM city_policy WHERE id=1").fetchone() is None:
        db.execute(_q("INSERT INTO city_policy(id,profit_tax_permille,property_tax_permille,social_share_permille,changed_month) VALUES(1,%s,%s,%s,%s)", ph),
                   (int(round(economy.DEFAULT_PROFIT_TAX * 1000)), int(round(economy.DEFAULT_PROPERTY_TAX * 1000)),
                    int(DEFAULT_SOCIAL_SHARE * 1000), -1))


def mayor(db, ph, month=0):
    ensure(db, ph, month)
    m, name, since, end = db.execute("SELECT mayor,mayor_name,since_month,term_end_month FROM city_state WHERE id=1").fetchone()
    return {"owner": m, "name": name, "since_month": int(since), "term_end_month": int(end), "is_npc": m.startswith("npc:")}


def is_mayor(db, ph, owner, month=0):
    return mayor(db, ph, month)["owner"] == owner


def set_mayor(db, ph, owner, name, month):
    ensure(db, ph, month)
    db.execute(_q("UPDATE city_state SET mayor=%s,mayor_name=%s,since_month=%s,term_end_month=%s WHERE id=1", ph),
               (owner, name, month, month + economy.ELECTION_PERIOD))


def set_taxes(db, ph, owner, profit, prop, month):
    """The mayor changes profit/property tax; limits are the law, at most one change per game month."""
    if not taxes.enabled():
        return 409, {"error": "taxes_disabled"}
    if not is_mayor(db, ph, owner, month):
        return 403, {"error": "not_mayor"}
    for value in (profit, prop):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return 400, {"error": "invalid_rate"}
    lo_p, hi_p = economy.PROFIT_TAX_LIMITS
    lo_i, hi_i = economy.PROPERTY_TAX_LIMITS
    if not (lo_p - 1e-9 <= profit <= hi_p + 1e-9 and lo_i - 1e-9 <= prop <= hi_i + 1e-9):
        return 400, {"error": "out_of_limits", "limits": {"profit_tax": [lo_p, hi_p], "property_tax": [lo_i, hi_i]}}
    changed = int(db.execute("SELECT changed_month FROM city_policy WHERE id=1").fetchone()[0])
    if changed >= month:
        return 409, {"error": "cooldown", "next_change_month": changed + 1}
    db.execute(_q("UPDATE city_policy SET profit_tax_permille=%s,property_tax_permille=%s,changed_month=%s WHERE id=1", ph),
               (int(round(profit * 1000)), int(round(prop * 1000)), month))
    return 200, {"ok": True, "taxes": taxes.view(db, ph)}


def social_counts(db, ph, month):
    counts = {k: 0 for k in economy.SOCIAL_KINDS}
    for kind, in db.execute(_q("SELECT kind FROM building_ops WHERE owner=%s AND start_month<=%s", ph), (economy.CITY, month)).fetchall():
        if kind in counts:
            counts[kind] += 1
    return counts


def social(db, ph, month, population, funded=True):
    """Coverage (0..1) of every service and the quality-of-life index."""
    counts = social_counts(db, ph, month)
    coverage = {}
    for kind in economy.SOCIAL_KINDS:
        served = counts[kind] * economy.PRODUCTION[kind]["serves"]
        coverage[kind] = min(1.0, served / max(population, 1)) * (1.0 if funded else 0.5)
    quality = sum(coverage.values()) / len(economy.SOCIAL_KINDS)
    return {"counts": counts, "coverage": coverage, "quality": quality, "funded": bool(funded)}


def monthly(db, ph, month, now):
    """City expenses outside company payroll: road maintenance and the human mayor's salary (never below zero)."""
    budget = economy.player_account(economy.CITY)
    cash = economy.balance(db, ph, economy.CITY) or 0
    m = mayor(db, ph, month)
    roads = db.execute("SELECT COUNT(*) FROM roads").fetchone()[0]
    road_cost = min(int(roads) * economy.ROAD_MAINTENANCE, max(cash, 0))
    if road_cost:
        economy.post(db, ph, "city", "Содержание дорог: %d" % road_cost, [(budget, -road_cost), (economy.UPKEEP, road_cost)], now)
        cash -= road_cost
    if not m["is_npc"]:
        salary = min(economy.MAYOR_SALARY, max(cash, 0))
        if salary:
            economy.ensure_wallet(db, ph, m["owner"], now)
            economy.post(db, ph, "city", "Зарплата мэра: %d" % salary, [(budget, -salary), (economy.player_account(m["owner"]), salary)], now)
