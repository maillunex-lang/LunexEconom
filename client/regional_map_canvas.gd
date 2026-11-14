extends Control
## The map's bounded drawing and gesture surface, inside the scroll-safe panel.
var owner_panel: Control

func _ready() -> void:
    mouse_filter = Control.MOUSE_FILTER_STOP
    clip_contents = true

func _draw() -> void:
    if owner_panel != null:
        owner_panel.draw_map(self)

func _gui_input(event: InputEvent) -> void:
    if owner_panel != null:
        owner_panel.map_input(event)
        accept_event()
