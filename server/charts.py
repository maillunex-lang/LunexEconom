"""Read-only price and city charts. No ledger writes, no world tick."""
import economy


def _q(sql, ph):
    return sql.replace("%s", ph)


def _months(args):
    raw = args.get("months", "12")
    if raw in ("all", "0", ""):
        return None
    if type(raw) is not str or not raw.isascii() or not raw.isdigit() or len(raw) > 4:
        return "bad"
    value = int(raw)
    if value not in (12, 24) and not 1 <= value <= 600:
        return "bad"
    return value


def price_history(db, ph, owner, args):
    """GET /soc/charts/prices?product=&months=12|24|all"""
    product = args.get("product")
    if product not in economy.MARKET:
        return 400, {"error": "invalid_product"}
    months = _months(args)
    if months == "bad":
        return 400, {"error": "invalid_months"}
    sql = "SELECT month_index,price,supply,demand FROM market_prices WHERE product=%s ORDER BY month_index"
    rows = db.execute(_q(sql, ph), (product,)).fetchall()
    if months is not None:
        rows = rows[-months:]
    return 200, {"ok": True, "product": product, "name": economy.MARKET[product]["name"],
                 "reference_price": economy.MARKET[product]["reference_price"], "viewer": owner,
                 "products": [{"id": key, "name": economy.MARKET[key]["name"]} for key in economy.MARKET],
                 "points": [{"month": int(m), "price": int(p), "supply": int(s), "demand": int(d)} for m, p, s, d in rows]}


def economy_history(db, ph, owner, args):
    """GET /soc/charts/economy — population, unemployment permille, wage."""
    months = _months(args)
    if months == "bad":
        return 400, {"error": "invalid_months"}
    rows = db.execute("SELECT month_index,population,labor_force,jobs,wage FROM population ORDER BY month_index").fetchall()
    if months is not None:
        rows = rows[-months:]
    points = []
    for month, population, labor, jobs, wage in rows:
        labor, jobs = int(labor), int(jobs)
        employed = min(jobs, labor)
        unemployed = max(0, labor - employed)
        permille = 0 if labor <= 0 else unemployed * 1000 // labor
        points.append({"month": int(month), "population": int(population), "labor_force": labor,
                       "jobs": jobs, "unemployment_permille": permille, "wage": int(wage)})
    return 200, {"ok": True, "viewer": owner, "points": points}
