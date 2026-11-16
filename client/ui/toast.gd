extends PanelContainer
## Use inside a safe-area parent; place above navigation with bottom_clearance.
const Strings = preload("res://i18n/strings.gd")
var label: Label
var timer: Timer
var bottom_clearance := 76.0

func _ready() -> void:
    mouse_filter = Control.MOUSE_FILTER_IGNORE
    set_anchors_and_offsets_preset(Control.PRESET_BOTTOM_WIDE)
    label = Label.new()
    label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    add_child(label)
    timer = Timer.new()
    timer.one_shot = true
    timer.timeout.connect(hide)
    add_child(timer)
    hide()

func show_text(key: String) -> void:
    label.text = Strings.get_text(key)
    offset_bottom = -bottom_clearance
    offset_top = offset_bottom - maxf(56.0,get_combined_minimum_size().y)
    show()
    timer.start(3.5)
