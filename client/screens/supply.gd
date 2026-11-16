extends Control
signal back_requested
const Api = preload("res://enterprises/chain_api.gd")
const Words = preload("res://enterprises/strings.gd")
const Format = preload("res://i18n/format.gd")
const Forest = preload("res://theme/forest_glass.gd")

var api: Node
var enterprise_id := -1
var city := ""
var recipe_rows: VBoxContainer
var message: Label
var save_button: Button
var row_controls: Array[Dictionary] = []
var _loading := false

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
    title.text = Words.get_text("supply.title")
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
    recipe_rows = VBoxContainer.new()
    recipe_rows.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    scroll.add_child(recipe_rows)
    message = Label.new()
    message.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    root_box.add_child(message)

func open(adapter: Node, id: int) -> void:
    api.configure(adapter)
    enterprise_id = id
    message.text = Words.get_text("chain.loading")
    await _load()

func _load() -> void:
    if _loading:
        return
    _loading = true
    for child in recipe_rows.get_children():
        child.queue_free()
    row_controls.clear()
    var detail: Dictionary = await api.detail(enterprise_id)
    if int(detail.get("code", 0)) != 200:
        _fail(detail)
        _loading = false
        return
    var data: Dictionary = detail.get("data", {})
    city = str(data.get("city", data.get("city_id", "ufa")))
    var supply: Dictionary = await api.supply(enterprise_id)
    if int(supply.get("code", 0)) != 200:
        _fail(supply)
        _loading = false
        return
    var payload: Dictionary = supply.get("data", {})
    var inputs: Array = payload.get("inputs", payload.get("recipe_inputs", []))
    var links: Array = payload.get("links", [])
    if inputs.is_empty():
        _label(Words.get_text("supply.no_inputs"))
    var fuel_failures: Array = payload.get("fuel_failures", [])
    for failure in fuel_failures:
        var reason := str(failure.get("reason", ""))
        if reason in ["fuel_unaffordable", "fuel_missing"]:
            _label(Words.get_text("error.build." + reason))
    for input in inputs:
        _add_input_row(input, links)
    if row_controls.is_empty():
        save_button.disabled = true
    _loading = false

func _add_input_row(input: Dictionary, links: Array) -> void:
    var product_id := str(input.get("product_id", input.get("id", "")))
    var panel := PanelContainer.new()
    panel.custom_minimum_size = Vector2(0, 150)
    recipe_rows.add_child(panel)
    var box := VBoxContainer.new()
    panel.add_child(box)
    var heading := Label.new()
    heading.text = str(input.get("name", product_id))
    box.add_child(heading)
    var fields := HBoxContainer.new()
    box.add_child(fields)
    var source := OptionButton.new()
    source.custom_minimum_size = Vector2(220, 48)
    for pair in [["enterprise", "supply.source.enterprise"], ["market", "supply.source.market"], ["port", "supply.source.port"]]:
        source.add_item(Words.get_text(pair[1]))
        source.set_item_metadata(source.item_count - 1, pair[0])
    var priority := SpinBox.new()
    priority.min_value = 1
    priority.max_value = 3
    priority.step = 1
    priority.custom_minimum_size = Vector2(100, 48)
    var share := SpinBox.new()
    share.min_value = 0
    share.max_value = 1000
    share.step = 1
    share.custom_minimum_size = Vector2(110, 48)
    var max_price := SpinBox.new()
    max_price.min_value = 0
    max_price.max_value = 2147483647
    max_price.step = 1
    max_price.custom_minimum_size = Vector2(150, 48)
    var quality := SpinBox.new()
    quality.min_value = 0
    quality.max_value = 100
    quality.step = 1
    quality.custom_minimum_size = Vector2(110, 48)
    for label_key in ["supply.source.label", "supply.priority", "supply.share", "supply.max_price", "supply.min_quality"]:
        var caption := Label.new()
        caption.text = Words.get_text(label_key)
        caption.custom_minimum_size = Vector2(100, 48)
        fields.add_child(caption)
    fields.add_child(source)
    fields.add_child(priority)
    fields.add_child(share)
    fields.add_child(max_price)
    fields.add_child(quality)
    var market_label := Label.new()
    market_label.text = Words.get_text("supply.market.loading")
    box.add_child(market_label)
    var trip_label := Label.new()
    box.add_child(trip_label)
    var current := {}
    for link in links:
        if str(link.get("product_id", "")) == product_id:
            current = link
            break
    trip_label.text = trip_info(current)
    _set_option(source, str(current.get("source_type", current.get("source", "market"))))
    priority.value = int(current.get("priority", 1))
    share.value = int(current.get("share", current.get("share_bp", 1000)))
    max_price.value = int(current.get("max_price", 0))
    quality.value = int(current.get("min_quality", 0))
    row_controls.append({"product_id": product_id, "source": source, "priority": priority, "share": share, "max_price": max_price, "quality": quality, "market": market_label})
    var quote: Dictionary = await api.market(city, product_id)
    if int(quote.get("code", 0)) == 200:
        var q: Dictionary = quote.get("data", {})
        var price := int(q.get("price", q.get("reference_price", 0)))
        var low := int(q.get("corridor_min", q.get("min_price", price)))
        var high := int(q.get("corridor_max", q.get("max_price", price)))
        market_label.text = Words.get_text("supply.market", {"price": Format.money(price), "low": Format.money(low), "high": Format.money(high)})
    else:
        market_label.text = Words.get_text("supply.market.unavailable")

static func trip_info(link: Dictionary) -> String:
    var liters := int(link.get("fuel_liters", 0))
    if liters <= 0:
        return ""
    var result := ""
    if link.has("transport_cost"):
        result = Words.get_text("supply.transport.trip", {"cost": Format.money(link.get("transport_cost", 0))}) + "\n"
    return result + Words.get_text("supply.fuel.trip", {
        "liters": Format.number(liters),
        "cost": Format.money(link.get("fuel_cost", 0))})

func _set_option(option: OptionButton, value: String) -> void:
    for index in range(option.item_count):
        if str(option.get_item_metadata(index)) == value:
            option.select(index)
            return

func _save() -> void:
    save_button.disabled = true
    var links: Array = []
    for row in row_controls:
        links.append({
            "product_id": row.product_id,
            "source_type": str(row.source.get_item_metadata(row.source.selected)),
            "priority": int(row.priority.value),
            "share": int(row.share.value),
            "max_price": int(row.max_price.value),
            "min_quality": int(row.quality.value)
        })
    var result: Dictionary = await api.save_supply(enterprise_id, links)
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
    recipe_rows.add_child(label)

func resize_ui(view_size: Vector2) -> void:
    Forest.apply_touch(self, view_size)
