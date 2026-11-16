extends RefCounted
## Client-side progress is only an index into server-confirmed achievements.
const PRODUCTION_STEPS := 15
const TOTAL := 18
var account_id := ""
var completed := false
var collapsed := false
var step := 0
var started_day := -1

func file_path() -> String:
    var safe := account_id if account_id.is_valid_int() else account_id.sha256_text()
    return "user://tutorial_%s.json" % safe

func use_account(id: String) -> void:
    account_id = id
    completed = false
    collapsed = false
    step = 0
    started_day = -1
    if id.is_empty():
        return
    var path := file_path()
    if not FileAccess.file_exists(path):
        return
    var value: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
    if value is Dictionary:
        completed = bool(value.get("completed", false))
        collapsed = bool(value.get("collapsed", false))
        step = clampi(int(value.get("step", 0)), 0, TOTAL)
        started_day = int(value.get("started_day", -1))

func persist() -> bool:
    if account_id.is_empty():
        return false
    var output := FileAccess.open(file_path(), FileAccess.WRITE)
    if output == null:
        return false
    output.store_string(JSON.stringify({"step":step, "completed":completed, "collapsed":collapsed, "started_day":started_day}))
    output.close()
    return true

func reset_progress() -> void:
    step = 0
    completed = false
    collapsed = false
    started_day = -1
    persist()

func note_start_day(day: int) -> void:
    if started_day < 0 and day >= 0:
        started_day = day
        persist()

func accept_verified(verified_step: int) -> void:
    if completed:
        return
    step = maxi(step, clampi(verified_step, 0, TOTAL))
    if step == TOTAL:
        completed = true
    persist()

func can_skip() -> bool:
    return completed

static func _has_product(inventory: Variant, product: String) -> bool:
    if inventory is Dictionary:
        var value: Variant = inventory.get(product, {})
        return (value is Dictionary and int(value.get("quantity", 0)) > 0) or (value is int and value > 0)
    return false

static func _by_building(details: Array, building: String) -> Dictionary:
    for value in details:
        if value is Dictionary and str(value.get("building_id", "")) == building:
            return value
    return {}

static func _operational(data: Dictionary) -> bool:
    return int(data.get("stage_index", -1)) == 4 or str(data.get("stage", "")) == "operational"

static func verified_progress(snapshot: Dictionary) -> int:
    # Missing / invalid API answers must never be treated as successes.
    if not bool(snapshot.get("identity_confirmed", false)):
        return 0
    if not bool(snapshot.get("wallet_confirmed", false)):
        return 1
    if not bool(snapshot.get("land_confirmed", false)):
        return 2
    var details: Array = snapshot.get("details", [])
    var field := _by_building(details, "field")
    if not _operational(field):
        return 3
    if not _has_product(field.get("inventory", {}), "grain"):
        return 4
    var mill := _by_building(details, "mill")
    if not _operational(mill):
        return 5
    if not _linked(snapshot.get("supplies", {}), mill, "grain", field):
        return 6
    if not _has_product(mill.get("inventory", {}), "flour"):
        return 7
    var bakery := _by_building(details, "bakery")
    if not _operational(bakery):
        return 8
    if not _linked(snapshot.get("supplies", {}), bakery, "flour", mill):
        return 9
    if not _has_product(bakery.get("inventory", {}), "bread"):
        return 10
    var store := _by_building(details, "grocery_store")
    if store.is_empty():
        store = _by_building(details, "supermarket")
    if not _operational(store):
        return 11
    var cells: Array = snapshot.get("retail_cells", [])
    var linked := false
    var priced := false
    for cell in cells:
        if cell is Dictionary and str(cell.get("product_id", "")) == "bread":
            if cell.get("supply_link_slot", null) != null:
                linked = true
            if int(cell.get("price", 0)) > 0:
                priced = true
    if not linked:
        return 12
    if not priced:
        return 13
    var sales: Array = snapshot.get("sales", [])
    var revenue := 0
    for sale in sales:
        if sale is Dictionary and str(sale.get("product_id", "")) == "bread":
            if int(sale.get("quantity", 0)) > 0:
                revenue += int(sale.get("revenue", 0))
    if sales.is_empty() or not bool(snapshot.get("bread_sale_confirmed", false)):
        return 14
    if revenue <= 0:
        return 15
    if not bool(snapshot.get("ten_days_confirmed", false)):
        return 16
    return TOTAL

static func _linked(supplies: Dictionary, receiver: Dictionary, good: String, supplier: Dictionary) -> bool:
    var products: Dictionary = supplies.get(str(receiver.get("id", "")), {})
    var links: Array = products.get(good, [])
    for link in links:
        if link is Dictionary and str(link.get("source_type", "")) == "enterprise" and int(link.get("source_enterprise_id", -1)) == int(supplier.get("id", -2)):
            return true
    return false