extends PanelContainer
signal target_requested(target: String)
const Words = preload("res://enterprises/strings.gd")
const Forest = preload("res://theme/forest_glass.gd")
const MAIN := ["headquarters", "map", "enterprises", "finance", "more"]
const DISPLAY := ["headquarters", "map", "enterprises", "settings", "finance", "more"]
const LABELS := ["nav.headquarters", "nav.map", "nav.enterprises", "nav.finance", "nav.more"]
var buttons: Dictionary = {}
var bar: HBoxContainer
var _current := ""
var _tutorial_step := -1

func _ready() -> void:
    mouse_filter = Control.MOUSE_FILTER_STOP
    bar = HBoxContainer.new()
    bar.name = "NavigationItems"
    add_child(bar)
    for i in range(MAIN.size()):
        var target: String = MAIN[i]
        var button := Button.new()
        button.name = target.capitalize()
        button.text = Words.get_text(LABELS[i])
        button.size_flags_horizontal = Control.SIZE_EXPAND_FILL
        button.custom_minimum_size = Vector2(88, 48)
        button.pressed.connect(func(): target_requested.emit(target))
        bar.add_child(button)
        buttons[target] = button

func change_screen(screen: String) -> void:
    _current = screen
    visible = DISPLAY.has(screen)
    _highlight()

func focus_tutorial(step_index: int) -> void:
    _tutorial_step = step_index
    _highlight()

func _highlight() -> void:
    var active := "more" if _current == "settings" else _current
    var target := ""
    if _tutorial_step in [0, 1]:
        target = "headquarters"
    elif _tutorial_step in [2, 3, 5, 8, 11]:
        target = "map"
    elif _tutorial_step >= 4:
        target = "enterprises"
    for key in buttons:
        var button: Button = buttons[key]
        var highlighted: bool = str(key) == target and str(key) != active
        button.self_modulate = Color("ffdb92") if highlighted else (Color("a6e3c2") if key == active else Color.WHITE)
        button.add_theme_color_override("font_color", Color("174a33") if key == active or highlighted else Color("edf5ec"))

func refresh_size(view_size: Vector2) -> void:
    Forest.apply_touch(self, view_size)
    for button in buttons.values():
        button.custom_minimum_size.y = maxf(48.0, Forest.touch_size(view_size))