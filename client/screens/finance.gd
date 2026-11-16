extends Control
const Words = preload("res://enterprises/strings.gd")
const Forest = preload("res://theme/forest_glass.gd")

func _ready() -> void:
    set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    var panel := PanelContainer.new()
    panel.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    add_child(panel)
    var label := Label.new()
    label.text = Words.get_text("nav.finance") + " · " + Words.get_text("nav.soon")
    label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
    label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
    panel.add_child(label)

func resize_ui(view_size: Vector2) -> void:
    Forest.apply_touch(self,view_size)
