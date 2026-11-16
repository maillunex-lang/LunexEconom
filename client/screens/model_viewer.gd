extends Control
signal back_requested

const Strings = preload("res://i18n/strings.gd")
const Forest = preload("res://theme/forest_glass.gd")
const MANIFEST = "res://models/manifest.json"
const CATALOG_BUILDINGS = "res://models/buildings_catalog.json"
const CATALOG_CITY = "res://models/city_catalog.json"
const STAGES = ["Foundation", "Frame", "Walls", "Roof", "Details"]

var entries: Array = []
var selected: Dictionary = {}
var list_widget: ItemList
var category_widget: OptionButton
var stage_widget: HSlider
var stage_label: Label
var stats_label: Label
var error_label: Label
var viewport_container: SubViewportContainer
var viewport: SubViewport
var model_anchor: Node3D
var camera: Camera3D
var yaw := -0.65
var pitch := -0.42
var distance := 92.0
var _pinch_previous := 0.0
var _touches := {}
var _dragging := false

func _ready() -> void:
    set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    _load_catalog()
    _build_interface()
    _set_filter()
    if not entries.is_empty():
        _select_entry(entries[0])

func _load_catalog() -> void:
    entries.clear()
    for family in ["buildings", "city"]:
        var path := "res://models/%s_catalog.json" % family
        if not FileAccess.file_exists(path):
            continue
        var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
        if parsed is Array:
            for item in parsed:
                if item is Dictionary:
                    var entry: Dictionary = item.duplicate(true)
                    entry["family"] = family
                    entries.append(entry)

func _build_interface() -> void:
    var outer := VBoxContainer.new()
    outer.name = "ViewerLayout"
    outer.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    outer.add_theme_constant_override("separation", 8)
    add_child(outer)
    var top := HBoxContainer.new()
    outer.add_child(top)
    var back := Button.new()
    back.name = "ViewerBack"
    back.text = Strings.get_text("model.viewer.back")
    back.custom_minimum_size = Vector2(110, 48)
    back.pressed.connect(func(): back_requested.emit())
    top.add_child(back)
    var title := Label.new()
    title.name = "ViewerTitle"
    title.text = Strings.get_text("model.viewer.title")
    title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    top.add_child(title)
    var content := HSplitContainer.new()
    content.name = "ViewerSplit"
    content.size_flags_vertical = Control.SIZE_EXPAND_FILL
    content.split_offset = 290
    outer.add_child(content)
    var sidebar := VBoxContainer.new()
    sidebar.custom_minimum_size.x = 190
    content.add_child(sidebar)
    var filter_label := Label.new()
    filter_label.text = Strings.get_text("model.viewer.filter")
    sidebar.add_child(filter_label)
    category_widget = OptionButton.new()
    category_widget.name = "CategoryFilter"
    category_widget.custom_minimum_size.y = 48
    category_widget.item_selected.connect(func(_i: int): _set_filter())
    sidebar.add_child(category_widget)
    list_widget = ItemList.new()
    list_widget.name = "ModelList"
    list_widget.custom_minimum_size.y = 100
    list_widget.size_flags_vertical = Control.SIZE_EXPAND_FILL
    list_widget.item_selected.connect(_on_list_selected)
    sidebar.add_child(list_widget)
    var right := VBoxContainer.new()
    right.custom_minimum_size.x = 180
    content.add_child(right)
    viewport_container = SubViewportContainer.new()
    viewport_container.name = "ScenePreview"
    viewport_container.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    viewport_container.size_flags_vertical = Control.SIZE_EXPAND_FILL
    viewport_container.stretch = true
    viewport_container.gui_input.connect(_on_preview_input)
    right.add_child(viewport_container)
    viewport = SubViewport.new()
    viewport.name = "ModelViewport"
    viewport.size = Vector2i(700,440)
    viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
    viewport.transparent_bg = false
    viewport_container.add_child(viewport)
    var world := Node3D.new()
    world.name = "PreviewWorld"
    viewport.add_child(world)
    model_anchor = Node3D.new()
    model_anchor.name = "ModelAnchor"
    world.add_child(model_anchor)
    camera = Camera3D.new()
    camera.name = "ViewerCamera"
    camera.fov = 40.0
    camera.current = true
    world.add_child(camera)
    var ambient := WorldEnvironment.new()
    var env := Environment.new()
    env.background_mode = Environment.BG_COLOR
    env.background_color = Color("0a201b")
    env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
    env.ambient_light_color = Color("eef5e8")
    env.ambient_light_energy = 0.75
    ambient.environment = env
    world.add_child(ambient)
    var sunlight := DirectionalLight3D.new()
    sunlight.rotation_degrees = Vector3(-45,-25,0)
    sunlight.shadow_enabled = false
    sunlight.light_energy = 1.1
    world.add_child(sunlight)
    var controls := HBoxContainer.new()
    right.add_child(controls)
    stage_label = Label.new()
    stage_label.name = "StageLabel"
    controls.add_child(stage_label)
    stage_widget = HSlider.new()
    stage_widget.name = "StageSlider"
    stage_widget.min_value = 0
    stage_widget.max_value = 4
    stage_widget.step = 1
    stage_widget.value = 4
    stage_widget.custom_minimum_size.x = 180
    stage_widget.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    stage_widget.value_changed.connect(func(value: float): set_stage(int(value)))
    controls.add_child(stage_widget)
    stats_label = Label.new()
    stats_label.name = "ModelStatistics"
    right.add_child(stats_label)
    error_label = Label.new()
    error_label.name = "ModelError"
    error_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    right.add_child(error_label)
    var hint := Label.new()
    hint.text = Strings.get_text("model.viewer.gestures")
    hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    right.add_child(hint)
    set_stage(4)
    _camera_update()

func _set_filter() -> void:
    var old := category_widget.get_selected_id() if category_widget.item_count else 0
    category_widget.clear()
    category_widget.add_item(Strings.get_text("model.viewer.all"))
    category_widget.add_item(Strings.get_text("model.viewer.buildings"))
    category_widget.add_item(Strings.get_text("model.viewer.city"))
    category_widget.select(clampi(old, 0, 2))
    list_widget.clear()
    for i in range(entries.size()):
        var e: Dictionary = entries[i]
        if category_widget.selected == 1 and str(e["family"]) != "buildings":
            continue
        if category_widget.selected == 2 and str(e["family"]) != "city":
            continue
        list_widget.add_item(str(e.get("name","")))
        list_widget.set_item_metadata(list_widget.item_count-1,i)

func _on_list_selected(index: int) -> void:
    _select_entry(entries[int(list_widget.get_item_metadata(index))])

func _select_entry(entry: Dictionary) -> void:
    selected = entry
    var wanted := str(entry["family"])+"/"+str(entry["id"])+".glb"
    var manifest: Variant = JSON.parse_string(FileAccess.get_file_as_string(MANIFEST))
    var record: Dictionary = manifest.get("models",{}).get(wanted,{}) if manifest is Dictionary else {}
    var model: Node3D
    var path := "res://models/"+wanted
    var state := GLTFState.new()
    var document := GLTFDocument.new()
    var code := document.append_from_file(path,state) if FileAccess.file_exists(path) else ERR_FILE_NOT_FOUND
    if code == OK:
        model = document.generate_scene(state)
    if model == null:
        model = _fallback_model(entry)
        error_label.text = Strings.get_text("model.viewer.failed")
    else:
        error_label.text = ""
    for child in model_anchor.get_children():
        model_anchor.remove_child(child)
        child.queue_free()
    model_anchor.add_child(model)
    model.name = "DisplayedModel"
    stage_widget.value = 4
    set_stage(4)
    var footprint := maxf(float(entry["width"]),float(entry["height"])) * 20.0
    distance = maxf(footprint*1.75,55)
    _camera_update()
    stats_label.text = Strings.get_text("model.viewer.statistics", {
        "triangles":str(record.get("triangles",0)),
        "kib":"%.1f" % (float(record.get("bytes",0))/1024.0)
    })

func _fallback_model(entry: Dictionary) -> Node3D:
    var root := Node3D.new()
    root.name = "Root"
    var w := float(entry["width"])*20
    var d := float(entry["height"])*20
    for i in range(5):
        var section := Node3D.new()
        section.name = STAGES[i]
        root.add_child(section)
        if i == 0 or i == 2:
            var body := MeshInstance3D.new()
            body.name = "FallbackBlock"
            var box := BoxMesh.new()
            box.size = Vector3(w,0.65 if i==0 else 8,d)
            body.mesh = box
            body.position.y = 0.325 if i==0 else 4.65
            section.add_child(body)
    return root

func set_stage(value: int) -> void:
    stage_label.text = Strings.get_text("model.viewer.stage",{"stage":str(value)})
    for child in model_anchor.get_children() if model_anchor != null else []:
        for i in range(STAGES.size()):
            var stage := child.find_child(STAGES[i],true,false)
            if stage != null and stage is Node3D:
                stage.visible = i <= value

func _camera_update() -> void:
    if camera == null:
        return
    var eye := Vector3(sin(yaw)*cos(pitch),-sin(pitch),cos(yaw)*cos(pitch))
    camera.position = eye*distance+Vector3(0,8,0)
    camera.look_at(Vector3(0,8,0),Vector3.UP)

func _on_preview_input(event: InputEvent) -> void:
    if event is InputEventScreenTouch:
        if event.pressed:
            _touches[event.index] = event.position
        else:
            _touches.erase(event.index)
            _pinch_previous = 0
    elif event is InputEventScreenDrag:
        _touches[event.index]=event.position
        if _touches.size() == 1:
            yaw-=event.relative.x*.008
            pitch=clampf(pitch+event.relative.y*.006,-1.25,-.15)
        elif _touches.size()==2:
            var positions := _touches.values()
            var span: float = positions[0].distance_to(positions[1])
            if _pinch_previous>0:
                distance=clampf(distance*_pinch_previous/maxf(span,1),28,300)
            _pinch_previous=span
        _camera_update()
    elif event is InputEventMouseMotion and Input.is_mouse_button_pressed(MOUSE_BUTTON_LEFT):
        yaw-=event.relative.x*.008
        pitch=clampf(pitch+event.relative.y*.006,-1.25,-.15)
        _camera_update()
    elif event is InputEventMouseButton and event.pressed:
        if event.button_index == MOUSE_BUTTON_WHEEL_UP:
            distance=clampf(distance*.9,28,300)
        elif event.button_index == MOUSE_BUTTON_WHEEL_DOWN:
            distance=clampf(distance*1.1,28,300)
        _camera_update()

func resize_ui(view_size: Vector2) -> void:
    Forest.apply_touch(self,view_size)
