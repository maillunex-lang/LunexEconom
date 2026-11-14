extends Control
## One series drawn without extra libraries. A touch shows the value under the finger.

var points: Array = []
var value_key := "price"
var hover := -1
var _tip := ""


func _ready() -> void:
	custom_minimum_size = Vector2(280, 160)
	mouse_filter = Control.MOUSE_FILTER_STOP


func set_points(rows: Array, key: String) -> void:
	points = rows
	value_key = key
	hover = -1
	_tip = ""
	queue_redraw()


func _index_at(local_x: float) -> int:
	if points.is_empty():
		return -1
	var span := maxf(size.x - 36.0, 1.0)
	var t := clampf((local_x - 28.0) / span, 0.0, 1.0)
	return clampi(int(round(t * float(points.size() - 1))), 0, points.size() - 1)


func _gui_input(event: InputEvent) -> void:
	var pos := Vector2.ZERO
	var pressed := false
	if event is InputEventScreenTouch:
		pos = event.position
		pressed = event.pressed
	elif event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT:
		pos = event.position
		pressed = event.pressed
	elif event is InputEventScreenDrag:
		pos = event.position
		pressed = true
	else:
		return
	hover = _index_at(pos.x) if pressed else -1
	if hover >= 0 and points[hover] is Dictionary:
		var row: Dictionary = points[hover]
		_tip = "мес. %s · %s" % [str(row.get("month", "")), str(row.get(value_key, ""))]
	else:
		_tip = ""
	queue_redraw()


func _draw() -> void:
	draw_rect(Rect2(Vector2.ZERO, size), Color(0.05, 0.12, 0.11, 1))
	if points.size() < 2:
		draw_string(ThemeDB.fallback_font, Vector2(12, 28), "Нет точек", HORIZONTAL_ALIGNMENT_LEFT, -1, 16, Color(0.85, 0.9, 0.86))
		return
	var values: Array[float] = []
	for row in points:
		var sample := 0.0
		if row is Dictionary:
			sample = float(row.get(value_key, 0))
		values.append(sample)
	var lo: float = values[0]
	var hi: float = values[0]
	for value in values:
		lo = minf(lo, value)
		hi = maxf(hi, value)
	if is_equal_approx(lo, hi):
		hi = lo + 1.0
	var poly := PackedVector2Array()
	var last := values.size() - 1
	for i in values.size():
		var x: float = 28.0 + (size.x - 36.0) * float(i) / float(last)
		var y: float = size.y - 22.0 - (size.y - 40.0) * (values[i] - lo) / (hi - lo)
		poly.append(Vector2(x, y))
	draw_polyline(poly, Color("#f0d08f"), 2.0, true)
	draw_string(ThemeDB.fallback_font, Vector2(8, 16), str(int(hi)), HORIZONTAL_ALIGNMENT_LEFT, -1, 12, Color(0.7, 0.8, 0.74))
	draw_string(ThemeDB.fallback_font, Vector2(8, size.y - 6), str(int(lo)), HORIZONTAL_ALIGNMENT_LEFT, -1, 12, Color(0.7, 0.8, 0.74))
	if hover >= 0 and hover < poly.size():
		draw_circle(poly[hover], 4.0, Color("#fff4d2"))
		draw_string(ThemeDB.fallback_font, Vector2(36, 16), _tip, HORIZONTAL_ALIGNMENT_LEFT, -1, 14, Color("#fff4d2"))
