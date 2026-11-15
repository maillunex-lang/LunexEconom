extends Control
signal back_requested
const Api = preload("res://enterprises/chain_api.gd")
const Words = preload("res://enterprises/strings.gd")
const Format = preload("res://i18n/format.gd")
const Forest = preload("res://theme/forest_glass.gd")

var api: Node
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
    rows = VBoxContainer.new()
    rows.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    scroll.add_child(rows)
    message = Label.new()
    message.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    root_box.add_child(message)

func open(adapter: Node, id: int) -> void:
    api.configure(adapter)
    enterprise_id = id
    message.text = Words.get_text("chain.loading")
    await _load()

func _load() -> void:
    row_controls.clear()
    for child in rows.get_children():
        child.queue_free()
    var detail: Dictionary = await api.detail(enterprise_id)
    if int(detail.get("code", 0)) != 200:
        _fail(detail)
        return
    var data: Dictionary = detail.get("data", {})
    city = str(data.get("city", data.get("city_id", "ufa")))
    var cells_response: Dictionary = await api.cells(enterprise_id)
    if int(cells_response.get("code", 0)) != 200:
        _fail(cells_response)
        return
    var payload: Dictionary = cells_response.get("data", {})
    var capacity := int(payload.get("capacity", payload.get("retail_cells", 0)))
    var allowed: Array = payload.get("allowed_goods", [])
    var current: Array = payload.get("cells", [])
    if capacity <= 0:
        _label(Words.get_text("store.no_cells"))
        return
    for cell_index in range(capacity):
        _add_cell(cell_index, allowed, current)

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
    box.add_child(fields)
    var product := OptionButton.new()
    product.custom_minimum_size = Vector2(220, 48)
    for good in allowed:
        var id := str(good.get("id", good) if good is Dictionary else good)
        var name := str(good.get("name", id) if good is Dictionary else id)
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
    var competitor := Label.new()
    competitor.text = Words.get_text("store.competitors.loading")
    box.add_child(competitor)
    var sales_label := Label.new()
    sales_label.text = Words.get_text("store.sales.loading")
    box.add_child(sales_label)
    var selected: Dictionary = {}
    for cell in current:
        if int(cell.get("cell_index", -1)) == index:
            selected = cell
            break
    _set_product(product, str(selected.get("product_id", "")))
    price.value = int(selected.get("price", 1))
    min_stock.value = int(selected.get("min_stock", 0))
    _set_source(source, int(selected.get("supply_link_slot", 0)))
    row_controls.append({"index": index, "product": product, "price": price, "min_stock": min_stock, "source": source})
    var good := str(selected.get("product_id", ""))
    if good.is_empty() and product.item_count > 0:
        good = str(product.get_item_metadata(0))
    if not good.is_empty():
        var rating: Dictionary = await api.ratings(city, good)
        if int(rating.get("code", 0)) == 200:
            var items: Array = rating.get("data", {}).get("items", rating.get("data", {}).get("ratings", []))
            var values: Array[int] = []
            for item in items:
                values.append(int(item.get("price", 0)))
            var hint := Words.get_text("store.competitors.none") if values.is_empty() else Words.get_text("store.competitors", {"price": Format.money(_average(values))})
            competitor.text = hint
        else:
            competitor.text = Words.get_text("store.competitors.unavailable")
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
    message.text = Words.error(response)

func _label(value: String) -> void:
    var label := Label.new()
    label.text = value
    label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    rows.add_child(label)

func resize_ui(view_size: Vector2) -> void:
    Forest.apply_touch(self, view_size)
