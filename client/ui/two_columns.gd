extends Control
## Reusable master/detail frame; narrow screens use detail stack and Back.
const Strings = preload("res://i18n/strings.gd")
var columns: HBoxContainer
var list_area: VBoxContainer
var detail_area: VBoxContainer
var back_button: Button
var showing_detail := false
var _wide := false

func _ready() -> void:
    set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    columns = HBoxContainer.new()
    columns.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    add_child(columns)
    list_area = VBoxContainer.new()
    list_area.name = "List"
    list_area.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    columns.add_child(list_area)
    detail_area = VBoxContainer.new()
    detail_area.name = "Details"
    detail_area.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    columns.add_child(detail_area)
    back_button = Button.new()
    back_button.text = Strings.get_text("ui.back")
    back_button.custom_minimum_size = Vector2(48,48)
    back_button.pressed.connect(func(): show_list())
    detail_area.add_child(back_button)
    refresh_size(get_viewport_rect().size)

func refresh_size(view_size: Vector2) -> void:
    _wide = view_size.x >= 1600.0
    list_area.visible = _wide or not showing_detail
    detail_area.visible = _wide or showing_detail
    back_button.visible = not _wide

func show_detail() -> void:
    showing_detail = true
    refresh_size(get_viewport_rect().size)

func show_list() -> void:
    showing_detail = false
    refresh_size(get_viewport_rect().size)
