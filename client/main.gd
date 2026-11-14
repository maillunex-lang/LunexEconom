extends Control

@onready var status_label: Label = $SafeArea/Centering/Center/Status
@onready var retry_button: Button = $SafeArea/Centering/Center/Retry
@onready var safe_area: MarginContainer = $SafeArea
@onready var center: VBoxContainer = $SafeArea/Centering/Center
@onready var title_label: Label = $SafeArea/Centering/Center/Title
var request: HTTPRequest

func _ready() -> void:
    if OS.has_feature("mobile"):
        DisplayServer.screen_set_orientation(DisplayServer.SCREEN_SENSOR_LANDSCAPE)
    get_viewport().size_changed.connect(_update_layout)
    call_deferred("_update_layout")
    retry_button.pressed.connect(_check_server)
    request = HTTPRequest.new()
    add_child(request)
    request.request_completed.connect(_on_request_completed)
    _check_server()

func _check_server() -> void:
    status_label.text = "Подключение к тестовому серверу..."
    # Development-only loopback. Android builds will use a separately configured HTTPS endpoint.
    var err := request.request("http://127.0.0.1:18761/health")
    if err != OK:
        status_label.text = "Сервер недоступен (код %s)" % err

func _on_request_completed(_result: int, code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
    if code != 200:
        status_label.text = "Сервер не подключён. Код HTTP: %s" % code
        return
    var parsed = JSON.parse_string(body.get_string_from_utf8())
    if parsed is Dictionary and parsed.get("ok", false):
        status_label.text = "Сервер Foundation доступен"
    else:
        status_label.text = "Некорректный ответ сервера"
func _update_layout() -> void:
    # Godot's safe rect is in physical display pixels; Control sizes are in
    # viewport coordinates. Convert before applying margins.
    var view := get_viewport_rect().size
    var screen := DisplayServer.screen_get_size()
    var safe := DisplayServer.get_display_safe_area()
    var left := 24.0
    var top := 18.0
    var right := 24.0
    var bottom := 18.0
    if OS.has_feature("mobile") and screen.x > 0 and screen.y > 0 and safe.size.x > 0 and safe.size.y > 0:
        var sx := view.x / float(screen.x)
        var sy := view.y / float(screen.y)
        left = maxf(left, float(safe.position.x) * sx + 12.0)
        top = maxf(top, float(safe.position.y) * sy + 12.0)
        right = maxf(right, float(screen.x - safe.end.x) * sx + 12.0)
        bottom = maxf(bottom, float(screen.y - safe.end.y) * sy + 12.0)
    safe_area.add_theme_constant_override("margin_left", int(left))
    safe_area.add_theme_constant_override("margin_top", int(top))
    safe_area.add_theme_constant_override("margin_right", int(right))
    safe_area.add_theme_constant_override("margin_bottom", int(bottom))
    var usable_width := maxf(240.0, view.x - left - right)
    center.custom_minimum_size.x = minf(720.0, usable_width * 0.9)
    # Keep touch controls and text legible even on compact landscape phones.
    var compact := view.y < 520.0
    center.add_theme_constant_override("separation", 12 if compact else 20)
    title_label.add_theme_font_size_override("font_size", 30 if compact else 38)
    retry_button.custom_minimum_size.y = 64.0 if compact else 76.0
