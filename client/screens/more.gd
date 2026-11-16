extends Control
signal navigate(target: String)
signal logout_requested
const Words = preload("res://enterprises/strings.gd")
const Forest = preload("res://theme/forest_glass.gd")

func _ready() -> void:
    set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    var panel := PanelContainer.new()
    panel.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    add_child(panel)
    var items := VBoxContainer.new()
    panel.add_child(items)
    var title := Label.new()
    title.text = Words.get_text("nav.more")
    items.add_child(title)
    for entry in [
        ["nav.more.settings", "settings"],
        ["nav.more.updates", "updates"],
        ["nav.more.logout", "logout"]
    ]:
        var button := Button.new()
        button.text = Words.get_text(str(entry[0]))
        button.custom_minimum_size = Vector2(160, 48)
        button.pressed.connect(_activate.bind(str(entry[1])))
        items.add_child(button)

func _activate(target: String) -> void:
    if target == "logout":
        logout_requested.emit()
    else:
        navigate.emit(target)

func resize_ui(view_size: Vector2) -> void:
    Forest.apply_touch(self,view_size)
