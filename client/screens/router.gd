extends Control
signal changed(screen_name: String)
const SCREENS := ["login", "headquarters", "settings", "updates", "map"]
var current := ""
var history: Array[String] = []
var host: Control
var instances := {}

func _ready() -> void:
    set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    host = Control.new()
    host.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    add_child(host)

func register_screen(name: String, screen: Control) -> void:
    assert(SCREENS.has(name))
    instances[name] = screen
    host.add_child(screen)
    screen.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    screen.hide()

func go(name: String, remember: bool = true) -> void:
    if not instances.has(name):
        push_warning("Unknown screen: " + name)
        return
    if current == name:
        return
    if remember and not current.is_empty():
        history.append(current)
    for key in instances:
        instances[key].visible = key == name
    current = name
    changed.emit(name)

func back() -> bool:
    if history.is_empty():
        return false
    go(history.pop_back(),false)
    return true

func reset(name: String) -> void:
    history.clear()
    go(name,false)
