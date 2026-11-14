"""Owners spend part of after-tax operating profit. Shared by SQLite and PostgreSQL.

The posting is player -> system:market (kind ``owner_spend``). It runs after contract settlement,
so a buyer still has the cash to pay a delivery. The city does not consume. A company that failed
to pay its bills this month keeps the cash. See docs/OWNER_SPENDING.md.
"""
import economy


def _q(sql, ph):
    return sql.replace("%s", ph)


def settle(db, ph, month, companies, bankrupt, now):
    """Spend from companies that cleared the month. Returns {owner: amount}."""
    if not economy.OWNER_SPEND_ENABLED:
        return {}
    bankrupt = set(bankrupt or ())
    spent = {}
    for owner, c in sorted(companies.items()):
        if owner == economy.CITY or owner in bankrupt:
            continue
        if int(c.get("unpaid_sum", 0)) > 0:
            continue
        base = int(c.get("after_tax", 0))
        if base <= 0:
            continue
        want = int(base * economy.OWNER_SPEND_SHARE)
        reserve = int(c.get("reserve", 0))
        cash = economy.balance(db, ph, owner) or 0
        amount = min(want, max(0, int(cash) - reserve))
        if amount <= 0:
            continue
        economy.post(db, ph, "owner_spend", "Личные траты владельца: %d" % amount,
                     [(economy.player_account(owner), -amount), (economy.MARKET_ACCOUNT, amount)], now)
        db.execute(_q("INSERT INTO eco_owner_spend(owner,month_index,amount) VALUES(%s,%s,%s)", ph),
                   (owner, month, amount))
        spent[owner] = amount
    return spent


def last_for(db, ph, owner, limit=6):
    rows = db.execute(_q("SELECT month_index,amount FROM eco_owner_spend WHERE owner=%s ORDER BY month_index DESC LIMIT %s", ph),
                      (owner, limit)).fetchall()
    return {int(month): int(amount) for month, amount in rows}
