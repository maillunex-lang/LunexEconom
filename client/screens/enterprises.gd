extends Control
signal back_requested
signal wallet_changed
const Service = preload("res://enterprises/api.gd")
const Catalog = preload("res://enterprises/catalog.gd")
const Words = preload("res://enterprises/strings.gd")
const Forest = preload("res://theme/forest_glass.gd")
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
        button.text = "%s  |  %s  |  %s" % [str(entry.get("name", entry.get("building_id", ""))),stage_text,Words.get_text("load",{"percent":int(entry.get("load_bp",0))/100})]
        button.pressed.connect(show_detail.bind(int(id)))
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
    list_button.pressed.connect(func(): current_id = -1; refresh_list())
    body.add_child(list_button)
    _label(str(current.get("name", "")))
    var stage := int(current.get("stage_index", 0))
    _label(Words.get_text("construction", {"stage":Words.get_text("stage."+str(current.get("stage", "foundation"))),"progress":mini(100,stage*25)}) if stage < 4 else Words.get_text("running" if current.get("running",false) else "stopped"))
    _label(Words.get_text("staff",{"percent":int(current.get("staffing_bp",0))/100}))
    _label(Words.get_text("load",{"percent":int(current.get("load_bp",0))/100}))
    _label(Words.get_text("wear",{"wear":current.get("wear",0)}))
    _label(Words.get_text("inventory"))
    var inventory: Dictionary = current.get("inventory", {})
    if inventory.is_empty():
        _label(Words.get_text("inventory.empty"))
    for product in inventory:
        var stock: Dictionary = inventory[product]
        _label("%s: %s" % [product,Words.get_text("quantity",{"quantity":stock.get("quantity",0),"quality":stock.get("quality",0)})])
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
    recipe_select.add_item("Без рецепта")
    recipe_select.set_item_metadata(0, "")
    for recipe in catalog.data.get("recipes", []):
        if str(recipe.get("building", "")) == str(current.get("building_id", "")):
            recipe_select.add_item(str(recipe.get("id", "")))
            recipe_select.set_item_metadata(recipe_select.item_count-1, str(recipe.get("id", "")))
    for i in range(recipe_select.item_count):
        if str(recipe_select.get_item_metadata(i)) == str(current.get("recipe_id", "")):
            recipe_select.select(i)
    body.add_child(recipe_select)
    var save := Button.new()
    save.text = Words.get_text("apply")
    save.pressed.connect(_save_settings)
    body.add_child(save)
    _label(Words.get_text("report"))
    var report: Dictionary = await service.report(id)
    if int(report.get("code", 0)) == 200:
        var reports: Array = report.get("data", {}).get("reports", [])
        if reports.is_empty():
            _label(Words.get_text("report.empty"))
        for item in reports:
            _label(Words.get_text("report.row",{"month":item.get("month_index",0),"revenue":item.get("revenue",0),"expenses":item.get("expenses",0),"profit":item.get("profit",0)}))
    else:
        _label(Words.error(report))
    var sell_button := Button.new()
    sell_button.text = Words.get_text("sell")
    sell_button.disabled = stage < 4 or not inventory.is_empty()
    sell_button.pressed.connect(func():
        sale_dialog.dialog_text = Words.get_text("confirm.sell",{"name":current.get("name","")})
        sale_dialog.popup_centered())
    body.add_child(sell_button)

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
