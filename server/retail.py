"""Shops sell consumer goods to residents. Shared by SQLite and PostgreSQL.

No shop in the world: the wage loop is untouched (residents pay system:market directly).
With shops, a share of that consumer spend is the shop's margin. The market still pays the
shop through the ordinary monthly revenue posting, and residents still return the full
consumer value to the market, so the net effect is: market keeps the wholesale part and the
shop keeps the markup (VAT on the markup follows the goods rate). See docs/RETAIL.md.
"""
import economy


def _q(sql, ph):
    return sql.replace("%s", ph)


def _split(total, weights):
    """Split ``total`` across (owner, weight) in owner order. The last owner takes the remainder."""
    weights = [(owner, weight) for owner, weight in weights if weight > 0]
    if not weights or total <= 0:
        return {}
    weights = sorted(weights)
    whole = sum(weight for _, weight in weights)
    alloc = {}
    used = 0
    for owner, weight in weights[:-1]:
        part = total * weight // whole
        alloc[owner] = part
        used += part
    alloc[weights[-1][0]] = total - used
    return alloc


def apply(companies, consumer_spend, consumer_units, staffing):
    """Add retail margin to shop owners' revenue. Returns the total margin (0 if there is no shop)."""
    if not economy.RETAIL_ENABLED or consumer_spend <= 0 or consumer_units <= 0:
        return 0
    weights = []
    for owner, company in companies.items():
        floor = 0
        for kind, factor in company["buildings"]:
            spec = economy.PRODUCTION.get(kind) or {}
            if spec.get("role") == "retail":
                floor += int(spec.get("floor", 0)) * int(factor) // 1000
        floor = int(floor * staffing)
        if floor > 0:
            weights.append((owner, floor))
    if not weights:
        return 0
    total_floor = sum(weight for _, weight in weights)
    served_units = min(int(consumer_units), total_floor)
    if served_units <= 0:
        return 0
    served_value = int(int(consumer_spend) * served_units / int(consumer_units))
    margin_total = int(served_value * economy.RETAIL_MARKUP / (1.0 + economy.RETAIL_MARKUP))
    if margin_total <= 0:
        return 0
    for owner, amount in _split(margin_total, weights).items():
        if amount <= 0:
            continue
        company = companies[owner]
        company["revenue"] += amount
        company["rev_by"]["goods"] = company["rev_by"].get("goods", 0) + amount
    return margin_total


def snapshot(db, ph, clk, quotes, scale):
    """What the client and the NPC manager need: coverage of consumer demand, not a second market."""
    month = int(clk["month_index"])
    demand_units = 0
    value = 0
    for product, meta in economy.MARKET.items():
        if not meta.get("consumer"):
            continue
        units = int(economy.demand_for(product, month, scale))
        price = int((quotes.get(product) or {}).get("price", meta["reference_price"]))
        demand_units += units
        value += units * price
    floor = 0
    shops = 0
    for (kind,) in db.execute("SELECT kind FROM building_ops").fetchall():
        spec = economy.PRODUCTION.get(kind) or {}
        if spec.get("role") == "retail":
            floor += int(spec.get("floor", 0))
            shops += 1
    return {"markup": economy.RETAIL_MARKUP, "shops": shops, "floor": floor,
            "consumer_demand": demand_units, "unmet_units": max(0, demand_units - floor),
            "unit_price": (value // demand_units) if demand_units else 0}
