extends PanelContainer
## Private chronological company feed. UI reads API only; never mutates game state.
signal close_requested
signal refresh_requested

var _rows: VBoxContainer
var _footer: Label


func _button(title: String, callback: Callable) -> Button:
    var button := Button.new()
    button.text = title
    button.custom_minimum_size = Vector2(110, 36)
    button.mouse_filter = Control.MOUSE_FILTER_IGNORE # world_screen owns the touch router
    button.add_theme_font_size_override("font_size", 15)
    button.pressed.connect(callback)
    return button


func _ready() -> void:
    name = "CompanyFeedPanel"
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
    title.text = "📜 События компании"
    title.add_theme_font_size_override("font_size", 19)
    title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    header.add_child(title)
    header.add_child(_button("Закрыть ×", func(): close_requested.emit()))
    var scroll := ScrollContainer.new()
    scroll.custom_minimum_size = Vector2(0, 110)
    scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
    body.add_child(scroll)
    _rows = VBoxContainer.new()
    _rows.add_theme_constant_override("separation", 5)
    _rows.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    scroll.add_child(_rows)
    var bottom := HBoxContainer.new()
    body.add_child(bottom)
    _footer = Label.new()
    _footer.add_theme_font_size_override("font_size", 14)
    _footer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    bottom.add_child(_footer)
    bottom.add_child(_button("Обновить", func(): refresh_requested.emit()))
    render({"events": []})
    hide()


func show_loading() -> void:
    _footer.text = "Загрузка..."


func show_error() -> void:
    _footer.text = "Ошибка сети. Нажмите «Обновить»."


func render(data: Dictionary) -> void:
    for child in _rows.get_children():
        child.queue_free()
    var events = data.get("events", [])
    if not events is Array or events.is_empty():
        var empty := Label.new()
        empty.text = "Пока нет событий"
        _rows.add_child(empty)
    else:
        # Most recent first. A fresh request with after=0 is used on every open.
        for index in range(events.size() - 1, -1, -1):
            var entry = events[index]
            if not entry is Dictionary:
                continue
            var item := Label.new()
            item.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
            item.add_theme_font_size_override("font_size", 15)
            var month = entry.get("month_index", null)
            var prefix := "Месяц %d · " % (int(month) + 1) if month != null else ""
            item.text = "• " + prefix + str(entry.get("title", "Событие"))
            _rows.add_child(item)
    _footer.text = "Записей: %d" % int(data.get("total", 0))
