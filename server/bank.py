"""Bank: one revolving loan per company. Shared by SQLite and PostgreSQL (`ph` = SQL placeholder).

The bank only creates money against collateral (the company's buildings); interest and repayments move money back to it.
Operating rules that touch production (monthly interest, bankruptcy waterfall) live in production.py and call this module.
"""
import economy


def _q(sql, ph):
    return sql.replace("%s", ph)


def appraisal(db, ph, owner):
    """Collateral value: construction cost of all buildings of the company."""
    return sum(economy.BUILD_COST.get(kind, 0) for kind, in db.execute(_q("SELECT kind FROM building_ops WHERE owner=%s", ph), (owner,)).fetchall())


def company_age(db, ph, owner):
    """How many completed game months the company has operated, counting the month it opened."""
    started = db.execute(_q("SELECT MIN(start_month) FROM building_ops WHERE owner=%s", ph), (owner,)).fetchone()
    if not started or started[0] is None:
        return 0
    row = db.execute("SELECT processed_through FROM world_state WHERE id=1").fetchone()
    if row is None:
        return 0
    return max(0, int(row[0]) - int(started[0]) + 1)


def trailing_revenue(db, ph, owner):
    rows = db.execute(_q("SELECT revenue FROM company_reports WHERE owner=%s ORDER BY month_index DESC LIMIT %s", ph),
                      (owner, economy.LOAN_REVENUE_MONTHS)).fetchall()
    if not rows:
        return 0
    return sum(int(row[0]) for row in rows) // len(rows)


def limit_detail(db, ph, owner):
    """Collateral limit that grows with age and confirmed revenue. ``limit`` is what the bank will lend."""
    worth = appraisal(db, ph, owner)
    full = min(economy.LOAN_MAX, int(worth * economy.LOAN_LTV))
    floor = min(full, int(worth * economy.LOAN_NEW_LTV))
    age = company_age(db, ph, owner)
    revenue = trailing_revenue(db, ph, owner)
    ramp = economy.LOAN_RAMP_MONTHS
    age_k = 1.0 if ramp <= 0 else min(1.0, age / float(ramp))
    proof = economy.LOAN_REVENUE_PROOF
    rev_k = 1.0 if proof <= 0 else min(1.0, revenue / float(proof))
    maturity = age_k * rev_k
    amount = min(economy.LOAN_MAX, int(round(floor + (full - floor) * maturity)))
    if worth <= 0:
        reason = "Нет залога: кредит открывается после строительства."
    elif maturity >= 0.999:
        reason = "Полный лимит: %d%% стоимости зданий." % int(round(economy.LOAN_LTV * 100))
    else:
        reason = ("Новичок: сейчас %d%% залога. Полные %d%% — после %d мес. работы и выручки от %d ₽/мес. "
                  "Компании %d мес., средняя выручка %d ₽.") % (
                      int(round(economy.LOAN_NEW_LTV * 100)), int(round(economy.LOAN_LTV * 100)),
                      ramp, proof, age, revenue)
    return {"limit": amount, "full_limit": full, "floor_limit": floor, "age_months": age,
            "revenue_avg": revenue, "maturity": round(maturity, 3), "limit_reason": reason}


def limit(db, ph, owner):
    return limit_detail(db, ph, owner)["limit"]


def balance(db, ph, owner):
    row = db.execute(_q("SELECT balance FROM loans WHERE owner=%s", ph), (owner,)).fetchone()
    return int(row[0]) if row else 0


def _change(db, ph, owner, d_balance=0, d_interest=0, d_taken=0, d_repaid=0):
    db.execute(_q("INSERT INTO loans(owner,balance,interest_paid,taken_total,repaid_total) VALUES(%s,%s,%s,%s,%s) ON CONFLICT(owner) DO UPDATE SET "
                  "balance=loans.balance+excluded.balance,interest_paid=loans.interest_paid+excluded.interest_paid,"
                  "taken_total=loans.taken_total+excluded.taken_total,repaid_total=loans.repaid_total+excluded.repaid_total", ph),
               (owner, d_balance, d_interest, d_taken, d_repaid))


def monthly_interest(loan_balance):
    return int(loan_balance * economy.LOAN_INTEREST)


def view(db, ph, owner, in_default=False):
    bal = balance(db, ph, owner)
    detail = limit_detail(db, ph, owner)
    lim = detail["limit"]
    return {"balance": bal, "limit": lim, "available": 0 if in_default else max(0, lim - bal), "interest_rate": economy.LOAN_INTEREST,
            "monthly_interest": monthly_interest(bal), "min": economy.LOAN_MIN, "in_default": bool(in_default),
            "full_limit": detail["full_limit"], "age_months": detail["age_months"], "revenue_avg": detail["revenue_avg"],
            "maturity": detail["maturity"], "limit_reason": detail["limit_reason"]}


def take(db, ph, owner, amount, now, in_default):
    if type(amount) is not int or amount < economy.LOAN_MIN or amount > economy.LOAN_MAX:
        return 400, {"error": "invalid_amount", "min": economy.LOAN_MIN, "max": economy.LOAN_MAX}
    if in_default:
        return 409, {"error": "in_default"}
    lim, bal = limit(db, ph, owner), balance(db, ph, owner)
    if amount > lim - bal:
        return 409, {"error": "limit_exceeded", "limit": lim, "available": max(0, lim - bal)}
    economy.ensure_wallet(db, ph, owner, now)
    economy.post(db, ph, "loan", "Кредит: получено %d" % amount, [(economy.BANK, -amount), (economy.player_account(owner), amount)], now)
    _change(db, ph, owner, d_balance=amount, d_taken=amount)
    return 201, {"ok": True}


def repay(db, ph, owner, amount, now):
    bal = balance(db, ph, owner)
    cash = economy.balance(db, ph, owner) or 0
    if bal <= 0:
        return 409, {"error": "no_loan"}
    if amount is None:
        amount = min(bal, cash)
    if type(amount) is not int or amount <= 0:
        return 400, {"error": "invalid_amount"}
    if amount > bal:
        amount = bal
    if amount > cash:
        return 409, {"error": "insufficient_funds", "balance": cash}
    economy.post(db, ph, "loan", "Кредит: погашено %d" % amount, [(economy.player_account(owner), -amount), (economy.BANK, amount)], now)
    _change(db, ph, owner, d_balance=-amount, d_repaid=amount)
    return 201, {"ok": True, "repaid": amount}


def capitalize(db, ph, owner, unpaid_interest):
    """Interest that could not be paid is added to the loan."""
    if unpaid_interest > 0:
        _change(db, ph, owner, d_balance=unpaid_interest)


def paid_interest(db, ph, owner, amount):
    if amount > 0:
        _change(db, ph, owner, d_interest=amount)


def write_off(db, ph, owner, now=None):
    """Bankruptcy: whatever is still owed to the bank is lost. Returns the written-off amount.

    The loan money was created by the bank (system:bank went negative) and has been spent, so the loss would stay in the ledger
    as a permanent negative bank balance without any loan behind it. The Republic's treasury covers the loss instead: system:bank
    again reflects only live loans and the loss is visible on system:treasury (the money supply that was issued to the players).
    """
    bal = balance(db, ph, owner)
    if bal > 0:
        _change(db, ph, owner, d_balance=-bal)
        if now is not None:
            economy.post(db, ph, "loan", "Списание безнадёжного кредита, потери банка покрывает казна: %d" % bal,
                         [(economy.TREASURY, -bal), (economy.BANK, bal)], now)
    return bal
