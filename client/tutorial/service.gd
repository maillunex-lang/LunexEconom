extends Node
signal verified(step: int)
signal clock_observed(day: int)
const State = preload("res://tutorial/state.gd")
var api: Node
var active_account := ""
var busy := false
var started_day := -1

func configure(adapter: Node, account: String, first_day: int = -1) -> void:
    api = adapter
    active_account = account
    started_day = first_day

func refresh() -> void:
    if busy or api == null or active_account.is_empty():
        return
    busy = true
    var id: String = active_account
    var me: Dictionary = await api.fetch("/auth/me")
    var wallet: Dictionary = await api.fetch("/ledger/balance")
    var snapshot := {
        "identity_confirmed": int(me.get("code", 0)) == 200 and str(me.get("data", {}).get("id", "")) == id,
        "wallet_confirmed": int(wallet.get("code", 0)) == 200 and wallet.get("data", {}).has("balance")
    }
    if not bool(snapshot["identity_confirmed"]) or not bool(snapshot["wallet_confirmed"]):
        if id == active_account:
            verified.emit(State.verified_progress(snapshot))
        busy = false
        return
    var clock: Dictionary = await api.fetch("/clock")
    var day_now := int(clock.get("data", {}).get("day_index", -1)) if int(clock.get("code", 0)) == 200 else -1
    if day_now >= 0 and id == active_account:
        clock_observed.emit(day_now)
    var baseline := started_day if started_day >= 0 else day_now
    var enterprises: Dictionary = await api.fetch("/enterprises")
    if int(enterprises.get("code", 0)) != 200:
        busy = false
        return
    var details: Array = []
    var supplies := {}
    var shops := {}
    var total_revenue := 0
    var had_bread_sale := false
    for enterprise_id in enterprises.get("data", {}).get("enterprises", []):
        var detail: Dictionary = await api.fetch("/enterprises/%d" % int(enterprise_id))
        if int(detail.get("code", 0)) != 200:
            continue
        var d: Dictionary = detail.get("data", {})
        details.append(d)
        if str(d.get("building_id", "")) in ["mill", "bakery"]:
            var link: Dictionary = await api.fetch("/enterprises/%d/supply" % int(enterprise_id))
            if int(link.get("code", 0)) == 200:
                supplies[str(enterprise_id)] = link.get("data", {}).get("inputs", {})
        if str(d.get("building_id", "")) in ["grocery_store", "supermarket"]:
            var cells: Dictionary = await api.fetch("/enterprises/%d/cells" % int(enterprise_id))
            if int(cells.get("code", 0)) == 200:
                shops[str(enterprise_id)] = cells.get("data", {}).get("cells", [])
            var first := maxi(0, day_now - 365)
            var end := maxi(first, day_now)
            var sales: Dictionary = await api.fetch("/enterprises/%d/sales?day_from=%d&day_to=%d" % [int(enterprise_id), first, end])
            if int(sales.get("code", 0)) == 200:
                for row in sales.get("data", {}).get("sales", []):
                    if row is Dictionary and str(row.get("product_id", "")) == "bread" and int(row.get("quantity", 0)) > 0:
                        had_bread_sale = true
                        total_revenue += int(row.get("revenue", 0))
    snapshot["details"] = details
    snapshot["supplies"] = supplies
    var cells_flat: Array = []
    for shop in shops.values():
        cells_flat.append_array(shop)
    snapshot["retail_cells"] = cells_flat
    snapshot["bread_sale_confirmed"] = had_bread_sale
    snapshot["sales"] = [{"product_id": "bread", "quantity": 1, "revenue": total_revenue}] if had_bread_sale else []
    snapshot["ten_days_confirmed"] = day_now >= 0 and baseline >= 0 and day_now - baseline >= 9
    # The world API exposes only chunk-scoped /land/parcels.
    # A confirmed player-owned parcel is needed before progressing to building.
    snapshot["land_confirmed"] = await _owned_land(details)
    if id == active_account:
        verified.emit(State.verified_progress(snapshot))
    busy = false

func _owned_land(details: Array) -> bool:
    # An enterprise on the account implies a previously owned parcel.
    if not details.is_empty():
        return true
    # Query only the chunks already fetched for this account; the world has
    # no global GET /land endpoint. Unseen parcels cannot be presumed owned.
    if api == null or not api.has_meta("tutorial_chunks"):
        return false
    for chunk in api.get_meta("tutorial_chunks", []):
        if chunk is Vector2i:
            var response: Dictionary = await api.fetch("/land/parcels?chunk=%d,%d" % [chunk.x, chunk.y])
            if int(response.get("code", 0)) != 200:
                continue
            for parcel in response.get("data", {}).get("parcels", []):
                if parcel is Dictionary and str(parcel.get("owner_kind", "")) == "player" and str(parcel.get("owner_ref", "")) == active_account:
                    return true
    return false