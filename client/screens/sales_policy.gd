extends Control
## GDD 30: owner-only, server-bounded sales policy, no fabricated forecasts.
signal back_requested
const Api = preload("res://enterprises/chain_api.gd")
const Strings = preload("res://i18n/strings.gd")
const Components = preload("res://ui/components.gd")
const Columns = preload("res://ui/two_columns.gd")
const Format = preload("res://i18n/format.gd")
const Forest = preload("res://theme/forest_glass.gd")
var api: Node
var enterprise_id := -1
var product_id := ""
var layout: Control
var mode: OptionButton
var price: SpinBox
var slider: HSlider
var reserve: SpinBox
var invites: LineEdit
var status: Label
var apply_button: Button
var check_button: Button
var version := 0
var min_price := 0
var max_price := 0
var _pending_id := ""
var _locked := false

func _ready() -> void:
    set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    api = Api.new()
    add_child(api)
    layout = Columns.new()
    add_child(layout)
    var heading := Label.new()
    heading.text = Strings.get_text("caplab.sales.title")
    heading.add_theme_font_size_override("font_size", 24)
    layout.list_area.add_child(heading)
    var back := Components.button("caplab.common.back", "secondary")
    back.pressed.connect(func(): back_requested.emit())
    layout.list_area.add_child(back)
    mode = OptionButton.new()
    mode.custom_minimum_size = Vector2(48,48)
    for value in ["private", "public", "mixed", "invited"]:
        mode.add_item(Strings.get_text("caplab.sales." + value))
        mode.set_item_metadata(mode.item_count-1, value)
    layout.list_area.add_child(_labeled("caplab.mode", mode))
    price = SpinBox.new()
    price.step = 1
    price.custom_minimum_size = Vector2(48,48)
    layout.list_area.add_child(_labeled("caplab.price", price))
    slider = HSlider.new()
    slider.step = 1
    slider.custom_minimum_size = Vector2(48,48)
    slider.value_changed.connect(func(value: float): price.value = value)
    price.value_changed.connect(func(value: float): slider.value = value)
    layout.list_area.add_child(slider)
    reserve = SpinBox.new()
    reserve.min_value = 0
    reserve.max_value = 100
    reserve.step = 1
    reserve.custom_minimum_size = Vector2(48,48)
    layout.list_area.add_child(_labeled("caplab.sales.reserve",reserve))
    invites = LineEdit.new()
    invites.custom_minimum_size = Vector2(48,48)
    invites.placeholder_text = Strings.get_text("caplab.sales.invites")
    layout.list_area.add_child(_labeled("caplab.sales.invites", invites))
    mode.item_selected.connect(func(_idx: int): _update_fields())
    var side := Components.card()
    layout.detail_area.add_child(side)
    var actions := VBoxContainer.new()
    side.add_child(actions)
    status = Label.new()
    status.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    actions.add_child(status)
    check_button = Components.button("caplab.sales.check", "secondary")
    check_button.pressed.connect(func(): _submit(true))
    actions.add_child(check_button)
    apply_button = Components.button("caplab.sales.apply")
    apply_button.pressed.connect(func(): _submit(false))
    actions.add_child(apply_button)
    layout.back_button.text = Strings.get_text("caplab.common.back")
    _set_ready(false)
    _update_fields()
    resize_ui(get_viewport_rect().size)

func _labeled(key: String, field: Control) -> VBoxContainer:
    var container := VBoxContainer.new()
    var label := Label.new()
    label.text = Strings.get_text(key)
    label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    container.add_child(label)
    container.add_child(field)
    return container

func open(adapter: Node, id: int, product: String) -> void:
    api.configure(adapter)
    enterprise_id = id
    product_id = product
    _pending_id = ""
    status.text = Strings.get_text("caplab.common.loading")
    _set_ready(false)
    var response: Dictionary = await api.sales_policy(id, product)
    var code := int(response.get("code",0))
    if code != 200:
        status.text = _error(response)
        return
    var data: Dictionary = response.get("data", {})
    var active: Dictionary = data.get("pending", {}) if data.get("pending", {}) is Dictionary else {}
    if active.is_empty() and data.get("active", {}) is Dictionary:
        active = data.get("active", {})
    version = int(active.get("version",0))
    var bounds: Dictionary = data.get("price_limits", data.get("bounds", {}))
    min_price = int(bounds.get("min_price", data.get("min_price", 0)))
    max_price = int(bounds.get("max_price", data.get("max_price", 0)))
    if max_price < min_price or min_price <= 0:
        _set_ready(false)
        status.text = Strings.get_text("caplab.sales.no.bounds")
        return
    price.min_value = min_price
    price.max_value = max_price
    slider.min_value = min_price
    slider.max_value = max_price
    price.value = clampi(int(active.get("price",min_price)),min_price,max_price)
    slider.value = price.value
    var selected := str(active.get("mode", "public"))
    for i in range(mode.item_count):
        if str(mode.get_item_metadata(i)) == selected:
            mode.select(i)
            break
    reserve.value = int(active.get("reserve_bp",0)) / 100.0
    var ids: Array = active.get("invited_owner_ids", []) if active.get("invited_owner_ids", []) is Array else []
    var parts: Array[String] = []
    for id_value in ids:
        parts.append(str(id_value))
    invites.text = ", ".join(parts)
    _update_fields()
    _set_ready(true)
    status.text = Strings.get_text("caplab.sales.version",{"version":version})

func _set_ready(enabled: bool) -> void:
    _locked = not enabled
    check_button.disabled = not enabled
    apply_button.disabled = not enabled
    mode.disabled = not enabled
    price.editable = enabled
    slider.editable = enabled
    reserve.editable = enabled
    invites.editable = enabled

func _update_fields() -> void:
    var selected := str(mode.get_item_metadata(mode.selected))
    reserve.get_parent().visible = selected == "mixed"
    invites.get_parent().visible = selected == "invited"

func _payload(dry_run: bool) -> Dictionary:
    var selected := str(mode.get_item_metadata(mode.selected))
    var invited: Array = []
    if selected == "invited":
        for entry in invites.text.split(",",false):
            var trimmed := entry.strip_edges()
            if not trimmed.is_valid_int() or int(trimmed) < 1:
                return {}
            if not invited.has(int(trimmed)):
                invited.append(int(trimmed))
    if _pending_id.is_empty():
        _pending_id = "sales:%s" % Crypto.new().generate_random_bytes(16).hex_encode()
    return {"mode":selected,"price":int(price.value),
        "reserve_bp":int(reserve.value)*100 if selected == "mixed" else (10000 if selected == "private" else 0),
        "invited_owner_ids":invited,"expected_version":version,"request_id":_pending_id,"dry_run":dry_run}

func _submit(dry_run: bool) -> void:
    if _locked:
        return
    var values := _payload(dry_run)
    if values.is_empty():
        status.text = Strings.get_text("caplab.sales.invalid")
        return
    _set_ready(false)
    status.text = Strings.get_text("caplab.common.loading")
    var result: Dictionary = await api.save_sales_policy(enterprise_id, product_id, values)
    var code := int(result.get("code",0))
    if code >= 200 and code < 300:
        status.text = Strings.get_text("caplab.sales.ready" if dry_run else "caplab.sales.saved")
        if not dry_run:
            version = int(result.get("data",{}).get("version",version))
            _pending_id = ""
    else:
        status.text = _error(result)
        if code == 409:
            _pending_id = ""
    _set_ready(true)

func _error(response: Dictionary) -> String:
    var code := int(response.get("code",0))
    var reason := str(response.get("data",{}).get("error", ""))
    if code == 401 or code == 403:
        return Strings.get_text("caplab.sales.no.permission")
    if code == 404 or reason == "feature_disabled":
        return Strings.get_text("caplab.sales.unavailable")
    if code == 409:
        return Strings.get_text("caplab.sales.pending" if reason == "pending_change_exists" else "caplab.sales.contracts" if reason == "active_contracts_block_private" else "caplab.sales.conflict")
    if code == 400:
        return Strings.get_text("caplab.sales.invalid")
    return Strings.get_text("caplab.sales.error")

func resize_ui(view_size: Vector2) -> void:
    Forest.apply_touch(self,view_size)
    if layout != null:
        layout.refresh_size(view_size)
