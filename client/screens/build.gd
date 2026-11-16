extends Control
signal back_requested
signal built
signal preview_changed(footprint: Dictionary)
signal road_preview_changed(cells: Array)
const Catalog = preload("res://enterprises/catalog.gd")
const EnterpriseApi = preload("res://enterprises/api.gd")
const Words = preload("res://enterprises/strings.gd")
const Format = preload("res://i18n/format.gd")
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
var site_cells: Dictionary = {}
var wallet_balance := -1
var road_near := false
var rows: VBoxContainer
var message: Label
var error_code_label: Label
var zone_label: Label
var road_label: Label
var category: OptionButton
var available_filter: CheckButton
var confirmation: ConfirmationDialog
var _busy := false
var _plan_serial := 0
var plan_data: Dictionary = {}
var plan_details: Label
var plan_shortfall: Label
var preview_canvas: Control

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
    available_filter = CheckButton.new()
    available_filter.text = Words.get_text("build.filter.available")
    available_filter.toggled.connect(func(_checked: bool): _render())
    bar.add_child(available_filter)
    var context := HBoxContainer.new()
    outer.add_child(context)
    zone_label = Label.new()
    zone_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    context.add_child(zone_label)
    road_label = Label.new()
    context.add_child(road_label)
    var preview := PanelContainer.new()
    preview.name = "RoadPreviewPanel"
    preview.custom_minimum_size = Vector2(0, 140)
    outer.add_child(preview)
    var preview_box := VBoxContainer.new()
    preview.add_child(preview_box)
    var preview_title := Label.new()
    preview_title.text = Words.get_text("build.plan.preview")
    preview_box.add_child(preview_title)
    preview_canvas = preload("res://world/map_canvas.gd").new()
    preview_canvas.name = "RoadPreviewCanvas"
    preview_canvas.custom_minimum_size = Vector2(0, 112)
    preview_canvas.mouse_filter = Control.MOUSE_FILTER_IGNORE
    preview_box.add_child(preview_canvas)
    var scroll := ScrollContainer.new()
    scroll.follow_focus = true
    scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
    scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
    outer.add_child(scroll)
    rows = VBoxContainer.new()
    rows.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    scroll.add_child(rows)
    plan_details = Label.new()
    plan_details.name = "RoadPlan"
    plan_details.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    outer.add_child(plan_details)
    plan_shortfall = Label.new()
    plan_shortfall.name = "PlanShortfall"
    plan_shortfall.add_theme_color_override("font_color", Color("f2a8a8"))
    outer.add_child(plan_shortfall)
    message = Label.new()
    message.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    outer.add_child(message)
    error_code_label = Label.new()
    error_code_label.name = "ErrorCode"
    error_code_label.add_theme_font_size_override("font_size",11)
    error_code_label.visible = false
    outer.add_child(error_code_label)
    confirmation = ConfirmationDialog.new()
    confirmation.title = Words.get_text("confirm")
    confirmation.ok_button_text = Words.get_text("confirm")
    confirmation.cancel_button_text = Words.get_text("cancel")
    confirmation.confirmed.connect(_purchase)
    add_child(confirmation)

func open(adapter: Node, parcel: Dictionary, cell: Vector2i) -> void:
    catalog.configure(adapter)
    service.configure(adapter)
    px = int(parcel.get("px",0))
    py = int(parcel.get("py",0))
    x = cell.x
    y = cell.y
    zone = str(parcel.get("zone","free"))
    available_width = maxi(0,px*6+6-x)
    available_height = maxi(0,py*6+6-y)
    road_near = bool(parcel.get("road_near",false))
    _plan_serial += 1
    plan_data.clear()
    chosen.clear()
    if plan_details != null:
        plan_details.text = ""
        plan_shortfall.text = ""
    road_preview_changed.emit([])
    _update_local_preview([])
    site_cells.clear()
    for entry in parcel.get("site_cells",[]):
        if entry is Dictionary and entry.has("x") and entry.has("y"):
            site_cells[_key(int(entry["x"]),int(entry["y"]))] = entry
    zone_label.text = Words.get_text("build.zone.current",{"zone":_zone_name(zone)})
    road_label.text = Words.get_text("build.road.yes" if road_near else "build.road.no")
    message.text = ""
    _load()

func _key(cx: int, cy: int) -> String:
    return "%d,%d" % [cx,cy]

func _zone_name(id: String) -> String:
    return Words.get_text("build.zone."+id) if id in ["free","industrial","residential","center"] else id

func _allowed_names(item: Dictionary) -> String:
    var names: Array[String] = []
    for id in item.get("zones", []):
        names.append(_zone_name(str(id)))
    return ", ".join(names)

func _load() -> void:
    var ok: bool = await catalog.update()
    if not ok and catalog.buildings().is_empty():
        message.text = Words.get_text("catalog.empty")
    var wallet: Dictionary = await service.transport.fetch("/ledger/balance")
    wallet_balance = int(wallet.get("data",{}).get("balance",-1)) if int(wallet.get("code",0)) == 200 else -1
    category.clear()
    category.add_item(Words.get_text("category.all"))
    var categories: Array[String] = []
    for entry in catalog.buildings():
        var kind := str(entry.get("category",""))
        if not categories.has(kind):
            categories.append(kind)
    categories.sort()
    for kind in categories:
        category.add_item(Words.get_text("category."+kind) if Words.has_text("category."+kind) else Words.get_text("category.other"))
        category.set_item_metadata(category.item_count-1,kind)
    _render()

func _cell(cx: int, cy: int) -> Dictionary:
    return site_cells.get(_key(cx,cy),{})

func _evaluate(item: Dictionary) -> Dictionary:
    var footprint: Dictionary = item.get("size",{})
    var width := int(footprint.get("width",0))
    var height := int(footprint.get("height",0))
    var allowed: Array = item.get("zones",[])
    if width<=0 or height<=0 or width>6 or height>6:
        return {"allowed":false,"reason":"size"}
    var any_zone := false
    var any_clear := false
    var any_road := false
    var candidate := {}
    var saw_water := false
    var saw_obstacle := false
    for top_y in range(py*6,py*6+7-height):
        for top_x in range(px*6,px*6+7-width):
            var zones_ok := true
            var clear := true
            var water := false
            var occupied := false
            var complete := not site_cells.is_empty()
            for cy in range(top_y,top_y+height):
                for cx in range(top_x,top_x+width):
                    var cell := _cell(cx,cy)
                    if cell.is_empty():
                        complete = false
                    var cell_zone := str(cell.get("zone",zone))
                    if cell_zone not in allowed:
                        zones_ok = false
                    if str(cell.get("terrain","ground")) == "water":
                        clear = false
                        water = true
                    if bool(cell.get("occupied",false)) or bool(cell.get("road",false)):
                        clear = false
                        occupied = true
            if not zones_ok:
                continue
            any_zone = true
            if not clear:
                saw_water = saw_water or water
                saw_obstacle = saw_obstacle or occupied
                continue
            any_clear = true
            var has_road := false
            var unknown_boundary := false
            for cy in range(top_y,top_y+height):
                for cx in range(top_x,top_x+width):
                    for neighbor in [Vector2i(cx-1,cy),Vector2i(cx+1,cy),Vector2i(cx,cy-1),Vector2i(cx,cy+1)]:
                        if neighbor.x>=top_x and neighbor.x<top_x+width and neighbor.y>=top_y and neighbor.y<top_y+height:
                            continue
                        var adjacent: Dictionary = _cell(neighbor.x,neighbor.y)
                        if adjacent.is_empty():
                            unknown_boundary = true
                        elif bool(adjacent.get("road",false)):
                            has_road = true
            # Local site validity only; server plan owns final access/cost.
            var installment := int(item.get("build_cost",0))*300/1000
            if wallet_balance>=0 and wallet_balance<installment:
                return {"allowed":false,"reason":"money","amount":installment,"x":top_x,"y":top_y}
            if has_road or unknown_boundary or not complete:
                return {"allowed":true,"x":top_x,"y":top_y,"reason":""}
            if candidate.is_empty():
                candidate = {"allowed":true,"x":top_x,"y":top_y,"reason":""}
            any_road = any_road or has_road
    if not any_zone:
        return {"allowed":false,"reason":"zone"}
    if not any_clear:
        return {"allowed":false,"reason":"water" if saw_water and not saw_obstacle else "occupied"}
    if not candidate.is_empty():
        # Permit server-planned access roads even if the old local road test fails.
        # Preserve the historical diagnostic result for unselected previews.
        return {"allowed":false,"reason":"road","candidate":candidate}
    if not any_road:
        return {"allowed":false,"reason":"road"}
    return {"allowed":false,"reason":"occupied"}

func _reason(item: Dictionary, result: Dictionary) -> String:
    var reason := str(result.get("reason",""))
    match reason:
        "zone": return Words.get_text("build.reason.zone",{"zones":_allowed_names(item)})
        "size": return Words.get_text("build.reason.size",{"width":int(item.get("size",{}).get("width",0)),"height":int(item.get("size",{}).get("height",0))})
        "money": return Words.get_text("build.reason.money",{"amount":Format.money(result.get("amount",0))})
        "road": return Words.get_text("build.reason.road")
        "occupied": return Words.get_text("build.reason.occupied")
        "water": return Words.get_text("build.reason.water")
    return Words.get_text("build.reason.offline")

func _render() -> void:
    for node in rows.get_children():
        node.queue_free()
    var kind := "" if category.selected<=0 else str(category.get_item_metadata(category.selected))
    for entry in catalog.buildings():
        var item: Dictionary = entry
        if not kind.is_empty() and str(item.get("category","")) != kind:
            continue
        var status := _evaluate(item)
        var allowed := bool(status.get("allowed",false)) or status.has("candidate") or str(status.get("reason","")) == "money"
        if available_filter.button_pressed and not allowed:
            continue
        var footprint: Dictionary = item.get("size",{})
        var card := PanelContainer.new()
        rows.add_child(card)
        var content := VBoxContainer.new()
        card.add_child(content)
        var description := Label.new()
        description.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
        description.text = "%s. %s" % [str(item.get("name",item.get("id",""))),str(item.get("description",""))]
        content.add_child(description)
        var specs := Label.new()
        specs.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
        specs.text = "%s  •  %s  •  %s  •  %s" % [
            Words.get_text("size",{"width":int(footprint.get("width",0)),"height":int(footprint.get("height",0))}),
            Words.get_text("cost",{"cost":Format.number(item.get("build_cost",0))}),
            Format.days(item.get("build_days",0)),
            Words.get_text("build.zone.allowed",{"zones":_allowed_names(item)})]
        content.add_child(specs)
        var requirements: Variant = item.get("materials_required", null)
        if requirements is Dictionary and requirements.get("items", []) is Array:
            _append_materials_summary(content, requirements.get("items", []))
        var button := Button.new()
        button.text = Words.get_text("build.plan.choose") if str(status.get("reason","")) in ["road","money"] else (Words.get_text("build.available") if allowed else Words.get_text("build.unavailable",{"reason":_reason(item,status)}))
        button.disabled = not allowed
        if allowed:
            button.pressed.connect(_choose.bind(item, status.get("candidate", status)))
        content.add_child(button)

func _append_materials_summary(container: VBoxContainer, items: Array) -> void:
    var labels: Array[String] = []
    for entry in items:
        if not (entry is Dictionary):
            continue
        var id := str(entry.get("product_id", ""))
        labels.append(Words.get_text("build.materials.item", {"name":catalog.product_name(id),"needed":Format.number(entry.get("needed",0)),"unit":catalog.product_unit(id)}))
    if not labels.is_empty():
        var label := Label.new()
        label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
        label.text = Words.get_text("build.materials.summary", {"items":", ".join(labels)})
        container.add_child(label)

func _choose(item: Dictionary, placement: Dictionary) -> void:
    if _busy:
        return
    chosen = item
    x = int(placement.get("x", x))
    y = int(placement.get("y", y))
    var footprint: Dictionary = item.get("size", {})
    var footprint_data := {"x": x, "y": y, "width": int(footprint.get("width", 1)),
        "height": int(footprint.get("height", 1))}
    preview_changed.emit(footprint_data)
    preview_canvas.preview = footprint_data
    preview_canvas.focus(Vector2i(x + int(footprint.get("width", 1)) / 2, y + int(footprint.get("height", 1)) / 2))
    preview_canvas.queue_redraw()
    _schedule_plan()


func _schedule_plan() -> void:
    _plan_serial += 1
    var serial := _plan_serial
    plan_data.clear()
    plan_details.text = Words.get_text("build.plan.loading")
    plan_shortfall.text = ""
    road_preview_changed.emit([])
    _update_local_preview([])
    await get_tree().create_timer(0.3).timeout
    if serial != _plan_serial or chosen.is_empty():
        return
    var response: Dictionary = await service.plan(str(chosen.get("id", "")), px, py, x, y)
    if serial != _plan_serial or chosen.is_empty():
        return
    if int(response.get("code", 0)) != 200:
        plan_details.text = Words.error(response)
        return
    var data: Dictionary = response.get("data", {})
    plan_data = data
    if not bool(data.get("ok", false)):
        var reason := str(data.get("reason", "unknown"))
        plan_details.text = Words.get_text("error.build." + reason) if Words.has_text("error.build." + reason) else Words.get_text("build.plan.unavailable")
        return
    var road: Array = data.get("road_cells", [])
    road_preview_changed.emit(road)
    _update_local_preview(road)
    var material_lines: Array[String] = []
    var required: Variant = data.get("materials_required", null)
    if required is Dictionary and required.get("items", []) is Array:
        for item in required["items"]:
            if item is Dictionary:
                var product_id := str(item.get("product_id", ""))
                material_lines.append(Words.get_text("build.materials.item", {"name":catalog.product_name(product_id),"needed":Format.number(item.get("needed",0)),"unit":catalog.product_unit(product_id)}))
    plan_details.text = "\n".join([
        Words.get_text("build.plan.road", {"count": road.size(), "cost": Format.money(data.get("road_cost", 0))}),
        Words.get_text("build.plan.initial", {"amount": Format.money(data.get("initial_payment", 0))}),
        Words.get_text("build.plan.total", {"amount": Format.money(data.get("total_initial", 0))})])
    if not material_lines.is_empty():
        plan_details.text += "\n" + Words.get_text("build.materials.summary", {"items":", ".join(material_lines)})
    if not bool(data.get("can_afford", false)):
        plan_shortfall.text = Words.get_text("build.plan.shortfall", {"amount": Format.money(data.get("shortfall", 0))})
        return
    plan_shortfall.text = Words.get_text("build.plan.afford")
    confirmation.dialog_text = Words.get_text("build.plan.confirm", {
        "name": chosen.get("name", ""), "total": Format.money(data.get("total_initial", 0))})
    confirmation.popup_centered()


func _update_local_preview(cells: Array) -> void:
    if preview_canvas == null:
        return
    preview_canvas.road_preview.clear()
    for item in cells:
        if item is Array and item.size() >= 2:
            preview_canvas.road_preview.append(Vector2i(int(item[0]), int(item[1])))
    preview_canvas.queue_redraw()


func _purchase() -> void:
    if _busy or chosen.is_empty() or not bool(plan_data.get("ok", false)) or not bool(plan_data.get("can_afford", false)):
        return
    _busy = true
    message.text = Words.get_text("loading")
    error_code_label.visible = false
    var response: Dictionary = await service.create(str(chosen.get("id","")),px,py,x,y)
    _busy = false
    if int(response.get("code",0)) in [200,201]:
        message.text = Words.get_text("done.build")
        built.emit()
    else:
        message.text = Words.error(response)
        var raw_code := str(response.get("data",{}).get("error","unknown"))
        if not Words.has_text("error.build."+raw_code):
            message.text = Words.get_text("error.build.unknown")
            error_code_label.text = Words.get_text("error.build.code",{"code":raw_code})
            error_code_label.visible = true
        if raw_code == "insufficient_funds":
            message.text = Words.get_text("build.plan.error.money", {
                "required": Format.money(response.get("data", {}).get("required", 0)),
                "road_cost": Format.money(response.get("data", {}).get("road_cost", 0)),
                "shortfall": Format.money(response.get("data", {}).get("shortfall", 0))})
        if raw_code=="invalid_zone":
            message.text += "\n" + Words.get_text("build.zone.allowed",{"zones":_allowed_names(chosen)})

func resize_ui(view_size: Vector2) -> void:
    Forest.apply_touch(self,view_size)