extends PanelContainer
## The host controls the bottom offset above its navigation bar.
const Words = preload("res://i18n/strings.gd")
var _message: Label
var _timer: Timer
func _ready() -> void:
    mouse_filter = Control.MOUSE_FILTER_IGNORE
    _message = Label.new()
    _message.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    add_child(_message)
    _timer = Timer.new()
    _timer.one_shot = true
    _timer.timeout.connect(hide)
    add_child(_timer)
    hide()
func show_message(key: String, nav_height: float = 0.0) -> void:
    _message.text = Words.get_text(key)
    set_anchors_and_offsets_preset(Control.PRESET_BOTTOM_WIDE)
    offset_bottom = -nav_height - 12.0
    offset_top = offset_bottom - maxf(56.0, get_combined_minimum_size().y)
    show()
    _timer.start(3.5)
