"""NPC banks, company shares and the extra tax schedule (EX-09, docs/BANKING.md).

The legacy revolving loan (`bank.py`, table `loans`) is not used here. NPC loans live in `bank_npc_loans`.
Every cash movement is one balanced `economy.post`. While `BANKS_ENABLED` and `TAX_EXTRAS_ENABLED` are off,
`monthly` does not write (inflation has its own flag and its own module).
"""
import json
import uuid

import balance
import bank
import economy
import inflation

BANKS = (
    {"id": "bashkredit", "name": "Башкредит", "policy": "conservative", "rate_add": 0.02, "ltv": 0.50,
     "products": ("working_capital", "mortgage")},
    {"id": "agroprombank", "name": "Агропромбанк", "policy": "agro", "rate_add": -0.01, "ltv": 0.65,
     "products": ("working_capital", "investment", "credit_line")},
    {"id": "uralinvest", "name": "Уралинвест", "policy": "investment", "rate_add": 0.04, "ltv": 0.55,
     "products": ("investment", "credit_line")},
)
PRODUCTS = {
    "working_capital": 12,
    "investment": 60,
    "mortgage": None,
    "credit_line": 12,
}
COLLATERAL_ADD = {"realty": 0.0, "equipment": 0.01, "transport": 0.015, "inventory": 0.03}
AGRO_MARKERS = ("farm", "flour", "dairy", "bakery", "cannery", "oil_press", "apiary")


def _q(sql, ph):
    return sql.replace("%s", ph)


def bank_account(bank_id):
    return "system:bank:" + bank_id


def _bank(bank_id):
    return next((item for item in BANKS if item["id"] == bank_id), None)


def ensure(db, ph):
    db.execute(
        "CREATE TABLE IF NOT EXISTS bank_npc_loans(id TEXT PRIMARY KEY, request_id TEXT NOT NULL, owner TEXT NOT NULL,"
        "bank_id TEXT NOT NULL, product TEXT NOT NULL, principal BIGINT NOT NULL, balance BIGINT NOT NULL,"
        "rate_ppm INTEGER NOT NULL, term_months INTEGER NOT NULL, payment BIGINT NOT NULL, collateral TEXT NOT NULL,"
        "collateral_value BIGINT NOT NULL, start_month BIGINT NOT NULL, missed INTEGER NOT NULL, status TEXT NOT NULL,"
        "UNIQUE(owner, request_id))")
    db.execute(
        "CREATE TABLE IF NOT EXISTS bank_npc_charges(loan_id TEXT NOT NULL, month_index BIGINT NOT NULL,"
        "PRIMARY KEY(loan_id, month_index))")
    db.execute(
        "CREATE TABLE IF NOT EXISTS company_shares(company TEXT NOT NULL, holder TEXT NOT NULL, shares BIGINT NOT NULL,"
        "paid BIGINT NOT NULL, PRIMARY KEY(company, holder))")
    db.execute(
        "CREATE TABLE IF NOT EXISTS dividend_paid(company TEXT NOT NULL, month_index BIGINT NOT NULL, amount BIGINT NOT NULL,"
        "PRIMARY KEY(company, month_index))")
    db.execute("CREATE TABLE IF NOT EXISTS bank_marks(mark TEXT PRIMARY KEY)")
    db.execute(
        "CREATE TABLE IF NOT EXISTS tax_extra_posted(owner TEXT NOT NULL, month_index BIGINT NOT NULL,"
        "land_tax BIGINT NOT NULL, payroll_tax BIGINT NOT NULL, sector_fee BIGINT NOT NULL, paid BIGINT NOT NULL,"
        "PRIMARY KEY(owner, month_index))")
    inflation.ensure(db, ph)


def tax_rates():
    """Profit, VAT and property are the live rates (taxes.py). Land, payroll and sector fees post only behind the flag."""
    return {
        "profit": float(balance.get("DEFAULT_PROFIT_TAX")),
        "property": float(balance.get("DEFAULT_PROPERTY_TAX")),
        "vat": float(balance.get("VAT_STANDARD")),
        "land": float(balance.get("LAND_TAX")),
        "payroll": float(balance.get("PAYROLL_TAX")),
        "sector_fee": float(balance.get("SECTOR_FEE")),
        "extras_enabled": bool(balance.get("TAX_EXTRAS_ENABLED")),
    }


def missed_months(db, ph, owner):
    row = db.execute(_q("SELECT missed FROM company_status WHERE owner=%s", ph), (owner,)).fetchone()
    return int(row[0]) if row else 0


def collateral_value(db, ph, owner, kind):
    if kind == "realty":
        return int(bank.appraisal(db, ph, owner))
    if kind == "equipment":
        rows = db.execute(_q(
            "SELECT d.equipment_level FROM building_dimensions d JOIN building_ops o ON o.object_id=d.object_id "
            "WHERE o.owner=%s", ph), (owner,)).fetchall()
        unit = int(balance.get("EQUIPMENT_COLLATERAL"))
        return sum(max(0, int(level) - 1) * unit for level, in rows)
    if kind == "transport":
        row = db.execute(_q("SELECT units,capacity_each FROM company_trucks WHERE owner=%s", ph), (owner,)).fetchone()
        if not row:
            return 0
        return int(row[0]) * int(balance.get("TRUCK_PRICE"))
    if kind == "inventory":
        total = 0
        for product, qty in db.execute(_q("SELECT product,qty FROM inventory WHERE owner=%s", ph), (owner,)).fetchall():
            total += int(qty) * economy.reference_price(product)
        return int(total * float(economy.INVENTORY_LIQUIDATION_RATE))
    return 0


def _agro(db, ph, owner):
    for kind, in db.execute(_q("SELECT kind FROM building_ops WHERE owner=%s", ph), (owner,)).fetchall():
        if any(marker in kind for marker in AGRO_MARKERS):
            return True
    return False


def quote_rate(db, ph, owner, bank_id, product, collateral):
    item = _bank(bank_id)
    if item is None or product not in PRODUCTS or collateral not in COLLATERAL_ADD:
        return None
    risk = min(0.20, missed_months(db, ph, owner) * float(balance.get("BANK_RISK_STEP")))
    raw = float(balance.get("BANK_BASE_RATE_YEAR")) + float(item["rate_add"]) + risk + COLLATERAL_ADD[collateral]
    if item["policy"] == "agro" and _agro(db, ph, owner):
        raw -= 0.01
    lo = float(balance.get("BANK_RATE_MIN_YEAR"))
    hi = float(balance.get("BANK_RATE_MAX_YEAR"))
    rate = min(hi, max(lo, raw))
    return rate


def _term(product):
    if product == "mortgage":
        return int(balance.get("MORTGAGE_TERM_MONTHS"))
    return int(PRODUCTS[product])


def _payment(principal, rate, product, term):
    if product == "credit_line":
        return max(1, int(round(principal * rate / 12.0)))
    monthly = rate / 12.0
    if monthly <= 0:
        return max(1, (principal + term - 1) // term)
    growth = (1.0 + monthly) ** term
    return max(1, int(round(principal * monthly * growth / (growth - 1.0))))


def offers(db, ph, owner=None):
    rows = []
    for item in BANKS:
        for product in item["products"]:
            for collateral in COLLATERAL_ADD:
                rate = quote_rate(db, ph, owner, item["id"], product, collateral) if owner else None
                if rate is None and owner:
                    continue
                if rate is None:
                    rate = min(float(balance.get("BANK_RATE_MAX_YEAR")), max(
                        float(balance.get("BANK_RATE_MIN_YEAR")),
                        float(balance.get("BANK_BASE_RATE_YEAR")) + float(item["rate_add"]) + COLLATERAL_ADD[collateral]))
                value = collateral_value(db, ph, owner, collateral) if owner else 0
                rows.append({
                    "bank": item["id"], "name": item["name"], "policy": item["policy"], "product": product,
                    "collateral": collateral, "rate_year": round(rate, 4), "ltv": item["ltv"],
                    "term_months": _term(product),
                    "limit": int(value * item["ltv"]) if owner else None,
                })
    return {"enabled": bool(balance.get("BANKS_ENABLED")), "offers": rows, "taxes": tax_rates()}


def _remember(db, ph, owner, request_id, result):
    db.execute(_q("INSERT INTO commands(owner,request_id,response) VALUES(%s,%s,%s)", ph),
               (owner, request_id, json.dumps(result, ensure_ascii=False)))


def _replay(db, ph, owner, request_id):
    prev = db.execute(_q("SELECT response FROM commands WHERE owner=%s AND request_id=%s", ph), (owner, request_id)).fetchone()
    if prev:
        return 200, json.loads(prev[0])
    return None


def _open(db, ph, owner, item, product, amount, collateral, value, month, now, request_id):
    rate = quote_rate(db, ph, owner, item["id"], product, collateral)
    term = _term(product)
    payment = _payment(amount, rate, product, term)
    loan_id = uuid.uuid4().hex
    economy.post(db, ph, "npc_loan", "Кредит %s (%s): %d" % (item["name"], product, amount),
                 [(bank_account(item["id"]), -amount), (economy.player_account(owner), amount)], now)
    db.execute(_q(
        "INSERT INTO bank_npc_loans(id,request_id,owner,bank_id,product,principal,balance,rate_ppm,term_months,payment,"
        "collateral,collateral_value,start_month,missed,status) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", ph),
        (loan_id, request_id, owner, item["id"], product, amount, amount, int(round(rate * 1_000_000)),
         term, payment, collateral, int(value), int(month), 0, "active"))
    return {"ok": True, "loan_id": loan_id, "bank": item["id"], "product": product, "amount": amount,
            "payment": payment, "rate_year": round(rate, 4), "term_months": term, "collateral": collateral,
            "balance": economy.balance(db, ph, owner)}


def loan(db, ph, owner, payload, now, month):
    if not balance.get("BANKS_ENABLED"):
        return 409, {"error": "banks_disabled"}
    ensure(db, ph)
    request_id = payload.get("request_id")
    try:
        uuid.UUID(str(request_id))
    except (ValueError, TypeError, AttributeError):
        return 400, {"error": "invalid_request_id"}
    replay = _replay(db, ph, owner, request_id)
    if replay:
        return replay
    item = _bank(payload.get("bank"))
    product = payload.get("product")
    collateral = payload.get("collateral")
    amount = payload.get("amount")
    if item is None:
        return 400, {"error": "unknown_bank"}
    if product not in item["products"]:
        return 400, {"error": "product_not_offered"}
    if collateral not in COLLATERAL_ADD:
        return 400, {"error": "unknown_collateral"}
    if type(amount) is not int or amount < int(balance.get("LOAN_MIN")):
        return 400, {"error": "invalid_amount"}
    value = collateral_value(db, ph, owner, collateral)
    limit = int(value * item["ltv"])
    if amount > limit:
        return 409, {"error": "insufficient_collateral", "limit": limit, "collateral_value": value}
    result = _open(db, ph, owner, item, product, amount, collateral, value, month, now, request_id)
    _remember(db, ph, owner, request_id, result)
    return 201, result


def repay(db, ph, owner, payload, now, month):
    if not balance.get("BANKS_ENABLED"):
        return 409, {"error": "banks_disabled"}
    ensure(db, ph)
    request_id = payload.get("request_id")
    try:
        uuid.UUID(str(request_id))
    except (ValueError, TypeError, AttributeError):
        return 400, {"error": "invalid_request_id"}
    replay = _replay(db, ph, owner, request_id)
    if replay:
        return replay
    loan_id = payload.get("loan_id")
    row = db.execute(_q(
        "SELECT balance,payment,bank_id,status FROM bank_npc_loans WHERE id=%s AND owner=%s", ph), (loan_id, owner)).fetchone()
    if row is None:
        return 404, {"error": "unknown_loan"}
    owed, payment, bank_id, status = int(row[0]), int(row[1]), row[2], row[3]
    if status == "closed" or owed <= 0:
        return 409, {"error": "loan_closed"}
    amount = payload.get("amount", payment)
    if type(amount) is not int or amount <= 0:
        return 400, {"error": "invalid_amount"}
    amount = min(amount, owed)
    cash = economy.balance(db, ph, owner) or 0
    if cash < amount:
        return 402, {"error": "insufficient_funds", "balance": cash, "amount": amount}
    economy.post(db, ph, "npc_loan", "Погашение кредита %s: %d" % (loan_id[:8], amount),
                 [(economy.player_account(owner), -amount), (bank_account(bank_id), amount)], now)
    left = owed - amount
    new_status = "closed" if left <= 0 else status
    db.execute(_q("UPDATE bank_npc_loans SET balance=%s, status=%s, missed=0 WHERE id=%s", ph), (left, new_status, loan_id))
    result = {"ok": True, "loan_id": loan_id, "paid": amount, "balance": left, "status": new_status,
              "wallet": economy.balance(db, ph, owner)}
    _remember(db, ph, owner, request_id, result)
    return 201, result


def loans_of(db, ph, owner):
    ensure(db, ph)
    rows = db.execute(_q(
        "SELECT id,bank_id,product,principal,balance,rate_ppm,term_months,payment,collateral,missed,status "
        "FROM bank_npc_loans WHERE owner=%s ORDER BY id", ph), (owner,)).fetchall()
    return {"loans": [{
        "loan_id": loan_id, "bank": bank_id, "product": product, "principal": int(principal), "balance": int(owed),
        "rate_year": round(int(rate) / 1_000_000, 4), "term_months": int(term), "payment": int(payment),
        "collateral": collateral, "missed": int(missed), "status": status,
        "warning": int(missed) >= int(balance.get("BANK_MISSED_WARN")) and status not in ("closed", "defaulted"),
    } for loan_id, bank_id, product, principal, owed, rate, term, payment, collateral, missed, status in rows]}


def buy_shares(db, ph, owner, payload, now, month):
    if not balance.get("BANKS_ENABLED"):
        return 409, {"error": "banks_disabled"}
    ensure(db, ph)
    request_id = payload.get("request_id")
    try:
        uuid.UUID(str(request_id))
    except (ValueError, TypeError, AttributeError):
        return 400, {"error": "invalid_request_id"}
    replay = _replay(db, ph, owner, request_id)
    if replay:
        return replay
    company = payload.get("company")
    shares = payload.get("shares")
    price = payload.get("price")
    if not isinstance(company, str) or not company or company == owner or company in economy.RESERVED_OWNERS or len(company) > 64:
        return 400, {"error": "invalid_company"}
    if type(shares) is not int or not 1 <= shares <= 1_000_000:
        return 400, {"error": "invalid_shares"}
    if type(price) is not int or not 1 <= price <= 1_000_000_000:
        return 400, {"error": "invalid_price"}
    total = shares * price
    cash = economy.ensure_wallet(db, ph, owner, now)
    if cash < total:
        return 402, {"error": "insufficient_funds", "balance": cash, "cost": total}
    economy.post(db, ph, "shares", "Доля %s: %d x %d" % (company, shares, price),
                 [(economy.player_account(owner), -total), (economy.player_account(company), total)], now)
    db.execute(_q(
        "INSERT INTO company_shares(company,holder,shares,paid) VALUES(%s,%s,%s,%s) "
        "ON CONFLICT(company,holder) DO UPDATE SET shares=company_shares.shares+excluded.shares,"
        "paid=company_shares.paid+excluded.paid", ph), (company, owner, shares, total))
    result = {"ok": True, "company": company, "shares": shares, "paid": total, "balance": economy.balance(db, ph, owner)}
    _remember(db, ph, owner, request_id, result)
    return 201, result


def _service(db, ph, month, now):
    rows = db.execute(
        "SELECT id,owner,bank_id,product,balance,rate_ppm,payment,missed,status,collateral,collateral_value "
        "FROM bank_npc_loans WHERE status NOT IN ('closed','defaulted') ORDER BY id").fetchall()
    warn = int(balance.get("BANK_MISSED_WARN"))
    restructure_at = int(balance.get("BANK_MISSED_RESTRUCTURE"))
    foreclose_at = int(balance.get("BANK_MISSED_FORECLOSE"))
    for loan_id, owner, bank_id, product, owed, rate_ppm, payment, missed, status, collateral, collateral_value_ in rows:
        if db.execute(_q("SELECT 1 FROM bank_npc_charges WHERE loan_id=%s AND month_index=%s", ph), (loan_id, int(month))).fetchone():
            continue
        owed = int(owed)
        rate = int(rate_ppm) / 1_000_000
        interest = int(round(owed * rate / 12.0))
        due = int(payment) if product != "credit_line" else max(interest, 1)
        cash = max(0, economy.balance(db, ph, owner) or 0)
        pay = min(due, cash, owed + interest)
        if pay:
            economy.post(db, ph, "npc_loan", "Платёж %s: %d" % (loan_id[:8], pay),
                         [(economy.player_account(owner), -pay), (bank_account(bank_id), pay)], now)
        interest_paid = min(pay, interest)
        principal_paid = max(0, pay - interest)
        owed = max(0, owed - principal_paid) + max(0, interest - interest_paid)
        if pay >= due and due > 0:
            missed = 0
            if status == "warning":
                status = "active"
        else:
            missed = int(missed) + 1
        if owed <= 0:
            owed = 0
            status = "closed"
        elif missed >= foreclose_at:
            status = "defaulted"
            seize = min(owed, max(0, economy.balance(db, ph, owner) or 0), int(int(collateral_value_) * float(economy.LIQUIDATION_RATE)))
            if seize > 0:
                economy.post(db, ph, "npc_loan", "Взыскание залога %s: %d" % (collateral, seize),
                             [(economy.player_account(owner), -seize), (bank_account(bank_id), seize)], now)
                owed -= seize
        elif missed >= restructure_at and status != "restructured":
            status = "restructured"
            payment = _payment(owed, rate, product, _term(product) + 12)
        elif missed >= warn and status == "active":
            status = "warning"
        db.execute(_q(
            "UPDATE bank_npc_loans SET balance=%s, missed=%s, status=%s, payment=%s WHERE id=%s", ph),
            (owed, missed, status, int(payment), loan_id))
        db.execute(_q("INSERT INTO bank_npc_charges(loan_id,month_index) VALUES(%s,%s)", ph), (loan_id, int(month)))


def _boom(db, ph, month, now):
    if not int(balance.get("CREDIT_BOOM") or 0):
        return
    if db.execute("SELECT 1 FROM bank_marks WHERE mark='credit_boom'").fetchone():
        return
    db.execute("INSERT INTO bank_marks(mark) VALUES('credit_boom')")
    item = _bank("bashkredit")
    amount = int(balance.get("LOAN_MIN"))
    for owner, in db.execute("SELECT DISTINCT owner FROM building_ops ORDER BY owner").fetchall():
        if owner in economy.RESERVED_OWNERS:
            continue
        value = collateral_value(db, ph, owner, "realty")
        if int(value * item["ltv"]) < amount:
            continue
        _open(db, ph, owner, item, "working_capital", amount, "realty", value, month, now, "credit-boom")
        return


def _dividends(db, ph, month, now):
    companies = [row[0] for row in db.execute("SELECT DISTINCT company FROM company_shares ORDER BY company").fetchall()]
    ppm = int(balance.get("DIVIDEND_PAYOUT_PPM"))
    reserve = int(balance.get("DIVIDEND_MIN_CASH"))
    for company in companies:
        if db.execute(_q("SELECT 1 FROM dividend_paid WHERE company=%s AND month_index=%s", ph), (company, int(month))).fetchone():
            continue
        cash = max(0, economy.balance(db, ph, company) or 0)
        payout = max(0, cash - reserve) * ppm // 1000
        holders = db.execute(_q("SELECT holder,shares FROM company_shares WHERE company=%s ORDER BY holder", ph), (company,)).fetchall()
        weights = {holder: int(shares) for holder, shares in holders if holder != company and int(shares) > 0}
        whole = sum(weights.values())
        paid = 0
        if payout > 0 and whole > 0:
            parts = {holder: payout * shares // whole for holder, shares in weights.items()}
            left = payout - sum(parts.values())
            order = sorted(weights, key=lambda holder: (-(payout * weights[holder] % whole), holder))
            for holder in order:
                if left <= 0:
                    break
                parts[holder] += 1
                left -= 1
            parts = {holder: part for holder, part in parts.items() if part}
            paid = sum(parts.values())
            if paid:
                entries = [(economy.player_account(company), -paid)]
                for holder, part in sorted(parts.items()):
                    entries.append((economy.player_account(holder), part))
                economy.post(db, ph, "dividend", "Дивиденд %s: %d" % (company, paid), entries, now)
        db.execute(_q("INSERT INTO dividend_paid(company,month_index,amount) VALUES(%s,%s,%s)", ph), (company, int(month), paid))


def _extras(db, ph, month, now):
    if not balance.get("TAX_EXTRAS_ENABLED"):
        return
    rates = tax_rates()
    rows = db.execute(_q(
        "SELECT owner,revenue,buildings FROM company_reports WHERE month_index=%s ORDER BY owner", ph), (int(month),)).fetchall()
    for owner, revenue, _buildings in rows:
        if owner in economy.RESERVED_OWNERS:
            continue
        if db.execute(_q("SELECT 1 FROM tax_extra_posted WHERE owner=%s AND month_index=%s", ph), (owner, int(month))).fetchone():
            continue
        land = int(bank.appraisal(db, ph, owner) * rates["land"] / 12.0)
        jobs = 0
        for kind, in db.execute(_q("SELECT kind FROM building_ops WHERE owner=%s", ph), (owner,)).fetchall():
            jobs += economy.kind_jobs(kind)
        payroll = int(jobs * int(balance.get("BASE_WAGE")) * rates["payroll"])
        sector = int(max(0, int(revenue)) * rates["sector_fee"])
        due = land + payroll + sector
        cash = max(0, economy.balance(db, ph, owner) or 0)
        pay = min(due, cash)
        if pay:
            economy.post(db, ph, "tax_extra", "Земля, зарплаты и сбор %s: %d" % (owner, pay),
                         [(economy.player_account(owner), -pay), (economy.player_account(economy.CITY), pay)], now)
        db.execute(_q(
            "INSERT INTO tax_extra_posted(owner,month_index,land_tax,payroll_tax,sector_fee,paid) VALUES(%s,%s,%s,%s,%s,%s)", ph),
            (owner, int(month), land, payroll, sector, pay))


def monthly(db, ph, month, now):
    banks_on = bool(balance.get("BANKS_ENABLED"))
    extras_on = bool(balance.get("TAX_EXTRAS_ENABLED"))
    if not banks_on and not extras_on and not inflation.enabled():
        return {"enabled": False}
    ensure(db, ph)
    if banks_on:
        _service(db, ph, month, now)
        _boom(db, ph, month, now)
        _dividends(db, ph, month, now)
    if extras_on:
        _extras(db, ph, month, now)
    if inflation.enabled():
        inflation.monthly(db, ph, month, now)
    return {"enabled": True}
