extends VBoxContainer
## Labeled editable input. Never stores credentials or dispatches requests.
const Words = preload("res://i18n/strings.gd")
const Forest = preload("res://theme/forest_glass.gd")
var caption: Label
var field: LineEdit
var error: Label
func _ready() -> void:
    caption = Label.new()
    caption.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    add_child(caption)
    field = LineEdit.new()
    field.custom_minimum_size = Vector2(48,48)
    field.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    add_child(field)
    error = Label.new()
    error.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    error.add_theme_color_override("font_color",Forest.COLORS.danger)
    error.hide()
    add_child(error)
func configure(caption_key: String, hint_key: String) -> void:
    caption.text = Words.get_text(caption_key)
    field.placeholder_text = Words.get_text(hint_key)
func set_error(key: String = "") -> void:
    error.visible = not key.is_empty()
    error.text = Words.get_text(key) if not key.is_empty() else ""
    if not key.is_empty():
        field.add_theme_stylebox_override("normal",Forest.rounded(Forest.COLORS.background,8,Forest.COLORS.danger,2))
    else:
        field.remove_theme_stylebox_override("normal")
