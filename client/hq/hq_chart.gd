extends Control
## Single-pass chart: _draw only runs when history changes or the viewport is resized.
var history: Array = []
const PROFIT := Color("#9bd9a9")
const FLOW := Color("#7bbac1")

func set_history(values: Array) -> void:
    history = values.duplicate(true)
    queue_redraw()

func _draw() -> void:
    if history.is_empty():
        return
    var top := 6.0
    var bottom := size.y - 24.0
    var chart_height := maxf(1.0, bottom - top)
    var values := []
    for item in history:
        if item is Dictionary:
            values.append(float(item.get("profit", 0)))
            values.append(float(item.get("cashflow", 0)))
    if values.is_empty():
        return
    var highest: float = maxf(1.0, float(values.max()))
    var lowest: float = minf(0.0, float(values.min()))
    var span: float = maxf(1.0, highest - lowest)
    var origin: float = bottom - (0.0 - lowest) / span * chart_height
    draw_line(Vector2(0.0, origin), Vector2(size.x, origin), Color("#b7d7c7", 0.35), 1.0)
    var bar_width: float = size.x / maxf(1.0, float(history.size()))
    for index in history.size():
        var item = history[index]
        if not item is Dictionary:
            continue
        var profit: float = float(item.get("profit", 0))
        var cashflow: float = float(item.get("cashflow", 0))
        var p_y: float = bottom - (profit - lowest) / span * chart_height
        var f_y: float = bottom - (cashflow - lowest) / span * chart_height
        var first := Rect2(index * bar_width + bar_width * 0.15, minf(origin, p_y), bar_width * 0.30, maxf(2.0, absf(origin - p_y)))
        var second := Rect2(index * bar_width + bar_width * 0.53, minf(origin, f_y), bar_width * 0.30, maxf(2.0, absf(origin - f_y)))
        draw_rect(first, PROFIT)
        draw_rect(second, FLOW)
        draw_string(ThemeDB.fallback_font, Vector2((index + 0.10) * bar_width, size.y - 4), str(item.get("month", index + 1)), HORIZONTAL_ALIGNMENT_LEFT, -1, 12, Color("#d1e5d8"))
