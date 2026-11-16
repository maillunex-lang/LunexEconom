extends Control
signal back_requested
const Api = preload("res://enterprises/chain_api.gd")
const Words = preload("res://enterprises/strings.gd")
const Format = preload("res://i18n/format.gd")
const Forest = preload("res://theme/forest_glass.gd")
const Strings = preload("res://i18n/strings.gd")
const Components = preload("res://ui/components.gd")
const Columns = preload("res://ui/two_columns.gd")
var _columns: Control
var _offers_area: VBoxContainer
var _selected_product := ""
var selected_links: Array = []
var _current_inputs: Array = []

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
    _columns = Columns.new()
    scroll.add_child(_columns)
    _columns.custom_minimum_size = Vector2(0, 300)
    recipe_rows = _columns.list_area
    var offers_scroll := ScrollContainer.new()
    offers_scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
    _columns.detail_area.add_child(offers_scroll)
    _offers_area = VBoxContainer.new()
    _offers_area.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    offers_scroll.add_child(_offers_area)
    _columns.back_button.text = Strings.get_text("caplab.common.back")
    _columns.refresh_size(get_viewport_rect().size)
    message = Label.new()
    message.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    root_box.add_child(message)

func open(adapter: Node, id: int) -> void:
    api.configure(adapter)
    enterprise_id = id
    message.text = Strings.get_text("caplab.common.loading")
    await _load()

func _load() -> void:
    if _loading:
        return
    _loading = true
    message.text = Strings.get_text("caplab.common.loading")
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
    var raw_inputs: Variant = payload.get("inputs", payload.get("recipe_inputs", []))
    var inputs: Array = []
    if raw_inputs is Dictionary:
        for product in raw_inputs:
            inputs.append({"product_id":str(product)})
    elif raw_inputs is Array:
        inputs = raw_inputs
    var links: Array = payload.get("links", [])
    selected_links = links.duplicate(true)
    _current_inputs = inputs.duplicate(true)
    if _offers_area != null:
        for offer_child in _offers_area.get_children():
            offer_child.queue_free()
    if inputs.is_empty():
        _label(Strings.get_text("caplab.supply.no.inputs"))
    var fuel_failures: Array = payload.get("fuel_failures", [])
    for failure in fuel_failures:
        var reason := str(failure.get("reason", ""))
        if reason in ["fuel_unaffordable", "fuel_missing"]:
            _label(Words.get_text("error.build." + reason))
    for input in inputs:
        _add_input_row(input, links)
    if row_controls.is_empty():
        save_button.disabled = true
    elif _selected_product.is_empty() and inputs.size() > 0:
        _selected_product = str(inputs[0].get("product_id", ""))
    if not _selected_product.is_empty():
        await _load_offers(_selected_product)
    if not row_controls.is_empty():
        message.text = ""
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
    var choose := Components.button("caplab.supply.choose", "secondary")
    choose.pressed.connect(func(): _load_offers(product_id); _columns.show_detail())
    box.add_child(choose)
    var fields := HBoxContainer.new()
    var horizontal := ScrollContainer.new()
    horizontal.custom_minimum_size = Vector2(0, 72)
    horizontal.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_AUTO
    box.add_child(horizontal)
    horizontal.add_child(fields)
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
            "min_quality": int(row.quality.value),
            "source_enterprise_id": null
        })
    if not selected_links.is_empty():
        links = selected_links.duplicate(true)
    var result: Dictionary = await api.save_supply(enterprise_id, links)
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
    recipe_rows.add_child(label)

func resize_ui(view_size: Vector2) -> void:
    Forest.apply_touch(self, view_size)
    if _columns != null:
        _columns.refresh_size(view_size)

func _load_offers(product: String) -> void:
    _selected_product = product
    if _offers_area == null:
        return
    for item in _offers_area.get_children():
        item.queue_free()
    _offers_label(Strings.get_text("caplab.common.loading"))
    var result: Dictionary = await api.offers(city,product)
    for item in _offers_area.get_children():
        item.queue_free()
    var code := int(result.get("code",0))
    if code != 200:
        _offers_label(Strings.get_text("caplab.supply.no.permission") if code in [401,403] else Strings.get_text("caplab.supply.unavailable"))
        return
    var offers: Array = result.get("data", {}).get("offers", [])
    if offers.is_empty():
        _offers_label(Strings.get_text("caplab.supply.empty"))
        return
    for offer in offers:
        if offer is Dictionary:
            _add_offer(offer,product)

func _offers_label(value: String) -> void:
    var label := Label.new()
    label.text = value
    label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    _offers_area.add_child(label)

func _add_offer(offer: Dictionary, product: String) -> void:
    var panel := Components.card()
    _offers_area.add_child(panel)
    var stack := VBoxContainer.new()
    panel.add_child(stack)
    var seller_id := int(offer.get("seller_enterprise_id",0))
    var name := str(offer.get("name", ""))
    if name.is_empty():
        name = Strings.get_text("caplab.supply.enterprise",{"id":seller_id}) if seller_id > 0 else Strings.get_text("caplab.supply." + str(offer.get("source_type", "market")))
    if bool(offer.get("is_ai",offer.get("managed_by_ai",false))):
        name += " · " + Strings.get_text("caplab.supply.ai")
    var columns: Array[String] = [name]
    for part in [["price","caplab.price"],["quality","caplab.supply.quality"],["reliability","caplab.supply.reliability"],["distance","caplab.supply.distance"],["score","caplab.supply.score"]]:
        if offer.has(part[0]):
            var value := Format.money(offer[part[0]]) if part[0] == "price" else str(offer[part[0]])
            columns.append(Strings.get_text(str(part[1])) + ": " + value)
    var label := Label.new()
    label.text = " · ".join(columns)
    label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    stack.add_child(label)
    var actions := HBoxContainer.new()
    stack.add_child(actions)
    var choose := Components.button("caplab.supply.select")
    choose.pressed.connect(_choose_offer.bind(offer,product))
    actions.add_child(choose)
    var map_button := Components.button("caplab.supply.map","secondary")
    map_button.pressed.connect(func(): message.text = Strings.get_text("caplab.supply.map.later"))
    actions.add_child(map_button)

func _choose_offer(offer: Dictionary, product: String) -> void:
    var links: Array = []
    for link in selected_links:
        if str(link.get("product_id", "")) == product:
            links.append(link)
    if links.size() >= 3:
        message.text = Strings.get_text("caplab.supply.full")
        return
    var supplier_id := int(offer.get("seller_enterprise_id",0))
    var source_type := str(offer.get("source_type", "enterprise" if supplier_id > 0 else "market"))
    var supplier: Variant = supplier_id if source_type == "enterprise" and supplier_id > 0 else null
    for existing in links:
        if existing.get("source_type") == source_type and existing.get("source_enterprise_id") == supplier:
            message.text = Strings.get_text("caplab.supply.full")
            return
    var slot := links.size() + 1
    selected_links.append({"product_id":product,"source_type":source_type,
        "source_enterprise_id":supplier,"share":1000,"priority":slot,
        "max_price":int(offer.get("price",0)),"min_quality":0})
    # New selections split this product equally; leave other products unchanged.
    var selected: Array = []
    for link in selected_links:
        if str(link.get("product_id", "")) == product:
            selected.append(link)
    var count := selected.size()
    for index in range(count):
        selected[index]["priority"] = index + 1
        selected[index]["share"] = 1000 / count + (1 if index < 1000 % count else 0)
    message.text = Strings.get_text("caplab.supply.selected",{"slot":slot})

func _sum_shares(links: Array) -> int:
    var total := 0
    for link in links:
        total += int(link.get("share",0))
    return total
