"""Целочисленная симуляция кредитов, процентов, просрочек и налогов (GDD 34). Только проект, balance: draft."""
from __future__ import annotations

import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data" / "credit_proposed"


def load():
    return (json.loads((DATA / "parameters.json").read_text(encoding="utf-8")),
            json.loads((DATA / "scenarios.json").read_text(encoding="utf-8")))


def rate_bp_month(rating, p):
    return (p["key_rate_bp_year"] + p["spread_bp_year"][rating]) // 12


def rating_letter(score, p):
    b = p["rating_bounds"]
    return "A" if score >= b["A"] else "B" if score >= b["B"] else "C" if score >= b["C"] else "D"


def schedule(principal, term, rate_bp):
    """Дифференцированные платежи: равная часть долга плюс проценты на остаток."""
    part = principal // term
    remaining, rows = principal, []
    for m in range(1, term + 1):
        body = remaining if m == term else part
        interest = remaining * rate_bp // 10000
        rows.append((m, body, interest))
        remaining -= body
    return rows


def taxes(profit_before_tax, wages, assets, p):
    profit_tax = max(0, profit_before_tax) * p["profit_tax_bp"] // 10000
    return profit_tax + assets * p["property_tax_bp_month"] // 10000 + wages * p["payroll_tax_bp"] // 10000


def run(variant, scn, p):
    base, exp, loan = scn["base"], scn["expansion"], scn["loan"]
    cash = 0
    debt_rows = []
    profit_total = interest_total = tax_total = arrears_months = seized = 0
    arrears = 0
    assets = base["assets"]
    expanded = variant["id"] != "no_expansion"
    if expanded:
        assets += exp["cost"]
        if variant.get("cash"):
            profit_total -= exp["cost"]
        else:
            debt_rows = schedule(loan["principal"], loan["term_months"], rate_bp_month(loan["rating"], p))
    for m in range(1, scn["months"] + 1):
        gross = base["profit_before_tax_month"] + (exp["extra_profit_month"] if expanded else 0)
        if m in variant.get("shock_months", []):
            gross = gross * variant["shock_factor_bp"] // 10000
        due_body = due_interest = 0
        if debt_rows and m <= len(debt_rows):
            _, due_body, due_interest = debt_rows[m - 1]
        due = due_body + due_interest + arrears
        pay_capacity = max(0, gross + cash)
        paid = min(due, pay_capacity)
        late = due - paid
        arrears = late + late * p["arrears_penalty_bp_month"] // 10000 if late else 0
        arrears_months = arrears_months + 1 if late else 0
        if arrears_months >= p["seize_after_arrears_months"] and not seized:
            seized = m
            assets -= exp["cost"] * p["ltv_bp"]["building"] // 10000
        interest_total += min(due_interest, paid)
        tax = min(taxes(gross - due_interest, base["wages_month"], assets, p), max(0, gross + cash - paid))
        tax_total += tax
        net = gross - paid - tax
        cash += net
        profit_total += net
    return {"id": variant["id"], "net_cash_end": profit_total, "interest_total": interest_total,
            "tax_total": tax_total, "arrears_end": arrears, "seized_month": seized}


def run_all():
    p, s = load()
    return {"variants": [run(v, s, p) for v in s["variants"]],
            "rates_bp_month": {k: rate_bp_month(k, p) for k in p["spread_bp_year"]}}


def rebuild_golden():
    out = run_all()
    (DATA / "golden.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return out
