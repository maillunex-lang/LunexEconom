extends Control
## At >= 1600 canvas px show both columns, else stacked navigation with Back.
signal back_requested
const Words = preload("res://i18n/strings.gd")
var list_host: VBoxContainer
var details_host: VBoxContainer
var _back: Button
var _split: HBoxContainer
var _show_detail := false
func _ready() -> void:
    _split = HBoxContainer.new()
    _split.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    add_child(_split)
    list_host = VBoxContainer.new()
    list_host.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    list_host.size_flags_stretch_ratio = 1.0
    _split.add_child(list_host)
    details_host = VBoxContainer.new()
    details_host.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    details_host.size_flags_stretch_ratio = 1.25
    _split.add_child(details_host)
    _back = Button.new()
    _back.text = Words.get_text("ui.back")
    _back.custom_minimum_size = Vector2(48,48)
    _back.pressed.connect(func(): show_details(false); back_requested.emit())
    details_host.add_child(_back)
    resized.connect(func(): refresh_width(size.x))
    call_deferred("refresh_width",size.x)
func show_details(active: bool = true) -> void:
    _show_detail = active
    refresh_width(size.x)
func refresh_width(width: float) -> void:
    var wide := width >= 1600.0
    list_host.visible = wide or not _show_detail
    details_host.visible = wide or _show_detail
    _back.visible = not wide
    _split.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
