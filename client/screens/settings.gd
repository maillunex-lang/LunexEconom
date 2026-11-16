extends Control
signal back_requested
signal reset_tutorial_requested
const Strings = preload("res://i18n/strings.gd")
const Forest = preload("res://theme/forest_glass.gd")
var stack: VBoxContainer

func _ready() -> void:
    set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    var panel := PanelContainer.new()
    panel.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    add_child(panel)
    stack = VBoxContainer.new()
    panel.add_child(stack)
    var title := Label.new()
    title.text = Strings.get_text("main.menu.settings")
    stack.add_child(title)
    var back := Button.new()
    back.text = Strings.get_text("button.back")
    back.pressed.connect(func(): back_requested.emit())
    stack.add_child(back)
    var reset := Button.new()
    reset.text = preload("res://enterprises/strings.gd").get_text("tutorial.reset")
    reset.name = "ResetTutorial"
    reset.custom_minimum_size = Vector2(220, 48)
    reset.pressed.connect(func(): reset_tutorial_requested.emit())
    stack.add_child(reset)
    for key in ["settings.language","settings.sound","settings.music","settings.graphics"]:
        var entry := Label.new()
        entry.text = Strings.get_text(key)
        stack.add_child(entry)

func resize_ui(view_size: Vector2) -> void:
    Forest.apply_touch(self,view_size)