"""Footprint and equipment-upgrade rules for the staged construction rollout.

Legacy buildings keep their original footprints. New 1x1/2x2/3x3 choices
are opt-in, and must be enabled only when both world backends and the Android
placement preview use the same authoritative footprint.
"""
LEGACY_FOOTPRINTS = {
    "farm": (2, 2), "mine": (2, 3), "factory": (3, 2),
    "warehouse": (3, 3), "shop": (2, 2),
    "school": (3, 2), "hospital": (3, 3), "park": (2, 2),
}
SIZE_CHOICES = {
    "farm": (1, 2, 3), "mine": (1, 2, 3),
    "factory": (1, 2, 3), "warehouse": (1, 2, 3),
    "shop": (1, 2),
}
MAX_EQUIPMENT_LEVEL = 3


def footprint(kind, size=None):
    """Resolve a square size or preserve the exact legacy shape."""
    if kind not in LEGACY_FOOTPRINTS:
        raise ValueError("unknown_building_kind")
    if size is None:
        return LEGACY_FOOTPRINTS[kind]
    if type(size) is not int or size not in SIZE_CHOICES.get(kind, ()):
        raise ValueError("invalid_building_size")
    return (size, size)


def can_expand(kind, old_size, new_size):
    """Only permit increasing square footprints on supported buildings."""
    if type(old_size) is not int or type(new_size) is not int:
        return False
    sizes = SIZE_CHOICES.get(kind, ())
    return old_size in sizes and new_size in sizes and new_size > old_size


def can_upgrade_equipment(old_level, new_level):
    return (type(old_level) is int and type(new_level) is int
            and 1 <= old_level < new_level <= MAX_EQUIPMENT_LEVEL)


def view():
    return {
        "legacy_footprints": {k: list(v) for k, v in LEGACY_FOOTPRINTS.items()},
        "size_choices": {k: list(v) for k, v in SIZE_CHOICES.items()},
        "max_equipment_level": MAX_EQUIPMENT_LEVEL,
        "enabled": False,
        "note": "Server rules staged; existing construction uses legacy footprints.",
    }
