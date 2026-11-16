extends RefCounted
## Forest Glass reusable controls. All visible copy comes from the RU catalogue.
const Components = preload("res://ui/components.gd")
const Forest = preload("res://theme/forest_glass.gd")
const Strings = preload("res://i18n/strings.gd")

static func button(key: String, kind: String = "primary") -> Button:
    var result := Button.new()
    result.text = Strings.get_text(key)
    result.custom_minimum_size = Vector2(48,48)
    result.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    var fill: Color = Forest.COLORS.accent if kind == "primary" else (Forest.COLORS.danger if kind == "danger" else Forest.COLORS.panel_secondary)
    var fg: Color = Forest.COLORS.background if kind != "secondary" else Forest.COLORS.text
    result.add_theme_color_override("font_color",fg)
    result.add_theme_color_override("font_pressed_color",fg)
    result.add_theme_color_override("font_hover_color",fg)
    result.add_theme_color_override("font_disabled_color",Forest.COLORS.muted)
    result.add_theme_stylebox_override("normal",Forest.rounded(fill,12))
    result.add_theme_stylebox_override("hover",Forest.rounded(fill.lightened(0.07),12))
    result.add_theme_stylebox_override("pressed",Forest.rounded(fill.darkened(0.15),12))
    result.add_theme_stylebox_override("disabled",Forest.rounded(Forest.COLORS.panel,12))
    result.add_theme_stylebox_override("focus",Forest.rounded(Color.TRANSPARENT,12,Forest.COLORS.focus,2))
    return result

static func field(key: String, secret: bool = false) -> VBoxContainer:
    var box := VBoxContainer.new()
    var caption := Label.new()
    caption.text = Strings.get_text(key)
    caption.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    box.add_child(caption)
    var edit := LineEdit.new()
    edit.name = "Edit"
    edit.placeholder_text = Strings.get_text(key)
    edit.secret = secret
    edit.custom_minimum_size = Vector2(48,48)
    box.add_child(edit)
    var error := Label.new()
    error.name = "Error"
    error.hide()
    error.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    error.add_theme_color_override("font_color",Forest.COLORS.danger)
    box.add_child(error)
    return box

static func set_field_error(field_box: VBoxContainer, key: String = "") -> void:
    var label: Label = field_box.get_node("Error")
    label.visible = not key.is_empty()
    if not key.is_empty():
        label.text = Strings.get_text(key)

static func card() -> PanelContainer:
    var result := PanelContainer.new()
    result.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    result.add_theme_stylebox_override("panel",Forest.rounded(Forest.COLORS.panel,18))
    return result

static func wrap(key: String, limit: int = 3) -> Label:
    var result := Label.new()
    result.text = Strings.get_text(key)
    result.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    result.max_lines_visible = limit
    result.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
    result.mouse_filter = Control.MOUSE_FILTER_STOP
    result.gui_input.connect(func(event: InputEvent):
        if event is InputEventMouseButton and event.pressed:
            result.max_lines_visible = 0 if result.max_lines_visible > 0 else limit
            result.text_overrun_behavior = TextServer.OVERRUN_NO_TRIMMING if result.max_lines_visible == 0 else TextServer.OVERRUN_TRIM_ELLIPSIS
    )
    return result

static func empty_state(symbol: String, title_key: String, help_key: String, action_key: String) -> VBoxContainer:
    var box := VBoxContainer.new()
    var icon := Label.new()
    icon.text = symbol
    icon.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
    box.add_child(icon)
    for key in [title_key, help_key]:
        var label := Components.wrap(key)
        label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
        box.add_child(label)
    var action := button(action_key)
    action.name = "Action"
    box.add_child(action)
    return box

static func loading(retry_key: String = "update.screen.retry") -> VBoxContainer:
    var box := VBoxContainer.new()
    var label := Components.wrap("loading")
    box.add_child(label)
    var retry := button(retry_key,"secondary")
    retry.name = "Retry"
    box.add_child(retry)
    return box

static func confirm(title_key: String, description_key: String) -> ConfirmationDialog:
    var dialog := ConfirmationDialog.new()
    dialog.title = Strings.get_text(title_key)
    dialog.dialog_text = Strings.get_text(description_key)
    dialog.ok_button_text = Strings.get_text("update.screen.button.ok")
    dialog.cancel_button_text = Strings.get_text("update.screen.button.cancel")
    return dialog
