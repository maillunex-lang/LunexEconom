"""Observed consumer-price index (EX-09, docs/BANKING.md).

The index is a report. It does not rewrite clearing prices. The annual rate is clamped to the
corridor in the balance registry (0–10%, the same bounds as `balance_targets`). While
`INFLATION_ENABLED` is off, `monthly` writes nothing.
"""
import balance
import economy

BASKET = ("honey", "oil", "goods")


def _q(sql, ph):
    return sql.replace("%s", ph)


def enabled():
    return bool(balance.get("INFLATION_ENABLED"))


def ensure(db, ph):
    db.execute(
        "CREATE TABLE IF NOT EXISTS inflation_index(month_index BIGINT PRIMARY KEY, basket_ppm INTEGER NOT NULL,"
        "money_ppm INTEGER NOT NULL, rate_year_ppm INTEGER NOT NULL, index_ppm INTEGER NOT NULL, circulation BIGINT NOT NULL)")


def _basket(db, ph, month):
    ratios = []
    for product in BASKET:
        ref = economy.reference_price(product)
        row = db.execute(_q(
            "SELECT price FROM market_prices WHERE product=%s AND month_index=%s", ph), (product, int(month))).fetchone()
        if row and ref:
            ratios.append(int(row[0]) / float(ref))
    if not ratios:
        return 1.0
    return sum(ratios) / len(ratios)


def _circulation(db, ph):
    row = db.execute(_q("SELECT balance FROM wallets WHERE account=%s", ph), (economy.RESIDENTS,)).fetchone()
    residents = int(row[0]) if row else 0
    players = db.execute("SELECT COALESCE(SUM(balance),0) FROM wallets WHERE substr(account,1,7)='player:'").fetchone()
    return residents + int(players[0] if players else 0)


def _previous(db, ph, month):
    return db.execute(_q(
        "SELECT index_ppm,circulation FROM inflation_index WHERE month_index<%s ORDER BY month_index DESC LIMIT 1", ph),
        (int(month),)).fetchone()


def monthly(db, ph, month, now):
    if not enabled():
        return None
    ensure(db, ph)
    if db.execute(_q("SELECT 1 FROM inflation_index WHERE month_index=%s", ph), (int(month),)).fetchone():
        return view(db, ph)
    basket = _basket(db, ph, month)
    circ = _circulation(db, ph)
    prev = _previous(db, ph, month)
    if prev and int(prev[1]) > 0:
        money_pressure = (circ - int(prev[1])) / float(prev[1])
    else:
        money_pressure = 0.0
    raw = (float(balance.get("INFLATION_PRICE_WEIGHT")) * max(0.0, basket - 1.0)
           + float(balance.get("INFLATION_MONEY_WEIGHT")) * max(0.0, money_pressure))
    if int(balance.get("INFLATION_SHOCK") or 0):
        raw += 0.04
    rate = min(float(balance.get("INFLATION_MAX_YEAR")), max(float(balance.get("INFLATION_MIN_YEAR")), raw))
    index_ppm = int(round((int(prev[0]) if prev else 1_000_000) * (1.0 + rate / 12.0)))
    db.execute(_q(
        "INSERT INTO inflation_index(month_index,basket_ppm,money_ppm,rate_year_ppm,index_ppm,circulation) "
        "VALUES(%s,%s,%s,%s,%s,%s)", ph),
        (int(month), int(round(basket * 1_000_000)), int(round(max(0.0, money_pressure) * 1_000_000)),
         int(round(rate * 1_000_000)), index_ppm, circ))
    return view(db, ph)


def view(db, ph):
    ensure(db, ph)
    row = db.execute(
        "SELECT month_index,basket_ppm,money_ppm,rate_year_ppm,index_ppm,circulation FROM inflation_index "
        "ORDER BY month_index DESC LIMIT 1").fetchone()
    if row is None:
        return {"enabled": enabled(), "month": None, "index": 1.0, "rate_year": 0.0,
                "corridor": [float(balance.get("INFLATION_MIN_YEAR")), float(balance.get("INFLATION_MAX_YEAR"))],
                "basket": None}
    return {
        "enabled": enabled(), "month": int(row[0]),
        "basket": round(int(row[1]) / 1_000_000, 6),
        "money_pressure": round(int(row[2]) / 1_000_000, 6),
        "rate_year": round(int(row[3]) / 1_000_000, 6),
        "index": round(int(row[4]) / 1_000_000, 6),
        "circulation": int(row[5]),
        "corridor": [float(balance.get("INFLATION_MIN_YEAR")), float(balance.get("INFLATION_MAX_YEAR"))],
    }
