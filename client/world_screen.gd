extends Control
@onready var world = $World
@onready var hud: MarginContainer = $HUD
@onready var info: Label = $HUD/Top/Info
func _ready() -> void:
    add_to_group("world_hud")
    get_viewport().size_changed.connect(_update_safe_area)
    call_deferred("_update_safe_area")
    $HUD/Top/Expand.pressed.connect(_expand)
    $HUD/Top/Connect.pressed.connect(_connect)
    _setup_build_toolbar()
    _connect_server()
    var sync = load("res://world_sync.gd").new()
    sync.world = world
    add_child(sync)
    var updater = load("res://updater.gd").new()
    updater.name = "Updater"
    add_child(updater)
    updater.state_changed.connect(_on_update_state)
    $HUD/Top/Update.pressed.connect(func() -> void:
        if not updater.downloaded_apk.is_empty():
            updater.install_apk()
        elif not updater.manifest.is_empty() and int(updater.manifest["apk"]["version_code"]) > 8:
            updater.download_apk()
        else:
            updater.check()
    )
    updater.check()
func set_selection(cell: Vector2i) -> void:
    info.text = "Регион 01 · Участок %d:%d" % [cell.x, cell.y]
func _update_safe_area() -> void:
    var v := get_viewport_rect().size
    var s := DisplayServer.screen_get_size()
    var safe := DisplayServer.get_display_safe_area()
    var left := 20
    var top := 20
    var right := 20
    var bottom := 20
    if OS.has_feature("mobile") and s.x > 0 and s.y > 0 and safe.size.x > 0:
        left = maxi(left, int(float(safe.position.x) * v.x / s.x) + 12)
        top = maxi(top, int(float(safe.position.y) * v.y / s.y) + 12)
        right = maxi(right, int(float(s.x - safe.end.x) * v.x / s.x) + 12)
        bottom = maxi(bottom, int(float(s.y - safe.end.y) * v.y / s.y) + 12)
    hud.add_theme_constant_override("margin_left", left)
    hud.add_theme_constant_override("margin_top", top)
    hud.add_theme_constant_override("margin_right", right)
    hud.add_theme_constant_override("margin_bottom", bottom)

func _expand() -> void:
    world.expand_city(2)
    info.text = "Территория: ±%d клеток" % world.expansion_radius

func _connect() -> void:
    if world.selected == Vector2i(-1, -1):
        info.text = "Выберите клетку для дороги"
        return
    if world.commit_access_road(world.selected):
        var path: Array[Vector2i] = world.roads.route(world.selected, Vector2i(0, 0))
        info.text = "Дорога подключена · маршрут %d клеток" % path.size()
    else:
        info.text = "Подключение невозможно"

func _connect_server() -> void:
    var req := HTTPRequest.new()
    add_child(req)
    req.timeout = 8.0
    req.request_completed.connect(func(result: int, code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
        if result == HTTPRequest.RESULT_SUCCESS and code == 200:
            var data = JSON.parse_string(body.get_string_from_utf8())
            info.text = "Сервер: подключён · Мир: %s" % str(data.get("world_id", "?")) if data is Dictionary else "Ошибка данных сервера"
        else:
            info.text = "Сервер недоступен · HTTP %d" % code
        req.queue_free()
    )
    var err := req.request("https://rikagro.ru/lunexeconom/api/world")
    if err != OK:
        info.text = "Ошибка соединения: %d" % err
        req.queue_free()

func _on_update_state(message: String, can_install: bool) -> void:
    $HUD/Top/Update.text = "Установить" if can_install else "Обновить"
    $HUD/Top/Update.tooltip_text = message
    $HUD/Top/UpdateStatus.text = message
var build_toolbar: HBoxContainer
var build_hint: Label

func _setup_build_toolbar() -> void:
    build_toolbar = HBoxContainer.new()
    build_toolbar.name = "ConstructionToolbar"
    build_toolbar.set_anchors_preset(Control.PRESET_CENTER_BOTTOM)
    build_toolbar.anchor_left = 0.0
    build_toolbar.anchor_right = 1.0
    build_toolbar.anchor_top = 1.0
    build_toolbar.anchor_bottom = 1.0
    build_toolbar.offset_top = -84.0
    build_toolbar.offset_bottom = -12.0
    build_toolbar.alignment = BoxContainer.ALIGNMENT_CENTER
    build_toolbar.add_theme_constant_override("separation", 10)
    add_child(build_toolbar)
    for entry in [["farm", "Ферма 2×2"], ["mine", "Шахта 2×3"], ["factory", "Завод 3×2"]]:
        var button := Button.new()
        button.text = str(entry[1])
        button.custom_minimum_size = Vector2(116, 56)
        var kind: String = str(entry[0])
        button.pressed.connect(func() -> void:
            world.choose_build(kind)
            info.text = "Выберите участок: %s" % kind
        )
        build_toolbar.add_child(button)
    var confirm := Button.new()
    confirm.text = "Построить"
    confirm.custom_minimum_size = Vector2(112, 56)
    confirm.pressed.connect(_place_building)
    build_toolbar.add_child(confirm)
    var cancel := Button.new()
    cancel.text = "Отмена"
    cancel.custom_minimum_size = Vector2(92, 56)
    cancel.pressed.connect(func() -> void:
        world.cancel_build()
        info.text = "Строительство отменено"
    )
    build_toolbar.add_child(cancel)

func show_build_preview(result: Dictionary) -> void:
    if result.get("ok", false):
        info.text = "Участок подходит · нажмите Построить"
    else:
        var messages := {
            "road_overlap": "Нельзя строить на дороге",
            "occupied": "Участок занят",
            "no_road_access": "Нужен подъезд к дороге",
            "outside_explored_area": "Территория ещё не открыта",
            "invalid_size": "Неверный размер участка"
        }
        info.text = str(messages.get(str(result.get("reason", "")), "Участок не подходит"))

func _place_building() -> void:
    var result: Dictionary = world.place_building()
    if result.get("ok", false):
        info.text = "Здание размещено (локальный прототип)"
    else:
        show_build_preview(result)
