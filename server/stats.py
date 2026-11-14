"""Read-only company leaderboard and private activity feed on SQLite or PostgreSQL.

Caller owns DB lifetime. No wallet creation, economy advance, DDL or mutation.
"""
import economy
import npc

SORTS = ("networth", "income", "buildings")
PAGE_SIZE = 50


def _sql(query, ph):
    return query.replace("%s", ph)


def _is_company(owner):
    return (isinstance(owner, str) and bool(owner) and owner != economy.CITY
            and not owner.startswith(("system:", "player:")))


def _display(owner):
    return npc.NAMES.get(owner, owner[4:] if owner.startswith("npc:") else owner)


def _last_reports(db, table):
    query = ("SELECT r.owner,r.revenue,r.profit FROM " + table + " r "
             "JOIN (SELECT owner,MAX(month_index) AS latest FROM " + table +
             " GROUP BY owner) m ON m.owner=r.owner AND m.latest=r.month_index")
    return {owner: (int(revenue), int(profit)) for owner, revenue, profit in db.execute(query).fetchall()}


def leaderboard(db, ph, owner, by="networth"):
    if by not in SORTS:
        return 400, {"error": "invalid_sort"}
    companies = {}

    def ensure(key):
        if not _is_company(key):
            return None
        return companies.setdefault(key, {"balance": 0, "appraisal": 0, "debt": 0,
                                          "buildings": 0, "income": 0, "profit": 0})

    ensure(owner)
    for account, balance in db.execute("SELECT account,balance FROM wallets WHERE account LIKE 'player:%'").fetchall():
        if account.startswith("player:"):
            item = ensure(account[7:])
            if item is not None:
                item["balance"] = int(balance)
    for key, kind in db.execute("SELECT owner,kind FROM building_ops").fetchall():
        item = ensure(key)
        if item is not None:
            item["buildings"] += 1
            item["appraisal"] += int(economy.BUILD_COST.get(kind, 0))
    for key, loan in db.execute("SELECT owner,balance FROM loans").fetchall():
        item = ensure(key)
        if item is not None:
            item["debt"] = int(loan)
    reports = _last_reports(db, "monthly_reports")
    reports.update(_last_reports(db, "company_reports"))  # newer normalized model wins
    for key, (revenue, profit) in reports.items():
        item = ensure(key)
        if item is not None:
            item["income"], item["profit"] = revenue, profit
    for key in npc.NAMES:
        ensure(key)
    items = []
    for key, values in companies.items():
        items.append({"owner": key, "name": _display(key), "npc": npc.is_npc(key),
                      "networth": values["balance"] + values["appraisal"] - values["debt"], **values})
    items.sort(key=lambda item: (-item[by], item["owner"].casefold(), item["owner"]))
    for index, item in enumerate(items):
        item["rank"] = index + 1
    return 200, {"ok": True, "by": by, "top": items[:20],
                 "me": next((item for item in items if item["owner"] == owner), None),
                 "total": len(items)}


def _month_time(db, month):
    row = db.execute("SELECT epoch,month_seconds,base_index FROM world_clock WHERE id=1").fetchone()
    if row is None:
        return 0
    epoch, seconds, base = map(int, row)
    return max(0, epoch + (int(month) - base + 1) * seconds)


def feed(db, ph, owner, after=0):
    """Paginate the existing histories without creating a new feed table.

    The numeric cursor is an offset in a deterministic chronological projection.
    A fresh open must request after=0; it is not an immutable cross-source event ID.
    """
    if type(after) is not int or not 0 <= after <= 2_000_000_000:
        return 400, {"error": "invalid_cursor"}
    events = []

    def add(source, ident, kind, title, when, amount=0, month=None):
        events.append({"id": "%s:%s" % (source, ident), "kind": kind,
                       "title": title, "time": int(when), "amount": int(amount),
                       "month_index": int(month) if month is not None else None})

    rows = db.execute(_sql(
        "SELECT t.id,t.kind,t.memo,t.created,e.amount FROM ledger_entries e "
        "JOIN ledger_tx t ON t.id=e.tx_id WHERE e.account=%s", ph),
        (economy.player_account(owner),)).fetchall()
    for txid, kind, memo, created, amount in rows:
        kind, memo = str(kind), str(memo)
        if kind == "start_capital":
            continue
        if kind == "monthly" and not memo.startswith("Проценты по кредиту"):
            continue  # report and tax tables give structured monthly details
        if kind == "build":
            label, title = "build", memo
        elif kind == "sale":
            label, title = "sale", memo
        elif kind == "liquidation":
            label, title = "bankruptcy", memo
        elif kind == "loan" or "кредит" in memo.casefold():
            label, title = "loan", memo
        elif kind == "city":
            label, title = ("mayor_salary" if ("зарплат" in memo.casefold() or
                            "преми" in memo.casefold()) else "city"), memo
        elif "налог" in memo.casefold():
            label, title = "tax", memo
        else:
            continue
        add("ledger", txid, label, title, created, amount)

    older = db.execute(_sql(
        "SELECT month_index,revenue,profit FROM monthly_reports WHERE owner=%s ORDER BY month_index", ph),
        (owner,)).fetchall()
    newer = db.execute(_sql(
        "SELECT month_index,revenue,profit FROM company_reports WHERE owner=%s ORDER BY month_index", ph),
        (owner,)).fetchall()
    reports = {int(m): (int(r), int(p)) for m, r, p in older}
    reports.update({int(m): (int(r), int(p)) for m, r, p in newer})
    for month, (revenue, profit) in reports.items():
        add("report", month, "monthly_result",
            "Итоги месяца: прибыль %s ₽, выручка %s ₽" % (profit, revenue),
            _month_time(db, month), profit, month)

    taxes = db.execute(_sql(
        "SELECT month_index,vat,profit_tax,property_tax,paid "
        "FROM company_taxes WHERE owner=%s ORDER BY month_index", ph),
        (owner,)).fetchall()
    for month, vat, profit_tax, property_tax, paid in taxes:
        if int(paid):
            add("tax", month, "tax",
                "Уплачены налоги: НДС %s ₽, прибыль %s ₽, имущество %s ₽" %
                (vat, profit_tax, property_tax), _month_time(db, month), -int(paid), month)

    elections = db.execute(_sql(
        "SELECT election FROM election_candidates WHERE candidate=%s ORDER BY election", ph),
        (owner,)).fetchall()
    for (election,) in elections:
        election = int(election)
        add("candidacy", election, "election_candidacy", "Участие в выборах мэра",
            _month_time(db, election - 4), 0, election)
        outcome = db.execute(_sql(
            "SELECT winner,month_index FROM election_results WHERE election=%s", ph),
            (election,)).fetchone()
        if outcome:
            winner, month = outcome
            add("election", election, "election_result",
                "Выборы мэра: победа" if winner == owner else "Выборы мэра: не избран",
                _month_time(db, month), 0, month)

    # Bankruptcy can leave no liquidation ledger entry (zero remaining assets).
    # company_status is the authoritative evidence of that event.
    status = db.execute(_sql(
        "SELECT last_bankruptcy_month FROM company_status WHERE owner=%s", ph),
        (owner,)).fetchone()
    if status is not None and status[0] is not None:
        month = int(status[0])
        add("bankruptcy", month, "bankruptcy", "Банкротство компании",
            _month_time(db, month), 0, month)

    events.sort(key=lambda event: (event["time"], event["id"]))
    # First page is the newest activity, not the oldest history.
    # Subsequent after=N calls fetch items appended after the returned cursor.
    page = events[-PAGE_SIZE:] if after == 0 else events[after:after + PAGE_SIZE]
    cursor = len(events) if after == 0 else after + len(page)
    return 200, {"ok": True, "events": page, "cursor": cursor,
                 "has_more": cursor < len(events), "total": len(events)}
