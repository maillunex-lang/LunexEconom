extends RefCounted
## Shared Forest Glass tokens. Design sizes are logical Godot canvas units.
const COLORS := {
    "background": Color("0a201b"),
    "panel": Color("173a30"),
    "panel_secondary": Color("22483b"),
    "accent": Color("b7efa5"),
    "text": Color("eef5e8"),
    "muted": Color("a1b9ad"),
    "border": Color("386c57"),
    "danger": Color("f0a29b"),
    "focus": Color("b7efa5"),
    "success": Color("7bc67e"),
    "warning": Color("e9b85c"),
}
const METRICS := {
    "touch_dp": 48.0,
    "body_sp": 16.0,
    "headline_sp": 24.0,
    "title_sp": 20.0,
    "gap": 12.0,
    "padding": 16.0,
    "radius": 18.0,
    "caption_sp": 12.0,
    "spacing_sm": 8.0,
    "spacing_lg": 24.0,
}

static func scale_for(window_size: Vector2, density: float = 1.0) -> float:
    # Preserve 16sp and 48dp targets while expanding at larger logical viewports.
    # OS dpi / 160 is useful for physical pixels, but canvas_items already scales
    # to the Android drawable viewport; don't double-apply the phone DPI.
    var candidate: float = minf(window_size.x / 1280.0, window_size.y / 720.0)
    return clampf(maxf(candidate, 1.0), 1.0, 1.5)

static func touch_size(window_size: Vector2, density: float = 1.0) -> float:
    return ceilf(METRICS.touch_dp * scale_for(window_size, density))

static func rounded(fill: Color, radius: int = 18, border: Color = COLORS.border, width: int = 1) -> StyleBoxFlat:
    var style := StyleBoxFlat.new()
    style.bg_color = fill
    style.border_color = border
    style.set_border_width_all(width)
    style.set_corner_radius_all(radius)
    style.set_content_margin_all(10)
    return style

static func create_theme(window_size: Vector2 = Vector2(1280,720)) -> Theme:
    var scale := scale_for(window_size)
    var theme := Theme.new()
    var font := SystemFont.new()
    font.font_names = PackedStringArray(["Noto Sans", "DejaVu Sans", "sans-serif"])
    theme.default_font = font
    theme.default_font_size = roundi(METRICS.body_sp * scale)
    for node_type in ["Label", "Button", "LineEdit", "CheckBox", "OptionButton", "ItemList", "TextEdit", "PopupMenu"]:
        theme.set_color("font_color",node_type,COLORS.text)
        theme.set_font_size("font_size",node_type,roundi(METRICS.body_sp * scale))
    theme.set_color("font_placeholder_color", "LineEdit", COLORS.muted)
    theme.set_color("font_focus_color", "Button", COLORS.accent)
    theme.set_color("font_hover_color", "Button", COLORS.accent)
    theme.set_color("font_pressed_color", "Button", COLORS.background)
    theme.set_color("font_disabled_color", "Button", COLORS.muted)
    for node_type in ["Panel", "PanelContainer"]:
        theme.set_stylebox("panel",node_type,rounded(COLORS.panel,roundi(METRICS.radius*scale)))
    for name in {"normal":COLORS.panel_secondary, "hover":COLORS.border, "pressed":COLORS.accent, "disabled":COLORS.panel}.keys():
        theme.set_stylebox(name,"Button",rounded({"normal":COLORS.panel_secondary, "hover":COLORS.border, "pressed":COLORS.accent, "disabled":COLORS.panel}[name],roundi(12*scale)))
    theme.set_stylebox("focus","Button",rounded(Color.TRANSPARENT,roundi(12*scale),COLORS.focus,2))
    theme.set_constant("h_separation", "GridContainer", roundi(12*scale))
    for name in ["normal", "focus", "read_only"]:
        theme.set_stylebox(name,"LineEdit",rounded(COLORS.background,roundi(10*scale),COLORS.focus if name == "focus" else COLORS.border))
    theme.set_stylebox("normal","TextEdit",rounded(COLORS.background))
    theme.set_color("font_color", "CheckBox", COLORS.text)
    theme.set_color("font_disabled_color", "LineEdit", COLORS.muted)
    theme.set_stylebox("panel","ItemList",rounded(COLORS.panel_secondary))
    theme.set_stylebox("panel","PopupPanel",rounded(COLORS.panel))
    theme.set_stylebox("panel","AcceptDialog",rounded(COLORS.panel))
    theme.set_constant("separation","VBoxContainer",roundi(METRICS.gap * scale))
    theme.set_constant("separation","HBoxContainer",roundi(METRICS.gap * scale))
    return theme

static func apply_touch(node: Node, window_size: Vector2) -> void:
    if node is Button or node is LineEdit or node is CheckBox or node is OptionButton:
        node.custom_minimum_size.y = maxf(node.custom_minimum_size.y, touch_size(window_size))
        node.custom_minimum_size.x = maxf(node.custom_minimum_size.x, touch_size(window_size))
    for child in node.get_children():
        apply_touch(child,window_size)
