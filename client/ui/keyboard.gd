extends RefCounted
## Keyboard drawable-area adjustment (Android virtual keyboard height in pixels).
static func visible_canvas_height(viewport: Vector2, physical_screen: Vector2i, keyboard_px: int) -> float:
    if keyboard_px <= 0 or physical_screen.y <= 0:
        return viewport.y
    return maxf(160.0, viewport.y - float(keyboard_px) * viewport.y / float(physical_screen.y))
