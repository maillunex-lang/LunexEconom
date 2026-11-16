extends Button
## Semantic button with explicit normal/hover/pressed/disabled/focus states.
const Forest = preload("res://theme/forest_glass.gd")
@export_enum("primary", "secondary", "danger") var variant := "primary":
    set(value):
        variant = value
        if is_inside_tree(): _paint()

func _ready() -> void:
    _paint()

func _paint() -> void:
    custom_minimum_size = Vector2(48, maxf(48.0, custom_minimum_size.y))
    var bg: Color = Forest.COLORS.accent if variant == "primary" else (Forest.COLORS.danger if variant == "danger" else Forest.COLORS.panel_secondary)
    var ink: Color = Forest.COLORS.background if variant != "secondary" else Forest.COLORS.text
    add_theme_color_override("font_color",ink)
    add_theme_color_override("font_hover_color",ink)
    add_theme_color_override("font_pressed_color",ink)
    add_theme_color_override("font_disabled_color",Forest.COLORS.muted)
    for state in ["normal", "hover", "pressed", "disabled"]:
        var fill: Color = bg.lightened(0.09) if state == "hover" else (bg.darkened(0.14) if state == "pressed" else (bg.darkened(0.45) if state == "disabled" else bg))
        add_theme_stylebox_override(state,Forest.rounded(fill,12,Forest.COLORS.border,1))
    add_theme_stylebox_override("focus",Forest.rounded(Color.TRANSPARENT,12,Forest.COLORS.focus,2))
