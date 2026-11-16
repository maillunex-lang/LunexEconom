extends PanelContainer
## Flexible card; caller sets max width through resize_for().
const Forest = preload("res://theme/forest_glass.gd")
@export var max_width_dp := 720.0
func _ready() -> void:
    add_theme_stylebox_override("panel",Forest.rounded(Forest.COLORS.panel,18))
func resize_for(width: float) -> void:
    custom_minimum_size.x = minf(max_width_dp, maxf(0.0, width))
