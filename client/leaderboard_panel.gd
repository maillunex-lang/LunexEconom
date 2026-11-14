extends PanelContainer
## Forest Glass: read-only company rankings, touch-friendly in landscape.
signal close_requested
signal sort_requested(sort_by: String)

var _sort: String = "networth"
var _rows: VBoxContainer
var _footer: Label
var _filters: Dictionary = {}


func _button(title: String, callback: Callable) -> Button:
    var button := Button.new()
    button.text = title
    button.custom_minimum_size = Vector2(100, 36)
    button.mouse_filter = Control.MOUSE_FILTER_IGNORE # handled by world_screen._hit_ui_button
    button.add_theme_font_size_override("font_size", 15)
    button.pressed.connect(callback)
    return button


func _ready() -> void:
    name = "LeaderboardPanel"
    mouse_filter = Control.MOUSE_FILTER_STOP
    var background := StyleBoxFlat.new()
    background.bg_color = Color(0.08, 0.17, 0.15, 0.97)
    background.border_color = Color("#567664")
    background.set_border_width_all(1)
    background.set_corner_radius_all(16)
    background.set_content_margin_all(10)
    add_theme_stylebox_override("panel", background)
    var body := VBoxContainer.new()
    body.add_theme_constant_override("separation", 5)
    add_child(body)
    var header := HBoxContainer.new()
    body.add_child(header)
    var title := Label.new()
    title.text = "🏆 Рейтинг компаний"
    title.add_theme_font_size_override("font_size", 19)
    title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    header.add_child(title)
    header.add_child(_button("Закрыть ×", func(): close_requested.emit()))
    var filters := HBoxContainer.new()
    filters.add_theme_constant_override("separation", 6)
    body.add_child(filters)
    for entry in [["networth", "Капитал"], ["income", "Выручка"], ["buildings", "Здания"]]:
        var key: String = entry[0]
        var button := _button(entry[1], func(): choose_sort(key))
        button.size_flags_horizontal = Control.SIZE_EXPAND_FILL
        filters.add_child(button)
        _filters[key] = button
    var scroll := ScrollContainer.new()
    scroll.custom_minimum_size = Vector2(0, 85)
    scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
    body.add_child(scroll)
    _rows = VBoxContainer.new()
    _rows.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    _rows.add_theme_constant_override("separation", 5)
    scroll.add_child(_rows)
    _footer = Label.new()
    _footer.add_theme_font_size_override("font_size", 15)
    body.add_child(_footer)
    _highlight()
    render({"top": [], "me": null})
    hide()


func choose_sort(sort_by: String) -> void:
    if not _filters.has(sort_by):
        return
    _sort = sort_by
    _highlight()
    sort_requested.emit(sort_by)


func _highlight() -> void:
    for key in _filters:
        var button: Button = _filters[key]
        button.modulate = Color("#f0d08f") if key == _sort else Color.WHITE


func show_loading() -> void:
    _footer.text = "Загрузка рейтинга..."


func show_error() -> void:
    _footer.text = "Не удалось загрузить рейтинг. Повторите выбор категории."


func render(data: Dictionary) -> void:
    for child in _rows.get_children():
        child.queue_free()
    var top = data.get("top", [])
    if not top is Array or top.is_empty():
        var empty := Label.new()
        empty.text = "Пока нет компаний"
        _rows.add_child(empty)
    else:
        for entry in top:
            if not entry is Dictionary:
                continue
            var row := Label.new()
            row.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
            row.add_theme_font_size_override("font_size", 16)
            var owner := str(entry.get("name", "Компания"))
            var npc_mark := " · NPC" if bool(entry.get("npc", false)) else ""
            var number := int(entry.get(_sort, 0))
            var suffix := " зданий" if _sort == "buildings" else " ₽"
            row.text = "%d. %s%s   %d%s" % [int(entry.get("rank", 0)), owner, npc_mark, number, suffix]
            _rows.add_child(row)
    var mine = data.get("me", null)
    if mine is Dictionary:
        _footer.text = "Ваше место: %d из %d" % [int(mine.get("rank", 0)), int(data.get("total", 0))]
    else:
        _footer.text = "Данные вашей компании отсутствуют"
