extends Control
signal back_requested
signal wallet_changed
signal supply_requested(enterprise_id: int)
signal store_requested(enterprise_id: int)
signal sales_policy_requested(enterprise_id: int, product: String)
const Strings = preload("res://i18n/strings.gd")
const Components = preload("res://ui/components.gd")
const ChainApi = preload("res://enterprises/chain_api.gd")
var detail_mode := false
var _detail_toggle: Button
var _inventory_panel: VBoxContainer
const Service = preload("res://enterprises/api.gd")
const Catalog = preload("res://enterprises/catalog.gd")
const Words = preload("res://enterprises/strings.gd")
const Forest = preload("res://theme/forest_glass.gd")
const Format = preload("res://i18n/format.gd")
const UiStrings = preload("res://i18n/strings.gd")
var service: Node
var catalog: Node
var body: VBoxContainer
var message: Label
var timer: Timer
var current_id := -1
var current: Dictionary = {}
var recipe_select: OptionButton
var running_toggle: CheckButton
var staffing_slider: HSlider
var sale_dialog: ConfirmationDialog
var _loading := false

func _ready() -> void:
    set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    service = Service.new()
    add_child(service)
    catalog = Catalog.new()
    add_child(catalog)
    var layout := VBoxContainer.new()
    layout.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    add_child(layout)
    var header := HBoxContainer.new()
    layout.add_child(header)
    var back := Button.new()
    back.text = Words.get_text("back")
    back.pressed.connect(func(): back_requested.emit())
    header.add_child(back)
    var heading := Label.new()
    heading.text = Words.get_text("title")
    heading.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    header.add_child(heading)
    var refresh := Button.new()
    refresh.text = Words.get_text("refresh")
    refresh.pressed.connect(refresh_list)
    header.add_child(refresh)
    var scroll := ScrollContainer.new()
    scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
    layout.add_child(scroll)
    body = VBoxContainer.new()
    body.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    scroll.add_child(body)
    message = Label.new()
    message.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    layout.add_child(message)
    sale_dialog = ConfirmationDialog.new()
    sale_dialog.title = Words.get_text("sell")
    sale_dialog.ok_button_text = Words.get_text("sell")
    sale_dialog.cancel_button_text = Words.get_text("cancel")
    sale_dialog.confirmed.connect(_sell)
    add_child(sale_dialog)
    timer = Timer.new()
    timer.wait_time = 60.0
    timer.timeout.connect(refresh_list)
    add_child(timer)
    visibility_changed.connect(func():
        if visible and service.transport != null:
            timer.start()
            refresh_list()
        else:
            timer.stop())

func open(adapter: Node, id: int = -1) -> void:
    service.configure(adapter)
    catalog.configure(adapter)
    current_id = id
    timer.start()
    _start()

func _start() -> void:
    await catalog.update()
    if current_id >= 0:
        await show_detail(current_id)
    else:
        await refresh_list()

func refresh_list() -> void:
    if _loading or not visible or service.transport == null:
        return
    _loading = true
    var response: Dictionary = await service.list_own()
    _loading = false
    if int(response.get("code", 0)) != 200:
        message.text = Words.error(response)
        return
    message.text = ""
    _clear()
    var ids: Array = response.get("data", {}).get("enterprises", [])
    if ids.is_empty():
        _label(Words.get_text("empty"))
        return
    for id in ids:
        var detail: Dictionary = await service.detail(int(id))
        if int(detail.get("code", 0)) != 200:
            continue
        var entry: Dictionary = detail.get("data", {})
        var button := Button.new()
        button.alignment = HORIZONTAL_ALIGNMENT_LEFT
        var stage := int(entry.get("stage_index", 0))
        var progress := mini(100, stage*25)
        var stage_text := Words.get_text("construction", {"stage":Words.get_text("stage."+str(entry.get("stage", "foundation"))),"progress":progress}) if stage < 4 else Words.get_text("running" if entry.get("running", false) else "stopped")
        button.text = "%s  |  %s  |  %s" % [catalog.building_name(str(entry.get("building_id", ""))),stage_text,Words.get_text("load",{"percent":int(entry.get("load_bp",0))/100})]
        button.pressed.connect(func(): detail_mode = false; show_detail(int(id)))
        body.add_child(button)

func show_detail(id: int) -> void:
    current_id = id
    var response: Dictionary = await service.detail(id)
    if int(response.get("code", 0)) != 200:
        message.text = Words.error(response)
        return
    current = response.get("data", {})
    _clear()
    message.text = ""
    var list_button := Button.new()
    list_button.text = Words.get_text("title")
    list_button.pressed.connect(func(): current_id = -1; detail_mode = false; refresh_list())
    body.add_child(list_button)
    _label(catalog.building_name(str(current.get("building_id", ""))))
    var stage := int(current.get("stage_index", 0))
    _label(Words.get_text("construction", {"stage":Words.get_text("stage."+str(current.get("stage", "foundation"))),"progress":mini(100,stage*25)}) if stage < 4 else Words.get_text("running" if current.get("running",false) else "stopped"))
    var mode_button := Components.button("caplab.details" if not detail_mode else "caplab.brief", "secondary")
    mode_button.custom_minimum_size = Vector2(150,48)
    mode_button.name = "DetailModeToggle"
    mode_button.pressed.connect(func():
        detail_mode = not detail_mode
        show_detail(current_id))
    body.add_child(mode_button)
    _detail_toggle = mode_button
    _render_materials(current.get("materials_required", null))
    if detail_mode and current.has("staffing_bp"):
        _label(Words.get_text("staff",{"percent":int(current.get("staffing_bp",0))/100}))
    if detail_mode and current.has("load_bp"):
        _label(Words.get_text("load",{"percent":int(current.get("load_bp",0))/100}))
    if detail_mode and current.has("wear"):
        _label(Words.get_text("wear",{"wear":current.get("wear",0)}))
    if detail_mode and (current.has("salary") or current.has("salary_month")):
        _label(Words.get_text("salary",{"amount":Format.money(current.get("salary", current.get("salary_month", 0)))}))
    if detail_mode and (current.has("upkeep") or current.has("upkeep_month")):
        _label(Words.get_text("upkeep",{"amount":Format.money(current.get("upkeep", current.get("upkeep_month", 0)))}))
    var idle_reason := str(current.get("idle_reason", current.get("stop_reason", "")))
    if not idle_reason.is_empty():
        _label(Words.get_text("idle_reason",{"reason":Words.get_text("idle."+idle_reason)}))
    _label(Strings.get_text("caplab.stock") if str(catalog.building(str(current.get("building_id", ""))).get("role", "")) != "retail" else Words.get_text("inventory"))
    var inventory: Dictionary = current.get("inventory", {})
    if inventory.is_empty():
        _label(Words.get_text("inventory.empty"))
    for product in inventory:
        var stock: Dictionary = inventory[product]
        var product_name: String = catalog.product_name(str(product))
        var line := HBoxContainer.new()
        body.add_child(line)
        var stock_label := Label.new()
        stock_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
        stock_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
        var policy: Dictionary = stock.get("sales_policy", {}) if stock.get("sales_policy", {}) is Dictionary else {}
        var mode := str(policy.get("mode", stock.get("sales_mode", "")))
        var mode_label := Strings.get_text("caplab.sales." + mode) if mode in ["private","public","mixed","invited"] else ""
        stock_label.text = Strings.get_text("caplab.sales.mode.row", {
            "product":product_name, "quantity":Format.number(stock.get("quantity",0)),
            "price":Format.money(policy.get("price",stock.get("price",0))) if policy.has("price") or stock.has("price") else "",
            "mode":mode_label})
        line.add_child(stock_label)
        if str(catalog.building(str(current.get("building_id", ""))).get("role", "")) != "retail":
            var policy_button := Components.button("caplab.go.sales", "secondary")
            policy_button.custom_minimum_size = Vector2(170,48)
            line.add_child(policy_button)
            policy_button.pressed.connect(func(): sales_policy_requested.emit(current_id,str(product)))
    running_toggle = CheckButton.new()
    running_toggle.text = Words.get_text("running")
    running_toggle.button_pressed = bool(current.get("running", false))
    body.add_child(running_toggle)
    staffing_slider = HSlider.new()
    staffing_slider.min_value = 0
    staffing_slider.max_value = 100
    staffing_slider.step = 1
    staffing_slider.value = float(current.get("staffing_bp", 0))/100.0
    body.add_child(staffing_slider)
    _label(Words.get_text("recipe"))
    recipe_select = OptionButton.new()
    recipe_select.add_item(Words.get_text("recipe.none"))
    recipe_select.set_item_metadata(0, "")
    for recipe in catalog.data.get("recipes", []):
        if str(recipe.get("building", "")) == str(current.get("building_id", "")):
            recipe_select.add_item(str(recipe.get("name", recipe.get("id", ""))))
            recipe_select.set_item_metadata(recipe_select.item_count-1, str(recipe.get("id", "")))
    for i in range(recipe_select.item_count):
        if str(recipe_select.get_item_metadata(i)) == str(current.get("recipe_id", "")):
            recipe_select.select(i)
    body.add_child(recipe_select)
    var save := Button.new()
    save.text = Words.get_text("apply")
    save.pressed.connect(_save_settings)
    body.add_child(save)
    var chain_actions := HBoxContainer.new()
    body.add_child(chain_actions)
    var supply_button := Button.new()
    supply_button.text = Words.get_text("supply.title")
    supply_button.custom_minimum_size = Vector2(0, 48)
    supply_button.pressed.connect(func(): supply_requested.emit(current_id))
    chain_actions.add_child(supply_button)
    var is_retail := str(catalog.building(str(current.get("building_id", ""))).get("role", "")) == "retail"
    if is_retail:
        var store_button := Button.new()
        store_button.text = Words.get_text("store.title")
        store_button.custom_minimum_size = Vector2(0, 48)
        store_button.pressed.connect(func(): store_requested.emit(current_id))
        chain_actions.add_child(store_button)
    if detail_mode:
        _label(Words.get_text("report"))
    var report: Dictionary = await service.report(id) if detail_mode else {}
    if detail_mode and int(report.get("code", 0)) == 200:
        var reports: Array = report.get("data", {}).get("reports", [])
        if reports.is_empty():
            _label(Words.get_text("report.empty"))
        for item in reports:
            _label(Words.get_text("report.row",{"month":item.get("month_index",0),"revenue":Format.money(item.get("revenue",0)),"expenses":Format.money(item.get("expenses",0)),"profit":Format.money(item.get("profit",0))}))
    elif detail_mode:
        _label(Words.error(report))
    var sell_button := Button.new()
    sell_button.text = Words.get_text("sell")
    sell_button.disabled = stage < 4 or not inventory.is_empty()
    sell_button.pressed.connect(func():
        sale_dialog.dialog_text = Words.get_text("confirm.sell",{"name":current.get("name","")})
        sale_dialog.popup_centered())
    body.add_child(sell_button)

func _render_materials(value: Variant) -> void:
    if not (value is Dictionary):
        return
    var items: Array = value.get("items", [])
    if items.is_empty():
        return
    _label(Words.get_text("build.materials.title"))
    var short_ids: Array[String] = []
    for missing in value.get("short", []):
        short_ids.append(str(missing.get("product_id", "") if missing is Dictionary else missing))
    for item in items:
        if not (item is Dictionary):
            continue
        var product_id := str(item.get("product_id", ""))
        var name: String = catalog.product_name(product_id)
        var shortage := product_id in short_ids or int(item.get("have", 0)) < int(item.get("needed", 0))
        _material_label(Words.get_text("build.materials.row", {"name":name,"needed":Format.number(item.get("needed",0)),"have":Format.number(item.get("have",0)),"unit":catalog.product_unit(product_id)}), shortage)
        if shortage:
            _material_label(UiStrings.get_text("build.material.missing", {"name":name}), true)
    if not short_ids.is_empty():
        _material_label(UiStrings.get_text("build.waiting_materials"), true)

func _material_label(value: String, shortage: bool) -> void:
    var label := Label.new()
    label.text = value
    label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    label.name = "MaterialShortage" if shortage else "MaterialAvailable"
    if shortage:
        label.add_theme_color_override("font_color", Color("f2a8a8"))
    body.add_child(label)

func _save_settings() -> void:
    var recipe := str(recipe_select.get_item_metadata(recipe_select.selected))
    var values := {"running":running_toggle.button_pressed,"staffing_bp":roundi(staffing_slider.value)*100}
    values["recipe_id"] = null if recipe.is_empty() else recipe
    var result: Dictionary = await service.settings(current_id, values)
    if int(result.get("code",0)) == 200:
        await show_detail(current_id)
    else:
        message.text = Words.error(result)

func _sell() -> void:
    var result: Dictionary = await service.sell(current_id)
    if int(result.get("code",0)) == 200:
        message.text = Words.get_text("done.sell")
        wallet_changed.emit()
        current_id = -1
        await refresh_list()
    else:
        message.text = Words.error(result)

func _clear() -> void:
    for child in body.get_children():
        child.queue_free()

func _label(value: String) -> void:
    var label := Label.new()
    label.text = value
    label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    body.add_child(label)

func resize_ui(view_size: Vector2) -> void:
    Forest.apply_touch(self, view_size)