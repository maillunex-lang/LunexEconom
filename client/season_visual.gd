extends RefCounted
## Deterministic seasonal palette transforms. Gameplay terrain is unchanged.
const WINTER := Color("#b6cad2")
const AUTUMN := Color("#c28f65")
const SPRING := Color("#97bd81")

static func season_for_month(month_index: int) -> int:
    var month := posmod(month_index, 12)
    if month in [11, 0, 1]:
        return 0 # winter
    if month in [2, 3, 4]:
        return 1 # spring
    if month in [5, 6, 7]:
        return 2 # summer
    return 3 # autumn

static func tinted(base: Color, month_index: int, enabled: bool = true) -> Color:
    if not enabled:
        return base
    match season_for_month(month_index):
        0:
            return base.lerp(WINTER, 0.32)
        1:
            return base.lerp(SPRING, 0.13)
        2:
            return base.lightened(0.025)
        3:
            return base.lerp(AUTUMN, 0.23)
    return base
