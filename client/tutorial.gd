extends PanelContainer
## Lightweight per-account onboarding. No tokens or personal data stored.
## Server-confirmed events only, no input capture outside this hint card.

const EVENTS := ["farm_built", "economy_opened", "city_opened", "contracts_opened"]
const HINTS := [
    "Постройте свою первую ферму. Выберите «Строить» и участок.",
    "Откройте «Экономику», чтобы посмотреть производство и доход.",
    "Посмотрите «Город»: жители, бюджет и управление.",
    "Загляните в «Контракты» через вкладку «Экономика»."
]
var account_path := ""
var finished: Dictionary = {}
var skipped := false
var _host: Control
var _title: Label
var _hint: Label
var _skip_button: Button

func setup(host: Control, account: String) -> void:
    _host = host
    if account.is_empty():
        host.get_node("UIOverlay").add_child(self)
        hide()
        return
    account_path = "user://tutorial_%s.json" % account.sha256_text()
    _restore()
    var container := VBoxContainer.new()
    container.add_theme_constant_override("separation", 4)
    add_child(container)
    var header := HBoxContainer.new()
    container.add_child(header)
    _title = Label.new()
    _title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    _title.add_theme_font_size_override("font_size", 16)
    header.add_child(_title)
    _skip_button = Button.new()
    _skip_button.text = "Пропустить"
    _skip_button.custom_minimum_size = Vector2(115, 36)
    # All Android taps are routed by world_screen.gd.
    _skip_button.mouse_filter = Control.MOUSE_FILTER_IGNORE
    _skip_button.pressed.connect(skip)
    header.add_child(_skip_button)
    var scroll := ScrollContainer.new()
    scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
    scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
    container.add_child(scroll)
    _hint = Label.new()
    _hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    _hint.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    _hint.add_theme_font_size_override("font_size", 15)
    scroll.add_child(_hint)
    add_theme_stylebox_override("panel", host._style())
    mouse_filter = Control.MOUSE_FILTER_STOP
    host.get_node("UIOverlay").add_child(self)
    if host.contracts_panel != null:
        host.contracts_panel.visibility_changed.connect(_on_contract_visibility)
    get_viewport().size_changed.connect(_layout)
    _render()
    call_deferred("_layout")

func _restore() -> void:
    if not FileAccess.file_exists(account_path):
        return
    var file := FileAccess.open(account_path, FileAccess.READ)
    if file == null:
        return
    var data = JSON.parse_string(file.get_as_text())
    file.close()
    if data is Dictionary:
        skipped = bool(data.get("skipped", false))
        var progress = data.get("completed", {})
        if progress is Dictionary:
            for event in EVENTS:
                if bool(progress.get(event, false)):
                    finished[event] = true

func _persist() -> bool:
    if account_path.is_empty():
        return false
    var file := FileAccess.open(account_path, FileAccess.WRITE)
    if file == null:
        push_warning("Tutorial progress cannot be saved locally")
        return false
    file.store_string(JSON.stringify({"skipped": skipped, "completed": finished}))
    var saved := file.get_error() == OK
    file.close()
    return saved

func _first_incomplete() -> int:
    for index in EVENTS.size():
        if not bool(finished.get(EVENTS[index], false)):
            return index
    return EVENTS.size()

func _render() -> void:
    if _title == null or _hint == null:
        return
    var index := _first_incomplete()
    if skipped or index == EVENTS.size():
        hide()
        return
    _title.text = "Подсказка · %d/%d" % [index + 1, EVENTS.size()]
    _hint.text = HINTS[index]
    show()

func notify(event: String) -> void:
    if account_path.is_empty() or skipped or not EVENTS.has(event) or finished.has(event):
        return
    finished[event] = true
    _persist()
    _render()

func skip() -> void:
    if account_path.is_empty():
        return
    skipped = true
    _persist()
    hide()

func _on_contract_visibility() -> void:
    if _host.contracts_panel != null and _host.contracts_panel.visible:
        notify("contracts_opened")

func _layout() -> void:
    if _host == null or _title == null:
        return
    var area: Rect2 = _host.panel_rect(_host.build_toolbar.position.y)
    var width := minf(365.0, area.size.x)
    size = Vector2(width, minf(115.0, area.size.y))
    custom_minimum_size = size
    position = Vector2(area.end.x - width, area.position.y + 4)
