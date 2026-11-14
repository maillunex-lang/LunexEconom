"""Player order book for honey, oil, goods and any later ``economy.MARKET`` product.

Matching is a pure function (``match_book``): price first, then time (``seq``),
partial fills, no self-trade. Money moves by double entry. Goods move only
through ``inventory`` — a sell order reserves stock on placement and a fill
credits the buyer, so units are never created or destroyed. The exchange fee
goes to the city budget. See docs/ALLIANCES.md.
"""
import uuid

import contracts
import economy


FEE_PERMILLE = 10          # 1 % of the notional, taken from the payment, paid to the city
MAX_OPEN = 8
MIN_LOT = 1
MAX_QTY = 10_000


def _q(sql, ph):
    return sql.replace("%s", ph)


def _human(owner):
    return type(owner) is str and bool(owner) and owner not in economy.RESERVED_OWNERS and ":" not in owner


def fee_of(notional):
    """Integer city fee. Zero on a tiny notional; never larger than the notional."""
    if notional <= 0:
        return 0
    return min(int(notional), int(notional) * FEE_PERMILLE // 1000)


def match_book(resting, incoming):
    """Match one incoming order against a resting book. Does not mutate inputs.

    ``resting`` items: id, owner, side (buy|sell), price, qty (still open), seq.
    ``incoming``: owner, side, price, qty.
    Trade price is the resting order's price. Buys take the cheapest ask first;
    sells take the highest bid first; equal prices break by smaller ``seq``, then id.
    Orders of the same owner are skipped (no self-trade).
    Returns ``(fills, leftover)`` where each fill is {id, owner, side, price, qty}.
    """
    side = incoming["side"]
    if side not in ("buy", "sell"):
        raise ValueError("side")
    opposite = "sell" if side == "buy" else "buy"
    price = int(incoming["price"])
    left = int(incoming["qty"])
    owner = incoming["owner"]
    ranked = []
    for order in resting:
        if order.get("side") != opposite or int(order.get("qty") or 0) <= 0:
            continue
        if order.get("owner") == owner:
            continue
        if order.get("status", "open") not in (None, "open"):
            continue
        other = int(order["price"])
        if side == "buy" and other > price:
            continue
        if side == "sell" and other < price:
            continue
        seq = int(order.get("seq") or 0)
        ident = str(order.get("id"))
        key = (other, seq, ident) if side == "buy" else (-other, seq, ident)
        ranked.append((key, order))
    ranked.sort(key=lambda item: item[0])
    fills = []
    for _key, order in ranked:
        if left <= 0:
            break
        take = min(left, int(order["qty"]))
        if take <= 0:
            continue
        fills.append({"id": order["id"], "owner": order["owner"], "side": order["side"],
                      "price": int(order["price"]), "qty": take})
        left -= take
    return fills, left


def _balance(db, ph, account):
    row = db.execute(_q("SELECT balance FROM wallets WHERE account=%s", ph), (account,)).fetchone()
    return int(row[0]) if row else 0


def _ensure(db, ph, account):
    db.execute(_q("INSERT INTO wallets(account,balance) VALUES(%s,0) ON CONFLICT(account) DO NOTHING", ph), (account,))


def _stock(db, ph, owner, product):
    row = db.execute(_q("SELECT qty FROM inventory WHERE owner=%s AND product=%s", ph), (owner, product)).fetchone()
    return int(row[0]) if row else 0


def add_stock(db, ph, owner, product, delta):
    """Apply a stock delta. Returns False if the result would be negative. Never deletes units into the void."""
    new = _stock(db, ph, owner, product) + int(delta)
    if new < 0:
        return False
    db.execute(_q("INSERT INTO inventory(owner,product,qty) VALUES(%s,%s,%s) ON CONFLICT(owner,product) DO UPDATE SET qty=excluded.qty", ph),
               (owner, product, new))
    return True


def escrow_account(order_id):
    return "exchange:" + order_id


def _move(db, ph, src, dst, amount, kind, memo, now):
    if amount <= 0:
        return True
    if _balance(db, ph, src) < amount:
        return False
    economy.post(db, ph, kind, memo, [(src, -amount), (dst, amount)], now)
    return True


def _pay_fill(db, ph, escrow, seller, notional, now):
    """Buyer escrow pays the seller; the fee lands in the city budget. Sum of the posting is 0."""
    fee = fee_of(notional)
    seller_net = notional - fee
    entries = [(escrow, -notional)]
    if seller_net:
        entries.append((economy.player_account(seller), seller_net))
    if fee:
        entries.append((economy.player_account(economy.CITY), fee))
    if _balance(db, ph, escrow) < notional:
        return False
    economy.post(db, ph, "exchange", "Сделка на бирже", entries, now)
    return True


def _next_seq(db, ph):
    import social
    return social.next_id(db, ph, "exchange")


def _apply(db, ph, incoming_id, incoming, fills, now):
    """Apply fills. Incoming buy money already sits on ``exchange:<incoming_id>``.
    Incoming sell stock is already reserved (removed from the seller).
    Resting sells have reserved stock; resting buys have their own escrow.
    """
    spent = 0
    done = []
    for fill in fills:
        notional = int(fill["qty"]) * int(fill["price"])
        if incoming["side"] == "buy":
            buyer, seller = incoming["owner"], fill["owner"]
            escrow = escrow_account(incoming_id)
            sell_id, buy_id = fill["id"], incoming_id
        else:
            buyer, seller = fill["owner"], incoming["owner"]
            escrow = escrow_account(fill["id"])
            sell_id, buy_id = incoming_id, fill["id"]
        if not _pay_fill(db, ph, escrow, seller, notional, now):
            break
        if not add_stock(db, ph, buyer, incoming["product"], fill["qty"]):
            raise RuntimeError("stock credit failed")
        spent += notional if incoming["side"] == "buy" else 0
        left = int(db.execute(_q("SELECT qty_left FROM soc_orders WHERE id=%s", ph), (fill["id"],)).fetchone()[0]) - int(fill["qty"])
        status = "filled" if left == 0 else "open"
        db.execute(_q("UPDATE soc_orders SET qty_left=%s, status=%s WHERE id=%s", ph), (left, status, fill["id"]))
        db.execute(_q("INSERT INTO soc_fills(id,buy_id,sell_id,buyer,seller,product,qty,price,fee,created) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", ph),
                   (uuid.uuid4().hex, buy_id, sell_id, buyer, seller, incoming["product"], int(fill["qty"]), int(fill["price"]), fee_of(notional), now))
        done.append({"order_id": fill["id"], "qty": int(fill["qty"]), "price": int(fill["price"]), "fee": fee_of(notional)})
    return done, spent


def place_order(db, ph, owner, payload, month, now):
    """POST /soc/exchange/order."""
    if not _human(owner):
        return 403, {"error": "npc_forbidden"}
    product = payload.get("product")
    side = payload.get("side")
    qty, price = payload.get("qty"), payload.get("price")
    if product not in economy.MARKET:
        return 400, {"error": "invalid_product"}
    if side not in ("buy", "sell"):
        return 400, {"error": "invalid_side"}
    if type(qty) is not int or not MIN_LOT <= qty <= MAX_QTY:
        return 400, {"error": "invalid_qty"}
    lo, hi = contracts.price_bounds(product)
    if type(price) is not int or not lo <= price <= hi:
        return 400, {"error": "price_out_of_range", "min_price": lo, "max_price": hi}
    open_n = int(db.execute(_q("SELECT COUNT(*) FROM soc_orders WHERE owner=%s AND status='open'", ph), (owner,)).fetchone()[0])
    if open_n >= MAX_OPEN:
        return 409, {"error": "too_many_orders"}
    oid = uuid.uuid4().hex
    if side == "sell":
        if _stock(db, ph, owner, product) < qty:
            return 409, {"error": "insufficient_stock", "have": _stock(db, ph, owner, product)}
        if not add_stock(db, ph, owner, product, -qty):
            return 409, {"error": "insufficient_stock"}
    else:
        reserve = price * qty
        economy.ensure_wallet(db, ph, owner, now)
        if (economy.balance(db, ph, owner) or 0) < reserve:
            return 402, {"error": "insufficient_funds", "cost": reserve, "balance": economy.balance(db, ph, owner) or 0}
        _ensure(db, ph, escrow_account(oid))
        if not _move(db, ph, economy.player_account(owner), escrow_account(oid), reserve, "exchange_reserve", "Резерв заявки на покупку", now):
            return 402, {"error": "insufficient_funds", "cost": reserve, "balance": economy.balance(db, ph, owner) or 0}
    seq = _next_seq(db, ph)
    db.execute(_q("INSERT INTO soc_orders(id,owner,product,side,qty,qty_left,price,status,created,seq) VALUES(%s,%s,%s,%s,%s,%s,%s,'open',%s,%s)", ph),
               (oid, owner, product, side, qty, qty, price, now, seq))
    resting = [_order_dict(r) for r in db.execute(
        _q("SELECT id,owner,side,price,qty_left,seq,status FROM soc_orders WHERE product=%s AND status='open' AND id<>%s ORDER BY seq,id", ph),
        (product, oid))]
    incoming = {"owner": owner, "side": side, "price": price, "qty": qty, "product": product}
    fills, leftover = match_book(resting, incoming)
    applied, spent = _apply(db, ph, oid, incoming, fills, now)
    filled_qty = sum(int(f["qty"]) for f in applied)
    leftover = qty - filled_qty
    if side == "buy":
        refund = price * qty - spent - price * leftover
        if refund > 0:
            _move(db, ph, escrow_account(oid), economy.player_account(owner), refund, "exchange_refund", "Возврат разницы цены", now)
    status = "filled" if leftover == 0 else "open"
    db.execute(_q("UPDATE soc_orders SET qty_left=%s, status=%s WHERE id=%s", ph), (leftover, status, oid))
    return 201, {"ok": True, "order": _public(db, ph, oid), "fills": applied,
                 "balance": economy.balance(db, ph, owner), "stock": _stock(db, ph, owner, product), "month": month}


def cancel_order(db, ph, owner, payload, month, now):
    """POST /soc/exchange/cancel. Returns reserved stock or reserved roubles."""
    if not _human(owner):
        return 403, {"error": "npc_forbidden"}
    oid = payload.get("order_id")
    if type(oid) is not str or not 8 <= len(oid) <= 64:
        return 400, {"error": "invalid_order"}
    row = db.execute(_q("SELECT owner,product,side,qty_left,price,status FROM soc_orders WHERE id=%s", ph), (oid,)).fetchone()
    if row is None:
        return 404, {"error": "not_found"}
    oowner, product, side, qty_left, price, status = row
    if oowner != owner:
        return 403, {"error": "not_owner"}
    if status != "open":
        return 409, {"error": "invalid_state"}
    qty_left, price = int(qty_left), int(price)
    if side == "sell":
        if not add_stock(db, ph, owner, product, qty_left):
            return 409, {"error": "insufficient_stock"}
    else:
        back = _balance(db, ph, escrow_account(oid))
        if back and not _move(db, ph, escrow_account(oid), economy.player_account(owner), back, "exchange_cancel", "Отмена заявки", now):
            return 409, {"error": "invalid_state"}
    db.execute(_q("UPDATE soc_orders SET status='cancelled', qty_left=0 WHERE id=%s", ph), (oid,))
    return 201, {"ok": True, "order_id": oid, "status": "cancelled", "balance": economy.balance(db, ph, owner),
                 "stock": _stock(db, ph, owner, product), "month": month}


def _order_dict(row):
    ident, owner, side, price, qty, seq, status = row
    return {"id": ident, "owner": owner, "side": side, "price": int(price), "qty": int(qty), "seq": int(seq), "status": status}


def _public(db, ph, oid):
    row = db.execute(_q("SELECT id,owner,product,side,qty,qty_left,price,status,seq FROM soc_orders WHERE id=%s", ph), (oid,)).fetchone()
    ident, owner, product, side, qty, qty_left, price, status, seq = row
    return {"id": ident, "name": owner, "product": product, "product_name": economy.MARKET[product]["name"],
            "side": side, "qty": int(qty), "qty_left": int(qty_left), "price": int(price), "status": status, "seq": int(seq)}


def view_book(db, ph, owner, args):
    """GET /soc/exchange/book?product= — aggregated price levels, no account names."""
    product = args.get("product")
    if product not in economy.MARKET:
        return 400, {"error": "invalid_product"}
    rows = db.execute(_q("SELECT side,price,qty_left FROM soc_orders WHERE product=%s AND status='open' AND qty_left>0 ORDER BY seq,id", ph),
                      (product,)).fetchall()
    bids, asks = {}, {}
    for side, price, qty in rows:
        bucket = bids if side == "buy" else asks
        bucket[int(price)] = bucket.get(int(price), 0) + int(qty)
    lo, hi = contracts.price_bounds(product)
    products = []
    for key in economy.MARKET:
        bounds = contracts.price_bounds(key)
        products.append({"id": key, "name": economy.MARKET[key]["name"], "min_price": bounds[0], "max_price": bounds[1],
                         "reference_price": economy.MARKET[key]["reference_price"]})
    return 200, {"ok": True, "product": product, "name": economy.MARKET[product]["name"],
                 "min_price": lo, "max_price": hi, "reference_price": economy.MARKET[product]["reference_price"],
                 "fee_permille": FEE_PERMILLE, "min_lot": MIN_LOT, "max_qty": MAX_QTY, "max_open": MAX_OPEN,
                 "products": products,
                 "bids": [{"price": p, "qty": bids[p]} for p in sorted(bids, reverse=True)],
                 "asks": [{"price": p, "qty": asks[p]} for p in sorted(asks)],
                 "viewer": owner}


def my_orders(db, ph, owner, args):
    rows = db.execute(_q("SELECT id FROM soc_orders WHERE owner=%s ORDER BY seq DESC LIMIT 30", ph), (owner,)).fetchall()
    return 200, {"ok": True, "orders": [_public(db, ph, r[0]) for r in rows]}
