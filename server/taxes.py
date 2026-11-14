"""Taxes: profit tax, VAT by product category and property tax. Everything is collected into the city budget
(the wallet of the pseudo-owner economy.CITY). Shared by SQLite and PostgreSQL (`ph` = SQL placeholder).

Model per company and game month (see docs/TAXES.md for the real-world rates behind the defaults):
  * VAT: consumers pay price + VAT, the company pays VAT on the raw materials it buys. The company remits
    output VAT - input VAT; a surplus of input VAT becomes a credit carried to later months. The company margin is
    unchanged, the tax is borne by the buyer. Rates depend on the product (honey 10 %, oil and goods 22 %).
  * Profit tax: rate * positive monthly profit (revenue - raw materials - wages - maintenance - interest, all without VAT).
  * Property tax: annual rate / 12 of the construction cost of the company's buildings.
Unpaid taxes become tax arrears (repaid right after wages) and count as a missed month.
"""
import economy


def _q(sql, ph):
    return sql.replace("%s", ph)


def enabled():
    return bool(economy.TAXES_ENABLED)


def vat_rate(product):
    return float(economy.VAT_RATES.get(product, economy.VAT_STANDARD)) if enabled() else 0.0


def clamp(value, limits):
    return min(max(value, limits[0]), limits[1])


def rates(db, ph):
    """Current profit and property tax rates (the mayor's policy, or the defaults before any policy exists)."""
    if not enabled():
        return {"profit": 0.0, "property": 0.0}
    row = db.execute("SELECT profit_tax_permille,property_tax_permille FROM city_policy WHERE id=1").fetchone()
    if row:
        return {"profit": row[0] / 1000.0, "property": row[1] / 1000.0}
    return {"profit": economy.DEFAULT_PROFIT_TAX, "property": economy.DEFAULT_PROPERTY_TAX}


def view(db, ph):
    r = rates(db, ph)
    return {"enabled": enabled(), "profit_tax": r["profit"], "property_tax": r["property"],
            "vat": {p: vat_rate(p) for p in economy.MARKET}, "vat_standard": economy.VAT_STANDARD if enabled() else 0.0,
            "limits": {"profit_tax": list(economy.PROFIT_TAX_LIMITS), "property_tax": list(economy.PROPERTY_TAX_LIMITS)}}


def vat_amounts(rev_by, in_by):
    out = sum(int(round(v * vat_rate(p))) for p, v in rev_by.items())
    inn = sum(int(round(v * vat_rate(p))) for p, v in in_by.items())
    return out, inn


def profit_tax_due(taxable, rate):
    return int(max(taxable, 0) * rate)


def property_tax_due(buildings, rate):
    """Monthly property tax: annual rate / 12 of the construction cost of the buildings (kind, share of the month)."""
    base = sum(economy.BUILD_COST.get(kind, 0) * factor // 1000 for kind, factor in buildings)
    return int(base * rate / 12)


def state(db, ph, owner):
    row = db.execute(_q("SELECT tax_owed,vat_credit FROM company_tax_state WHERE owner=%s", ph), (owner,)).fetchone()
    return {"tax_owed": int(row[0]), "vat_credit": int(row[1])} if row else {"tax_owed": 0, "vat_credit": 0}


def save_state(db, ph, owner, st):
    db.execute(_q("INSERT INTO company_tax_state(owner,tax_owed,vat_credit) VALUES(%s,%s,%s) ON CONFLICT(owner) DO UPDATE SET "
                  "tax_owed=excluded.tax_owed,vat_credit=excluded.vat_credit", ph), (owner, st["tax_owed"], st["vat_credit"]))


def record(db, ph, owner, month, vat, profit_tax, property_tax, paid):
    db.execute(_q("INSERT INTO company_taxes(owner,month_index,vat,profit_tax,property_tax,paid) VALUES(%s,%s,%s,%s,%s,%s) "
                  "ON CONFLICT(owner,month_index) DO NOTHING", ph), (owner, month, vat, profit_tax, property_tax, paid))


def last_taxes(db, ph, owner, limit=6):
    rows = db.execute(_q("SELECT month_index,vat,profit_tax,property_tax,paid FROM company_taxes WHERE owner=%s ORDER BY month_index DESC LIMIT %s", ph),
                      (owner, limit)).fetchall()
    return {int(m): {"vat": int(v), "profit_tax": int(p), "property_tax": int(r), "paid": int(d)} for m, v, p, r, d in rows}
