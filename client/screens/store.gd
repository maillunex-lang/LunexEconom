extends Control
signal back_requested
const Api = preload("res://enterprises/chain_api.gd")
const Catalog = preload("res://enterprises/catalog.gd")
const Words = preload("res://enterprises/strings.gd")
const Format = preload("res://i18n/format.gd")
const Forest = preload("res://theme/forest_glass.gd")
const Strings = preload("res://i18n/strings.gd")
const Components = preload("res://ui/components.gd")
const Columns = preload("res://ui/two_columns.gd")
var _columns: Control
var _detail_panel: VBoxContainer
var _stock_data: Dictionary = {}

var api: Node
var catalog: Node
var enterprise_id := -1
var city := ""
var rows: VBoxContainer
var message: Label
var save_button: Button
var row_controls: Array[Dictionary] = []

func _ready() -> void:
    set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    api = Api.new()
    add_child(api)
    catalog = Catalog.new()
    add_child(catalog)
    var root_box := VBoxContainer.new()
    root_box.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    add_child(root_box)
    var header := HBoxContainer.new()
    root_box.add_child(header)
    var back := Button.new()
    back.text = Words.get_text("chain.back")
    back.custom_minimum_size = Vector2(0, 48)
    back.pressed.connect(func(): back_requested.emit())
    header.add_child(back)
    var title := Label.new()
    title.text = Words.get_text("store.title")
    title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    header.add_child(title)
    save_button = Button.new()
    save_button.text = Words.get_text("chain.save")
    save_button.custom_minimum_size = Vector2(160, 48)
    save_button.pressed.connect(_save)
    header.add_child(save_button)
    var retry := Button.new()
    retry.text = Words.get_text("chain.retry")
    retry.custom_minimum_size = Vector2(0, 48)
    retry.pressed.connect(_load)
    header.add_child(retry)
    var scroll := ScrollContainer.new()
    scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
    root_box.add_child(scroll)
    _columns = Columns.new()
    scroll.add_child(_columns)
    _columns.custom_minimum_size = Vector2(0, 300)
    rows = _columns.list_area
    _detail_panel = VBoxContainer.new()
    _columns.detail_area.add_child(_detail_panel)
    _columns.back_button.text = Strings.get_text("caplab.common.back")
    _columns.refresh_size(get_viewport_rect().size)
    message = Label.new()
    message.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    root_box.add_child(message)

func open(adapter: Node, id: int) -> void:
    api.configure(adapter)
    catalog.configure(adapter)
    enterprise_id = id
    message.text = Words.get_text("chain.loading")
    await catalog.update()
    await _load()

func _load() -> void:
    row_controls.clear()
    save_button.disabled = false
    message.text = Strings.get_text("caplab.common.loading")
    for child in rows.get_children():
        child.queue_free()
    var detail: Dictionary = await api.detail(enterprise_id)
    if int(detail.get("code", 0)) != 200:
        _fail(detail)
        save_button.disabled = true
        return
    var data: Dictionary = detail.get("data", {})
    city = str(data.get("city", data.get("city_id", "ufa")))
    var cells_response: Dictionary = await api.cells(enterprise_id)
    if int(cells_response.get("code", 0)) != 200:
        _fail(cells_response)
        save_button.disabled = true
        return
    var payload: Dictionary = cells_response.get("data", {})
    var capacity := int(payload.get("capacity", payload.get("retail_cells", 0)))
    var allowed: Array = payload.get("allowed_goods", [])
    var building: Dictionary = catalog.building(str(data.get("building_id", "")))
    if building.has("allowed_goods"):
        var server_allowed: Array = building["allowed_goods"]
        allowed = allowed.filter(func(item):
            var good_id := str(item.get("id", "") if item is Dictionary else item)
            return good_id in server_allowed)
    var current: Array = payload.get("cells", [])
    _stock_data = data.get("inventory", {}) if data.get("inventory", {}) is Dictionary else {}
    for extra in _detail_panel.get_children():
        if extra is Label:
            extra.queue_free()
    if capacity <= 0 or allowed.is_empty():
        message.text = Strings.get_text("caplab.common.empty")
        _label(Words.get_text("store.no_cells"))
        save_button.disabled = true
        return
    for cell_index in range(capacity):
        await _add_cell(cell_index, allowed, current)
    message.text = ""

func _add_cell(index: int, allowed: Array, current: Array) -> void:
    var panel := PanelContainer.new()
    panel.custom_minimum_size = Vector2(0, 150)
    rows.add_child(panel)
    var box := VBoxContainer.new()
    panel.add_child(box)
    var heading := Label.new()
    heading.text = Words.get_text("store.cell", {"index": index + 1})
    box.add_child(heading)
    var fields := HBoxContainer.new()
    var horizontal := ScrollContainer.new()
    horizontal.custom_minimum_size = Vector2(0, 72)
    horizontal.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_AUTO
    box.add_child(horizontal)
    horizontal.add_child(fields)
    var product := OptionButton.new()
    product.custom_minimum_size = Vector2(220, 48)
    for good in allowed:
        var id := str(good.get("id", "") if good is Dictionary else good)
        var name: String = catalog.product_name(id)
        product.add_item(name)
        product.set_item_metadata(product.item_count - 1, id)
    var price := SpinBox.new()
    price.min_value = 1
    price.max_value = 2147483647
    price.step = 1
    price.custom_minimum_size = Vector2(150, 48)
    var min_stock := SpinBox.new()
    min_stock.min_value = 0
    min_stock.max_value = 2147483647
    min_stock.step = 1
    min_stock.custom_minimum_size = Vector2(150, 48)
    var source := OptionButton.new()
    source.custom_minimum_size = Vector2(160, 48)
    for pair in [["store.source.stock", 0], ["store.source.slot1", 1], ["store.source.slot2", 2], ["store.source.slot3", 3]]:
        source.add_item(Words.get_text(pair[0]))
        source.set_item_metadata(source.item_count - 1, pair[1])
    for label_key in ["store.product", "store.price", "store.min_stock", "store.source"]:
        var caption := Label.new()
        caption.text = Words.get_text(label_key)
        caption.custom_minimum_size = Vector2(100, 48)
        fields.add_child(caption)
    fields.add_child(product)
    fields.add_child(price)
    fields.add_child(min_stock)
    fields.add_child(source)
    var rating_bar := ProgressBar.new()
    rating_bar.custom_minimum_size = Vector2(0,48)
    rating_bar.max_value = 100
    rating_bar.show_percentage = false
    box.add_child(rating_bar)
    var rating_text := Label.new()
    rating_text.text = Strings.get_text("caplab.store.no.rating")
    box.add_child(rating_text)
    var sales_label := Label.new()
    sales_label.text = Words.get_text("store.sales.loading")
    box.add_child(sales_label)
    var selected: Dictionary = {}
    for cell in current:
        if int(cell.get("cell_index", -1)) == index:
            selected = cell
            break
    _set_product(product, str(selected.get("product_id", "")))
    var initial_id := str(selected.get("product_id", ""))
    if initial_id.is_empty() and product.item_count > 0:
        initial_id = str(product.get_item_metadata(0))
    var stock_label := Label.new()
    stock_label.text = Strings.get_text("caplab.store.stock") + ": " + Format.number(_stock_data[initial_id].get("quantity",0)) if _stock_data.has(initial_id) and _stock_data[initial_id] is Dictionary else Strings.get_text("caplab.store.no.stock")
    box.add_child(stock_label)
    var ref_price := int(catalog.product(initial_id).get("reference_price", 0))
    price.value = int(selected.get("price", ref_price if ref_price > 0 else 1))
    var reference := Label.new()
    reference.name = "ReferencePrice"
    reference.text = Words.get_text("store.reference", {"price": Format.money(ref_price)}) if ref_price > 0 else ""
    box.add_child(reference)
    product.item_selected.connect(func(_idx: int):
        var chosen_id := str(product.get_item_metadata(product.selected))
        var new_price := int(catalog.product(chosen_id).get("reference_price", 0))
        reference.text = Words.get_text("store.reference", {"price": Format.money(new_price)}) if new_price > 0 else ""
        if new_price > 0 and selected.is_empty():
            price.value = new_price)
    if selected.has("min_price") and selected.has("max_price"):
        price.min_value = maxf(1.0,float(selected["min_price"]))
        price.max_value = maxf(price.min_value,float(selected["max_price"]))
        price.value = clampf(price.value,price.min_value,price.max_value)
    min_stock.value = int(selected.get("min_stock", 0))
    _set_source(source, int(selected.get("supply_link_slot") if selected.get("supply_link_slot") != null else 0))
    row_controls.append({"index": index, "product": product, "price": price, "min_stock": min_stock, "source": source})
    var good := initial_id
    if good.is_empty() and product.item_count > 0:
        good = str(product.get_item_metadata(0))
    if not good.is_empty():
        var rating: Dictionary = await api.ratings(city, good)
        if int(rating.get("code", 0)) == 200:
            var items: Array = rating.get("data", {}).get("items", rating.get("data", {}).get("ratings", []))
            for item in items:
                if int(item.get("enterprise_id",-1)) == enterprise_id and int(item.get("cell_index",-1)) == index:
                    if item.has("rating"):
                        rating_bar.value = clampf(float(item["rating"]),0,100)
                        rating_text.text = Strings.get_text("caplab.store.rating") + ": " + str(item["rating"])
                    break
            for contribution in ["price_factor","quality_factor","brand_factor"]:
                if rating.get("data",{}).has(contribution):
                    _rating_part(contribution, rating.get("data",{})[contribution])
    var sales: Dictionary = await api.sales(enterprise_id, 0, 1)
    if int(sales.get("code", 0)) == 200:
        var sale_items: Array = sales.get("data", {}).get("sales", sales.get("data", {}).get("items", []))
        var total := 0
        for item in sale_items:
            total += int(item.get("quantity", 0))
        sales_label.text = Words.get_text("store.sales", {"quantity": total, "revenue": Format.money(_revenue(sale_items))})
    else:
        sales_label.text = Words.get_text("store.sales.unavailable")

func _average(values: Array[int]) -> int:
    if values.is_empty():
        return 0
    var total := 0
    for value in values:
        total += value
    return total / values.size()

func _revenue(items: Array) -> int:
    var total := 0
    for item in items:
        total += int(item.get("revenue", int(item.get("quantity", 0)) * int(item.get("price", 0))))
    return total

func _set_source(option: OptionButton, value: int) -> void:
    for index in range(option.item_count):
        if int(option.get_item_metadata(index)) == value:
            option.select(index)
            return

func _set_product(option: OptionButton, value: String) -> void:
    for index in range(option.item_count):
        if str(option.get_item_metadata(index)) == value:
            option.select(index)
            return

func _save() -> void:
    save_button.disabled = true
    var output: Array = []
    for row in row_controls:
        output.append({"cell_index": row.index, "product_id": str(row.product.get_item_metadata(row.product.selected)), "price": int(row.price.value), "min_stock": int(row.min_stock.value), "supply_link_slot": int(row.source.get_item_metadata(row.source.selected)) if int(row.source.get_item_metadata(row.source.selected)) > 0 else null})
    var result: Dictionary = await api.save_cells(enterprise_id, output)
    if int(result.get("code", 0)) >= 200 and int(result.get("code", 0)) < 300:
        message.text = Words.get_text("chain.saved")
    else:
        _fail(result)
    save_button.disabled = false

func _fail(response: Dictionary) -> void:
    message.text = Strings.get_text("caplab.common.permission") if int(response.get("code",0)) in [401,403] else Strings.get_text("caplab.common.error")

func _label(value: String) -> void:
    var label := Label.new()
    label.text = value
    label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    rows.add_child(label)

func resize_ui(view_size: Vector2) -> void:
    Forest.apply_touch(self, view_size)
    if _columns != null:
        _columns.refresh_size(view_size)

func _rating_part(key: String, value: Variant) -> void:
    var label := Label.new()
    var name := "caplab.store.price.factor" if key == "price_factor" else "caplab.store.quality.factor" if key == "quality_factor" else "caplab.store.brand.factor"
    label.text = Strings.get_text(name) + ": " + str(value)
    label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    _detail_panel.add_child(label)
