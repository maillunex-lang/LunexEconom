extends RefCounted
## Convert physical display cutouts to canvas units. Also supports tests.
static func margins(viewport_size: Vector2, physical_size: Vector2i, safe: Rect2i, padding: int = 12) -> Dictionary:
    var result := {"left":padding,"top":padding,"right":padding,"bottom":padding}
    if physical_size.x <= 0 or physical_size.y <= 0 or safe.size.x <= 0 or safe.size.y <= 0:
        return result
    var ratio_x := viewport_size.x / float(physical_size.x)
    var ratio_y := viewport_size.y / float(physical_size.y)
    result.left = maxi(padding, roundi(safe.position.x * ratio_x) + padding)
    result.top = maxi(padding, roundi(safe.position.y * ratio_y) + padding)
    result.right = maxi(padding, roundi((physical_size.x - safe.end.x) * ratio_x) + padding)
    result.bottom = maxi(padding, roundi((physical_size.y - safe.end.y) * ratio_y) + padding)
    return result

static func apply(container: MarginContainer, viewport_size: Vector2) -> void:
    var m := {"left":12,"top":12,"right":12,"bottom":12}
    if OS.has_feature("mobile"):
        m = margins(viewport_size,DisplayServer.screen_get_size(),DisplayServer.get_display_safe_area())
    for side in ["left","top","right","bottom"]:
        container.add_theme_constant_override("margin_"+side,m[side])
