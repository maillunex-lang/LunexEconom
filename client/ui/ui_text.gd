extends Label
## Long descriptions have a bounded preview; tap to expand. Monetary labels
## and buttons should not use this component.
@export_range(1, 10) var preview_lines := 3
var expanded := false
func _ready() -> void:
    autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
    max_lines_visible = preview_lines
    mouse_filter = Control.MOUSE_FILTER_STOP
func _gui_input(event: InputEvent) -> void:
    if event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_LEFT:
        expanded = not expanded
        max_lines_visible = -1 if expanded else preview_lines
        accept_event()
