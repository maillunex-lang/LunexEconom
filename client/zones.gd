extends RefCounted
## City zones, mirrored from server/zoning.py (docs/ZONING.md). The server decides; the client only draws zones and refuses a building
## that the server would refuse. Data: GET /geo/zones (current radius of every city).
const CORE_SHARE := 0.4
const WEDGE_DEGREES := 100.0
const EXPAND_STEP := 0.25
const ALLOWED := {
	"house": ["center", "suburb"], "shop": ["center", "suburb"], "school": ["center", "suburb"], "hospital": ["center", "suburb"],
	"park": ["center", "suburb"],
	"factory": ["industrial"], "warehouse": ["industrial", "open"], "mine": ["industrial", "open"], "farm": ["industrial", "open"],
}
const NAMES := {"center": "центр города", "suburb": "жилой район", "industrial": "промзона", "open": "свободная земля"}
var enabled := false
var cities: Array = []

func load_data(data: Dictionary) -> void:
	enabled = bool(data.get("enabled", false))
	cities = data.get("cities", []) if data.get("cities", null) is Array else []

## Zone of a cell relative to the nearest city: "center" | "suburb" | "industrial" | "open".
func zone_at(x: int, y: int) -> String:
	var best: Dictionary = {}
	var best_d := 1.0e30
	for city in cities:
		var dx := float(x - int(city.get("x", 0)))
		var dy := float(y - int(city.get("y", 0)))
		var d := dx * dx + dy * dy
		if d < best_d:
			best_d = d
			best = city
	if best.is_empty():
		return "open"
	var distance := sqrt(best_d)
	var radius := float(best.get("radius", 0))
	if distance > radius:
		return "open"
	if distance <= radius * CORE_SHARE:
		return "center"
	var dx2 := float(x - int(best.get("x", 0)))
	var dy2 := float(y - int(best.get("y", 0)))
	var angle := fposmod(rad_to_deg(atan2(dy2, dx2)), 360.0)
	var diff := absf(fposmod(angle - float(best.get("wedge_angle", 0)) + 180.0, 360.0) - 180.0)
	return "industrial" if diff <= WEDGE_DEGREES / 2.0 else "suburb"

## "" when `kind` may stand on all the cells, else the Russian reason shown to the player.
func refusal(kind: String, cells: Array) -> String:
	if not enabled or not ALLOWED.has(kind):
		return ""
	var allowed: Array = ALLOWED[kind]
	for cell in cells:
		var zone := zone_at(cell.x, cell.y)
		if not allowed.has(zone):
			var names: Array = []
			for z in allowed:
				names.append(NAMES[z])
			return "Здесь %s: это здание можно строить только в зоне «%s»" % [NAMES[zone], "», «".join(names)]
	return ""
