"""Transactional equipment upgrades for existing enterprises.

Caller owns the transaction and idempotency lock. No production formula changes
are activated until the monthly settlement has a compatible migration.
"""
import building_dimensions
import economy

def upgrade_equipment(db, ph, owner, object_id, target_level, now):
    if not isinstance(object_id, str) or not object_id or len(object_id) > 64:
        return 400, {"error": "invalid_object_id"}
    if type(target_level) is not int or not 2 <= target_level <= building_dimensions.MAX_EQUIPMENT_LEVEL:
        return 400, {"error": "invalid_equipment_level"}
    q = lambda sql: sql.replace("%s", ph)
    row = db.execute(q("SELECT owner,kind FROM buildings WHERE id=%s"), (object_id,)).fetchone()
    if not row:
        return 404, {"error": "not_found"}
    if row[0] != owner:
        return 403, {"error": "not_owner"}
    kind = row[1]
    if kind not in building_dimensions.SIZE_CHOICES:
        return 409, {"error": "unsupported_kind"}
    dim = db.execute(q("SELECT equipment_level FROM building_dimensions WHERE object_id=%s"), (object_id,)).fetchone()
    current_level = int(dim[0]) if dim else 1
    if not building_dimensions.can_upgrade_equipment(current_level, target_level):
        return 409, {"error": "invalid_upgrade_transition", "current_level": current_level}
    # Fixed integer cost from current building price, no fractional money.
    cost = economy.BUILD_COST[kind] * (20 + 10 * target_level) // 100
    balance = economy.ensure_wallet(db, ph, owner, now)
    if balance < cost:
        return 402, {"error": "insufficient_funds", "cost": cost, "balance": balance}
    # Preserve the original footprint, ownership, inventory, contracts and ops.
    if dim is None:
        w, h = building_dimensions.LEGACY_FOOTPRINTS[kind]
        db.execute(q("INSERT INTO building_dimensions(object_id,width,height,equipment_level) VALUES(%s,%s,%s,%s)"),
                   (object_id, w, h, target_level))
    else:
        db.execute(q("UPDATE building_dimensions SET equipment_level=%s WHERE object_id=%s"), (target_level, object_id))
    economy.post(db, ph, "equipment_upgrade", "Модернизация оборудования", [
        (economy.player_account(owner), -cost), (economy.CONSTRUCTION, cost)], now)
    return 201, {"ok": True, "object_id": object_id, "equipment_level": target_level,
                 "cost": cost, "balance": balance - cost}