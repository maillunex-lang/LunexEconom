extends Control
signal back_requested
signal built
signal preview_changed(footprint: Dictionary)
const Catalog = preload("res://enterprises/catalog.gd")
const EnterpriseApi = preload("res://enterprises/api.gd")
const Words = preload("res://enterprises/strings.gd")
const Forest = preload("res://theme/forest_glass.gd")
var catalog: Node
var service: Node
var zone := "free"
var px := 0
var py := 0
var x := 0
var y := 0
var available_width := 6
var available_height := 6
var chosen: Dictionary = {}
var rows: VBoxContainer
var message: Label
var category: OptionButton
var confirmation: ConfirmationDialog
var _busy := false

func _ready() -> void:
    set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    catalog = Catalog.new()
    add_child(catalog)
    service = EnterpriseApi.new()
    add_child(service)
    var outer := VBoxContainer.new()
    outer.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    add_child(outer)
    var bar := HBoxContainer.new()
    outer.add_child(bar)
    var back := Button.new()
    back.text = Words.get_text("back")
    back.pressed.connect(func(): back_requested.emit())
    bar.add_child(back)
    var title := Label.new()
    title.text = Words.get_text("choose")
    title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    bar.add_child(title)
    category = OptionButton.new()
    category.item_selected.connect(func(_idx: int): _render())
    bar.add_child(category)
    var scroll := ScrollContainer.new()
    scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
    outer.add_child(scroll)
    rows = VBoxContainer.new()
    rows.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    scroll.add_child(rows)
    message = Label.new()
    message.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    outer.add_child(message)
    confirmation = ConfirmationDialog.new()
    confirmation.title = Words.get_text("confirm")
    confirmation.ok_button_text = Words.get_text("confirm")
    confirmation.cancel_button_text = Words.get_text("cancel")
    confirmation.confirmed.connect(_purchase)
    add_child(confirmation)

func open(adapter: Node, parcel: Dictionary, cell: Vector2i) -> void:
    catalog.configure(adapter)
    service.configure(adapter)
    px = int(parcel.get("px", 0))
    py = int(parcel.get("py", 0))
    x = cell.x
    y = cell.y
    zone = str(parcel.get("zone", "free"))
    available_width = maxi(0, px*6+6-x)
    available_height = maxi(0, py*6+6-y)
    message.text = Words.get_text("loading")
    _load()

func _load() -> void:
    var ok: bool = await catalog.update()
    message.text = "" if ok else Words.get_text("catalog.empty")
    category.clear()
    category.add_item(Words.get_text("category.all"))
    var categories: Array[String] = []
    for item in catalog.buildings():
        var kind := str(item.get("category", ""))
        if not categories.has(kind):
            categories.append(kind)
    categories.sort()
    for kind in categories:
        category.add_item(kind)
        category.set_item_metadata(category.item_count-1, kind)
    _render()

func _render() -> void:
    for node in rows.get_children():
        node.queue_free()
    var filter_kind := "" if category.selected <= 0 else str(category.get_item_metadata(category.selected))
    for entry in catalog.buildings():
        var item: Dictionary = entry
        if not filter_kind.is_empty() and str(item.get("category", "")) != filter_kind:
            continue
        var size: Dictionary = item.get("size", {})
        var width := int(size.get("width", 0))
        var height := int(size.get("height", 0))
        var allowed: bool = catalog.eligible(item, zone, available_width, available_height)
        var card := PanelContainer.new()
        rows.add_child(card)
        var content := VBoxContainer.new()
        card.add_child(content)
        var description := Label.new()
        description.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
        description.text = "%s. %s" % [str(item.get("name", item.get("id", ""))),str(item.get("description", ""))]
        content.add_child(description)
        var specs := Label.new()
        specs.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
        specs.text = "%s  •  %s  •  %s" % [Words.get_text("size", {"width":width,"height":height}), Words.get_text("cost", {"cost":item.get("build_cost", 0)}), Words.get_text("duration", {"days":item.get("build_days", 0)})]
        content.add_child(specs)
        var button := Button.new()
        button.text = Words.get_text("build") if allowed else Words.get_text("reason.zone" if zone not in item.get("zones", []) else "reason.size")
        button.disabled = not allowed
        if allowed:
            button.pressed.connect(_choose.bind(item))
        content.add_child(button)

func _choose(item: Dictionary) -> void:
    if _busy:
        return
    chosen = item
    var footprint: Dictionary = item.get("size", {})
    preview_changed.emit({"x":x,"y":y,"width":int(footprint.get("width",1)),"height":int(footprint.get("height",1))})
    confirmation.dialog_text = Words.get_text("confirm.build", {"name":item.get("name", ""),"cost":item.get("build_cost", 0)})
    confirmation.popup_centered()

func _purchase() -> void:
    if _busy or chosen.is_empty():
        return
    _busy = true
    message.text = Words.get_text("loading")
    var response: Dictionary = await service.create(str(chosen.get("id", "")), px, py, x, y)
    _busy = false
    if int(response.get("code", 0)) in [200, 201]:
        message.text = Words.get_text("done.build")
        built.emit()
    else:
        message.text = Words.error(response)

func resize_ui(view_size: Vector2) -> void:
    Forest.apply_touch(self, view_size)