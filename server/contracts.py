"""Direct contracts between players for honey, oil and goods.

Offers live on a public board. Once accepted, a contract delivers every game month
inside ``production.step_month`` *before* that product is cleared on the open market:

  * the supplier keeps what their own factories need (own supply first);
  * the rest of stock, then output, is handed to buyers in contract-id order;
  * a factory buyer therefore consumes the delivery as its own input;
  * anything still unsold is offered to the market, so contracted volume leaves
    both supply and the buyer's residual demand.

Money moves in balanced player-to-player postings after the monthly market settlement.
A party that cannot pay keeps the debt on ``trade_debts`` (owed to the counterparty,
not to the market account). A new unpaid contract bill counts as a missed month, the
same way unpaid wages do. See docs/CONTRACTS.md.

Shared by SQLite and PostgreSQL. Every function runs inside the caller's transaction.
"""
import uuid

import economy


def _q(sql, ph):
    return sql.replace("%s", ph)


def _human(owner):
    return type(owner) is str and bool(owner) and owner not in economy.RESERVED_OWNERS and ":" not in owner


def price_bounds(product):
    """Inclusive integer price range: 50–200% of the reference price."""
    ref = int(economy.MARKET[product]["reference_price"])
    lo = max(1, int(round(ref * economy.CONTRACT_PRICE_MIN_K)))
    hi = max(lo, int(round(ref * economy.CONTRACT_PRICE_MAX_K)))
    return lo, hi


def free_units(produced, stock, own_need):
    """Units a supplier can ship after reserving their own factories' need."""
    produced, stock = max(int(produced), 0), max(int(stock), 0)
    protected = min(max(int(own_need), 0), produced + stock)
    return produced + stock - protected


def plan_deliveries(orders, available):
    """Allocate scarce goods. ``orders`` is (id, supplier, qty) already in priority order.

    Returns one dict per order: delivered, shortfall. Does not mutate ``available``.
    """
    pool = {k: int(v) for k, v in available.items()}
    out = []
    for cid, supplier, qty in orders:
        have = pool.get(supplier, 0)
        give = max(0, min(int(qty), have))
        pool[supplier] = have - give
        out.append({"id": cid, "delivered": give, "shortfall": int(qty) - give})
    return out


def _count(db, ph, sql, params):
    return int(db.execute(_q(sql, ph), params).fetchone()[0])


def _active_count(db, ph, owner):
    return _count(db, ph, "SELECT COUNT(*) FROM trade_contracts WHERE status='active' AND (supplier=%s OR buyer=%s)", (owner, owner))


def _cash(db, ph, owner):
    value = economy.balance(db, ph, owner)
    return 0 if value is None else int(value)


def _offer_row(row):
    oid, supplier, product, qty, price, term, penalty, status, created_month = row
    lo, hi = price_bounds(product)
    return {"id": oid, "supplier": supplier, "product": product, "name": economy.MARKET[product]["name"],
            "qty": int(qty), "price": int(price), "term_months": int(term), "penalty": int(penalty),
            "status": status, "created_month": int(created_month), "min_price": lo, "max_price": hi}


def _contract_public(row, month, role, last):
    cid, _offer, supplier, buyer, product, qty, price, penalty, start_month, end_month, status, reason, _created = row
    return {"id": cid, "role": role, "supplier": supplier, "buyer": buyer, "counterparty": buyer if role == "supplier" else supplier,
            "product": product, "name": economy.MARKET[product]["name"], "qty": int(qty), "price": int(price),
            "penalty": int(penalty), "start_month": int(start_month), "end_month": int(end_month), "status": status,
            "closed_reason": reason or "", "months_left": max(0, int(end_month) - int(month) + 1) if status == "active" else 0,
            "cancel_fee": int(penalty) * int(qty), "last": last}


def offer(db, ph, owner, payload, month, now):
    """POST /contracts/offer. Returns (http status, body)."""
    if not _human(owner):
        return 403, {"error": "npc_forbidden"}
    product = payload.get("product")
    if product not in economy.CONTRACT_PRODUCTS:
        return 400, {"error": "invalid_product"}
    qty, price = payload.get("qty"), payload.get("price")
    term = payload.get("term_months", payload.get("term"))
    penalty = payload.get("penalty")
    if type(qty) is not int or not economy.CONTRACT_QTY_MIN <= qty <= economy.CONTRACT_QTY_MAX:
        return 400, {"error": "invalid_qty"}
    lo, hi = price_bounds(product)
    ref = economy.MARKET[product]["reference_price"]
    if type(price) is not int or not lo <= price <= hi:
        return 400, {"error": "price_out_of_range", "min_price": lo, "max_price": hi, "reference_price": ref}
    if type(term) is not int or not economy.CONTRACT_TERM_MIN <= term <= economy.CONTRACT_TERM_MAX:
        return 400, {"error": "invalid_term"}
    if type(penalty) is not int or penalty < 0 or penalty > price:
        return 400, {"error": "invalid_penalty", "max_penalty": price if type(price) is int else 0}
    if _count(db, ph, "SELECT COUNT(*) FROM trade_offers WHERE supplier=%s AND status='open'", (owner,)) >= economy.CONTRACT_MAX_OPEN:
        return 409, {"error": "too_many_offers"}
    oid = uuid.uuid4().hex
    db.execute(_q("INSERT INTO trade_offers(id,supplier,product,qty,price,term_months,penalty,status,created_month,created) "
                  "VALUES(%s,%s,%s,%s,%s,%s,%s,'open',%s,%s)", ph),
               (oid, owner, product, qty, price, term, penalty, month, now))
    economy.ensure_wallet(db, ph, owner, now)
    row = (oid, owner, product, qty, price, term, penalty, "open", month)
    return 201, {"ok": True, "offer": _offer_row(row), "balance": economy.balance(db, ph, owner)}


def accept(db, ph, owner, payload, month, now):
    """POST /contracts/accept."""
    if not _human(owner):
        return 403, {"error": "npc_forbidden"}
    offer_id = payload.get("offer_id")
    if type(offer_id) is not str or not 8 <= len(offer_id) <= 64:
        return 400, {"error": "invalid_offer"}
    row = db.execute(_q("SELECT id,supplier,product,qty,price,term_months,penalty,status FROM trade_offers WHERE id=%s", ph), (offer_id,)).fetchone()
    if row is None:
        return 404, {"error": "not_found"}
    oid, supplier, product, qty, price, term, penalty, status = row
    if status != "open":
        return 409, {"error": "not_open"}
    if supplier == owner:
        return 403, {"error": "self_contract"}
    if not _human(supplier):
        return 403, {"error": "npc_forbidden"}
    import regions
    if regions.home_region(db, ph, owner) != regions.home_region(db, ph, supplier):
        return 409, {"error": "different_city"}      # a contract has no delivery time; goods between cities go through the market (docs/CITY_ECONOMY.md)
    if _active_count(db, ph, owner) >= economy.CONTRACT_MAX_ACTIVE or _active_count(db, ph, supplier) >= economy.CONTRACT_MAX_ACTIVE:
        return 409, {"error": "too_many_contracts"}
    cid = uuid.uuid4().hex
    end_month = int(month) + int(term) - 1
    db.execute(_q("INSERT INTO trade_contracts(id,offer_id,supplier,buyer,product,qty,price,penalty,start_month,end_month,status,closed_reason,created) "
                  "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'active','',%s)", ph),
               (cid, oid, supplier, owner, product, int(qty), int(price), int(penalty), month, end_month, now))
    db.execute(_q("UPDATE trade_offers SET status='accepted' WHERE id=%s", ph), (oid,))
    economy.ensure_wallet(db, ph, owner, now)
    economy.ensure_wallet(db, ph, supplier, now)
    body = {"id": cid, "offer_id": oid, "supplier": supplier, "buyer": owner, "product": product,
            "name": economy.MARKET[product]["name"], "qty": int(qty), "price": int(price), "penalty": int(penalty),
            "start_month": int(month), "end_month": end_month, "status": "active", "months_left": int(term)}
    return 201, {"ok": True, "contract": body, "balance": economy.balance(db, ph, owner)}


def cancel(db, ph, owner, payload, month, now):
    """POST /contracts/cancel — withdraw an open offer or pay the fee to leave an active contract."""
    if not _human(owner):
        return 403, {"error": "npc_forbidden"}
    offer_id, contract_id = payload.get("offer_id"), payload.get("contract_id")
    if type(offer_id) is str and type(contract_id) is str:
        return 400, {"error": "invalid_request"}
    if type(offer_id) is str:
        if not 8 <= len(offer_id) <= 64:
            return 400, {"error": "invalid_offer"}
        row = db.execute(_q("SELECT supplier,status FROM trade_offers WHERE id=%s", ph), (offer_id,)).fetchone()
        if row is None:
            return 404, {"error": "not_found"}
        if row[0] != owner:
            return 403, {"error": "not_owner"}
        if row[1] != "open":
            return 409, {"error": "not_open"}
        db.execute(_q("UPDATE trade_offers SET status='withdrawn' WHERE id=%s", ph), (offer_id,))
        return 201, {"ok": True, "offer_id": offer_id, "status": "withdrawn", "balance": economy.balance(db, ph, owner)}
    if type(contract_id) is not str or not 8 <= len(contract_id) <= 64:
        return 400, {"error": "invalid_request"}
    row = db.execute(_q("SELECT supplier,buyer,qty,penalty,status FROM trade_contracts WHERE id=%s", ph), (contract_id,)).fetchone()
    if row is None:
        return 404, {"error": "not_found"}
    supplier, buyer, qty, penalty, status = row
    if owner not in (supplier, buyer):
        return 403, {"error": "not_party"}
    if status != "active":
        return 409, {"error": "invalid_state"}
    fee = int(penalty) * int(qty)
    other = buyer if owner == supplier else supplier
    if fee:
        cash = _cash(db, ph, owner)
        if cash < fee:
            return 402, {"error": "insufficient_funds", "cost": fee, "balance": cash}
        economy.post(db, ph, "contract_cancel", "Расторжение контракта %s" % contract_id[:8],
                     [(economy.player_account(owner), -fee), (economy.player_account(other), fee)], now)
    db.execute(_q("UPDATE trade_contracts SET status='cancelled', closed_reason=%s WHERE id=%s", ph), (owner, contract_id))
    return 201, {"ok": True, "contract_id": contract_id, "status": "cancelled", "fee": fee, "balance": economy.balance(db, ph, owner), "month": month}


def view(db, ph, owner, month):
    """GET /contracts."""
    products = []
    for product in economy.CONTRACT_PRODUCTS:
        lo, hi = price_bounds(product)
        ref = economy.MARKET[product]["reference_price"]
        products.append({"id": product, "name": economy.MARKET[product]["name"], "reference_price": ref, "min_price": lo, "max_price": hi})
    offers = [_offer_row(r) for r in db.execute(
        "SELECT id,supplier,product,qty,price,term_months,penalty,status,created_month FROM trade_offers WHERE status='open' ORDER BY created,id").fetchall()]
    mine_rows = db.execute(_q(
        "SELECT id,offer_id,supplier,buyer,product,qty,price,penalty,start_month,end_month,status,closed_reason,created FROM trade_contracts "
        "WHERE supplier=%s OR buyer=%s ORDER BY created DESC,id DESC LIMIT 30", ph), (owner, owner)).fetchall()
    last = {}
    if mine_rows:
        ids = [r[0] for r in mine_rows]
        marks = ",".join([ph] * len(ids))
        sql = ("SELECT contract_id,month_index,delivered,shortfall,paid,penalty_paid FROM trade_deliveries WHERE contract_id IN (" + marks + ")")
        for cid, m, delivered, shortfall, paid, penalty_paid in db.execute(sql, tuple(ids)).fetchall():
            prev = last.get(cid)
            if prev is None or int(m) >= prev["month"]:
                last[cid] = {"month": int(m), "delivered": int(delivered), "shortfall": int(shortfall), "paid": int(paid), "penalty_paid": int(penalty_paid)}
    mine = [_contract_public(r, month, "supplier" if r[2] == owner else "buyer", last.get(r[0])) for r in mine_rows]
    owed = _count(db, ph, "SELECT COALESCE(SUM(amount),0) FROM trade_debts WHERE debtor=%s", (owner,))
    receivable = _count(db, ph, "SELECT COALESCE(SUM(amount),0) FROM trade_debts WHERE creditor=%s", (owner,))
    return {"ok": True, "month_index": int(month), "products": products,
            "limits": {"max_active": economy.CONTRACT_MAX_ACTIVE, "max_open": economy.CONTRACT_MAX_OPEN,
                       "qty": [economy.CONTRACT_QTY_MIN, economy.CONTRACT_QTY_MAX],
                       "term_months": [economy.CONTRACT_TERM_MIN, economy.CONTRACT_TERM_MAX],
                       "price_min_k": economy.CONTRACT_PRICE_MIN_K, "price_max_k": economy.CONTRACT_PRICE_MAX_K},
            "offers": offers, "mine": mine, "debts": {"owed": owed, "receivable": receivable},
            "active": _active_count(db, ph, owner),
            "open_offers": _count(db, ph, "SELECT COUNT(*) FROM trade_offers WHERE supplier=%s AND status='open'", (owner,))}


def _shell(cash):
    return {"buildings": [], "maint": 0, "jobs": 0, "capacity": 0, "stock": {}, "needs": {}, "got": {}, "need_ext": {},
            "revenue": 0, "input_cost": 0, "rev_by": {}, "in_by": {}, "cash": cash, "distress": False}


def _ensure_company(db, ph, companies, produced_map, owner):
    if owner in companies:
        return companies[owner]
    shell = _shell(_cash(db, ph, owner))
    for product, qty in db.execute(_q("SELECT product,qty FROM inventory WHERE owner=%s", ph), (owner,)).fetchall():
        if int(qty) > 0 and product in economy.MARKET:
            shell["stock"][product] = int(qty)
    companies[owner] = shell
    produced_map.setdefault(owner, 0)
    return shell


def deliver(db, ph, product, month, companies, produced_map):
    """Move this month's contracted goods before the market clears ``product``.

    Mutates ``companies`` (stock, and inserts a shell company for a buyer who owns
    no buildings so the ordinary market loop can store or resell the surplus) and
    ``produced_map``. Returns the deliveries to be paid in :func:`settle`.
    """
    rows = db.execute(_q(
        "SELECT id,supplier,buyer,qty,price,penalty,end_month FROM trade_contracts "
        "WHERE status='active' AND product=%s AND start_month<=%s AND end_month>=%s ORDER BY id", ph),
        (product, month, month)).fetchall()
    if not rows:
        return []
    pools = {}

    def pool_of(owner):
        if owner in pools:
            return pools[owner]
        if owner not in companies:
            _ensure_company(db, ph, companies, produced_map, owner)
        produced = int(produced_map.get(owner, 0))
        stock = int(companies[owner]["stock"].get(product, 0))
        need = int(companies[owner]["needs"].get(product, 0))
        protected = min(max(need, 0), produced + stock)
        prot_prod = min(protected, produced)
        pools[owner] = {"prot_prod": prot_prod, "prot_stock": protected - prot_prod,
                        "prod": produced - prot_prod, "stock": stock - (protected - prot_prod)}
        return pools[owner]

    meta = {}
    orders = []
    for cid, supplier, buyer, qty, price, penalty, end_month in rows:
        qty, price, penalty = int(qty), int(price), int(penalty)
        pool_of(supplier)
        orders.append((cid, supplier, qty))
        meta[cid] = (supplier, buyer, qty, price, penalty, int(end_month))
    planned = plan_deliveries(orders, {owner: pool["prod"] + pool["stock"] for owner, pool in pools.items()})
    incoming = {}
    plan = []
    for item in planned:
        cid, give = item["id"], item["delivered"]
        supplier, buyer, qty, price, penalty, end_month = meta[cid]
        pool = pools[supplier]
        take_stock = min(pool["stock"], give)
        pool["stock"] -= take_stock
        pool["prod"] -= give - take_stock
        if give:
            _ensure_company(db, ph, companies, produced_map, buyer)
            incoming[buyer] = incoming.get(buyer, 0) + give
        plan.append({"id": cid, "supplier": supplier, "buyer": buyer, "qty": qty, "price": price, "penalty": penalty,
                     "delivered": give, "shortfall": item["shortfall"], "value": give * price,
                     "penalty_due": item["shortfall"] * penalty, "end_month": end_month})
    for owner, pool in pools.items():
        extra = incoming.pop(owner, 0)
        companies[owner]["stock"][product] = pool["prot_stock"] + pool["stock"] + extra
        produced_map[owner] = pool["prot_prod"] + pool["prod"]
    for buyer, extra in incoming.items():
        stock = companies[buyer]["stock"]
        stock[product] = int(stock.get(product, 0)) + extra
    saved = []
    for item in plan:
        db.execute(_q("INSERT INTO trade_deliveries(contract_id,month_index,delivered,shortfall,paid,penalty_paid) VALUES(%s,%s,%s,%s,0,0)", ph),
                   (item["id"], month, item["delivered"], item["shortfall"]))
        if month >= item["end_month"]:
            db.execute(_q("UPDATE trade_contracts SET status='completed', closed_reason='fulfilled' WHERE id=%s AND status='active'", ph), (item["id"],))
        saved.append(item)
    return saved


def _pay(db, ph, debtor, creditor, amount, kind, memo, now):
    """Transfer up to the debtor's cash. The unpaid remainder is a debt to the creditor. Returns the amount paid."""
    amount = int(amount)
    if amount <= 0 or debtor == creditor:
        return 0
    paid = min(amount, max(_cash(db, ph, debtor), 0))
    if paid:
        economy.post(db, ph, kind, memo, [(economy.player_account(debtor), -paid), (economy.player_account(creditor), paid)], now)
    unpaid = amount - paid
    if unpaid:
        db.execute(_q("INSERT INTO trade_debts(debtor,creditor,amount) VALUES(%s,%s,%s) "
                      "ON CONFLICT(debtor,creditor) DO UPDATE SET amount=trade_debts.amount+excluded.amount", ph),
                   (debtor, creditor, unpaid))
    return paid


def _repay_debts(db, ph, now):
    rows = db.execute("SELECT debtor,creditor,amount FROM trade_debts WHERE amount>0 ORDER BY debtor,creditor").fetchall()
    for debtor, creditor, amount in rows:
        amount = int(amount)
        paid = min(amount, max(_cash(db, ph, debtor), 0))
        if not paid:
            continue
        economy.post(db, ph, "contract_debt", "Погашение долга по контракту",
                     [(economy.player_account(debtor), -paid), (economy.player_account(creditor), paid)], now)
        left = amount - paid
        if left:
            db.execute(_q("UPDATE trade_debts SET amount=%s WHERE debtor=%s AND creditor=%s", ph), (left, debtor, creditor))
        else:
            db.execute(_q("DELETE FROM trade_debts WHERE debtor=%s AND creditor=%s", ph), (debtor, creditor))


def settle(db, ph, month, deliveries, now, bankrupt):
    """Pay deliveries and old contract debts. May append newly insolvent owners to ``bankrupt``."""
    if not deliveries and db.execute("SELECT 1 FROM trade_debts WHERE amount>0 LIMIT 1").fetchone() is None:
        return
    short = set()
    for item in deliveries:
        paid = _pay(db, ph, item["buyer"], item["supplier"], item["value"], "contract",
                    "Контракт %s: %d ед. по %d" % (item["id"][:8], item["delivered"], item["price"]), now)
        item["paid"] = paid
        if paid < item["value"]:
            short.add(item["buyer"])
    for item in deliveries:
        paid = _pay(db, ph, item["supplier"], item["buyer"], item["penalty_due"], "contract_penalty",
                    "Штраф контракта %s: недопоставка %d" % (item["id"][:8], item["shortfall"]), now)
        item["penalty_paid"] = paid
        if paid < item["penalty_due"]:
            short.add(item["supplier"])
        db.execute(_q("UPDATE trade_deliveries SET paid=%s, penalty_paid=%s WHERE contract_id=%s AND month_index=%s", ph),
                   (item["paid"], item["penalty_paid"], item["id"], month))
    _repay_debts(db, ph, now)
    import production
    for owner in sorted(o for o in short if _human(o)):
        st = production._status(db, ph, owner)
        if st["missed"] <= 0:
            st["missed"] = 1
            production._save_status(db, ph, owner, st)
        if st["missed"] >= economy.BANKRUPT_AFTER_MISSED and owner not in bankrupt:
            bankrupt.append(owner)


def on_bankruptcy(db, ph, owner, month, now):
    """Pay contract debts from whatever cash liquidation left, write off the rest, drop active contracts."""
    rows = db.execute(_q("SELECT creditor,amount FROM trade_debts WHERE debtor=%s AND amount>0 ORDER BY creditor", ph), (owner,)).fetchall()
    for creditor, amount in rows:
        paid = min(int(amount), max(_cash(db, ph, owner), 0))
        if paid:
            economy.post(db, ph, "contract_debt", "Банкротство: долг по контракту",
                         [(economy.player_account(owner), -paid), (economy.player_account(creditor), paid)], now)
    db.execute(_q("DELETE FROM trade_debts WHERE debtor=%s", ph), (owner,))
    db.execute(_q("UPDATE trade_contracts SET status='dissolved', closed_reason='bankruptcy' "
                  "WHERE status='active' AND (supplier=%s OR buyer=%s)", ph), (owner, owner))
