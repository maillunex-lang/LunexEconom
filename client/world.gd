extends Node3D
## The game world in 2.5D: an isometric orthographic Camera3D over a 3D ground (terrain, the river, roads, trees) with 3D buildings.
## Same public interface as the old 2D world (cell_kind, server_cells, roads, selection, build preview, apply_server_event, ...), so the
## HUD, the sync and the server stay unchanged. Visual only: the server is the authority on buildings, roads and money.
## Grid: cell (x, y) is centred at (x * CELL, 0, y * CELL) and covers ±CELL/2 (client/world3d/grid_projection.gd).
const CELL := 2.0
const CHUNK := 12
const ROAD_SCRIPT = preload("res://road_network.gd")
const PLANNER_SCRIPT = preload("res://construction_planner.gd")
const TOPOLOGY = preload("res://road_topology.gd")
const SEASONS = preload("res://season_visual.gd")
const MODELS = preload("res://world3d/building_models.gd")
const ZONES = preload("res://zones.gd")
const INDUSTRIAL_TINT := Color("#b0a58a")   # ground colour of the industrial zone (blended over the grass)
## Every building kind a server snapshot or event may carry ("house" = a city-generated dwelling, never player-built).
## The agro chain and extraction kinds (docs/INDUSTRIES.md) are included.
const BUILDING_KINDS := ["farm", "mine", "factory", "warehouse", "shop", "school", "hospital", "park", "house",
	"grain_field", "elevator", "mill", "bread_plant", "oil_well", "gas_well", "sand_pit", "logging_camp"]
const SEED := 18273
const GRASS := [Color("#74a05e"), Color("#78a361"), Color("#7ca664")]
const OUTSIDE_DIM := 0.82            # land beyond the explored radius is drawn darker (no building there)
const ROAD_COLOR := Color("#4d545a")
const LINE_COLOR := Color("#e2c985")
const WATER_COLOR := Color("#4f88a8")
const SAND_COLOR := Color("#c9b98a")
const LOT_COLOR := Color("#a9a58f")
const CROWN_COLORS := [Color("#3f7a4a"), Color("#467f4d"), Color("#3a6e45")]
const PITCH_DEGREES := 30.0            # camera elevation above the ground
const YAW_DEGREES := 45.0              # +x goes right-down and +y left-down on screen, like the old isometric map
const MIN_SIZE := 14.0                 # orthographic height in metres (zoomed in) ...
const MAX_SIZE := 80.0                 # ... and zoomed out (more is too many chunks for a phone)
const CHUNK_BUILDS_PER_FRAME := 2
const PAN_RESPONSE := 13.0
const ZOOM_RESPONSE := 10.0

var planner = PLANNER_SCRIPT.new()
var roads = ROAD_SCRIPT.new()
var server_cells: Dictionary = {}
var building_records: Dictionary = {}          # local sandbox buildings (tests, offline preview)
var build_counter := 0
var build_type := ""
var build_square_size := 0
var expansion_radius := 48
var selected := Vector2i(-1, -1)
var active_chunks: Dictionary = {}             # Vector2i chunk -> Node3D
var building_nodes: Dictionary = {}            # object id -> Node3D
var building_signatures: Dictionary = {}
var camera: Camera3D
var focus := Vector3.ZERO                      # ground point in the centre of the screen
var target_focus := Vector3.ZERO
var target_size := 40.0
const DEPOSIT_COLORS := {"oil": Color("#3a3634"), "gas": Color("#8fb4c9"), "sand": Color("#e4d28c"), "forest": Color("#2e6a3c")}
const DEPOSIT_NAMES := {"oil": "нефти", "gas": "газа", "sand": "песка", "forest": "леса"}
var deposits: Dictionary = {}                  # id -> deposit from GET /deposits {resource, x, y, width, height, remaining}
var deposit_kinds: Dictionary = {}             # building kind -> the resource it must stand on (from the goods catalogue)
var zones = ZONES.new()                        # city zones from GET /geo/zones (docs/ZONING.md)
var season_month := -1
var seasons_on := false
var last_build_usec := 0                       # time of the last chunk rebuild (performance overlay)
var _dirty_chunks: Dictionary = {}
var _buildings_dirty := true
var _overlay: Node3D
var _selection_node: MeshInstance3D
var _preview_node: MeshInstance3D
var _sun: DirectionalLight3D
var _ground_material: StandardMaterial3D
var _crown_mesh: CylinderMesh
var _trunk_mesh: CylinderMesh

# touch and mouse state (same rules as before: the HUD never selects a tile)
var touch_points: Dictionary = {}
var ui_touch_indices: Dictionary = {}
var ui_mouse_press := false
var dragging := false
var moved := false
var pinch_distance := 0.0
var last_pinch_midpoint := Vector2.ZERO
const PAN_SENSITIVITY := 1.0
const ZOOM_SENSITIVITY := 0.70

func _ready() -> void:
	camera = Camera3D.new()
	camera.name = "WorldCamera"
	camera.projection = Camera3D.PROJECTION_ORTHOGONAL
	camera.size = target_size
	camera.near = 0.5
	camera.far = 600.0
	camera.current = true
	add_child(camera)
	_sun = DirectionalLight3D.new()
	_sun.name = "Sun"
	_sun.rotation_degrees = Vector3(-52.0, 20.0, 0.0)
	_sun.light_energy = 1.05
	add_child(_sun)
	var environment := Environment.new()
	environment.background_mode = Environment.BG_COLOR
	environment.background_color = Color("#9fbfc4")
	environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	environment.ambient_light_color = Color("#c9d3c6")
	environment.ambient_light_energy = 0.75
	var world_environment := WorldEnvironment.new()
	world_environment.name = "Environment"
	world_environment.environment = environment
	add_child(world_environment)
	_ground_material = StandardMaterial3D.new()
	_ground_material.vertex_color_use_as_albedo = true
	_ground_material.roughness = 1.0
	_crown_mesh = CylinderMesh.new()
	_crown_mesh.top_radius = 0.0
	_crown_mesh.bottom_radius = 0.72
	_crown_mesh.height = 1.7
	_crown_mesh.radial_segments = 7
	_crown_mesh.rings = 1
	var crown_material := StandardMaterial3D.new()
	crown_material.vertex_color_use_as_albedo = true
	crown_material.roughness = 1.0
	_crown_mesh.material = crown_material
	_trunk_mesh = CylinderMesh.new()
	_trunk_mesh.top_radius = 0.12
	_trunk_mesh.bottom_radius = 0.14
	_trunk_mesh.height = 0.6
	_trunk_mesh.radial_segments = 5
	_trunk_mesh.rings = 1
	_trunk_mesh.material = MODELS.material(Color("#6b4f37"))
	_overlay = Node3D.new()
	_overlay.name = "Overlay"
	add_child(_overlay)
	_selection_node = MeshInstance3D.new()
	_selection_node.name = "Selection"
	_overlay.add_child(_selection_node)
	_preview_node = MeshInstance3D.new()
	_preview_node.name = "BuildPreview"
	_overlay.add_child(_preview_node)
	_sync_camera()
	_update_visible_chunks()

# ---------- coordinates ----------
static func cell_center(cell: Vector2i) -> Vector3:
	return Vector3(float(cell.x) * CELL, 0.0, float(cell.y) * CELL)

static func cell_of(point: Vector3) -> Vector2i:
	return Vector2i(roundi(point.x / CELL), roundi(point.z / CELL))

## Kept for callers of the old map: the 3D ground point of a cell (the old version returned isometric screen pixels).
func iso(x: float, y: float) -> Vector3:
	return Vector3(x * CELL, 0.0, y * CELL)

func _camera_basis() -> Basis:
	return Basis.from_euler(Vector3(deg_to_rad(-PITCH_DEGREES), deg_to_rad(YAW_DEGREES), 0.0))

func _sync_camera() -> void:
	if camera == null:
		return
	camera.size = clampf(camera.size, MIN_SIZE, MAX_SIZE)
	camera.transform = Transform3D(_camera_basis(), focus + _camera_basis() * Vector3(0.0, 0.0, 200.0))

func ground_point(screen_position: Vector2) -> Vector3:
	"""Where a screen point hits the ground plane (y = 0)."""
	var origin := camera.project_ray_origin(screen_position)
	var direction := camera.project_ray_normal(screen_position)
	if absf(direction.y) < 0.0001:
		return focus
	return origin + direction * (-origin.y / direction.y)

func screen_cell(screen_position: Vector2) -> Vector2i:
	return cell_of(ground_point(screen_position))

## Centre the camera on a cell (immediately, without easing).
func focus_cell(cell: Vector2i) -> void:
	expansion_radius = maxi(expansion_radius, maxi(absi(cell.x), absi(cell.y)) + 48)
	focus = cell_center(cell)
	target_focus = focus
	_sync_camera()
	_update_visible_chunks()

func focus_on(cell: Vector2i) -> void:
	focus_cell(cell)

func set_zoom(size_or_factor: float) -> void:
	target_size = clampf(size_or_factor, MIN_SIZE, MAX_SIZE)

func clamp_camera() -> void:
	target_focus.x = clampf(target_focus.x, -25000.0, 25000.0)
	target_focus.z = clampf(target_focus.z, -25000.0, 25000.0)

# ---------- terrain (identical rules to the server, docs/CITYGEN.md) ----------
func cell_kind(x: int, y: int) -> int:
	var coord := Vector2i(x, y)
	if server_cells.has(coord):
		var kind := str(server_cells[coord].get("kind", ""))
		if kind == "road_changed": return 3
		if kind == "building_created" or kind in BUILDING_KINDS: return 6
		if kind == "building_removed": return 0
	if planner.occupied.has(coord): return 6
	if roads.is_road(coord):
		return 3 # roads
	if ROAD_SCRIPT.is_water(coord):
		return 4 # the river is the only water
	var n := ROAD_SCRIPT.terrain_noise(x, y)
	if n < 24:
		return 5 # trees
	return n % 3

# ---------- server data ----------
func _is_building_event(kind: String) -> bool:
	return kind == "building_created" or kind in BUILDING_KINDS

func apply_server_event(event: Dictionary) -> void:
	var kind := str(event.get("kind", ""))
	if not (_is_building_event(kind) or kind in ["building_removed", "road_changed"]): return
	var building_kind := str(event.get("building_kind", kind if kind in BUILDING_KINDS else ""))
	for cell in event.get("cells", []):
		if not cell is Array or cell.size() != 2: continue
		var coord := Vector2i(int(cell[0]), int(cell[1]))
		if kind == "road_changed":
			roads.segments[coord] = true
			_mark_cell(coord, true)
			continue
		if kind == "building_removed": server_cells.erase(coord)
		else: server_cells[coord] = {"kind": "building_created", "building_kind": building_kind, "object_id": str(event.get("object_id", "")), "owner": str(event.get("owner", ""))}
		_mark_cell(coord, false)
	_buildings_dirty = true

func apply_chunk_snapshot(coord: Vector2i, cells: Array) -> void:
	for x in range(coord.x * CHUNK, (coord.x + 1) * CHUNK):
		for y in range(coord.y * CHUNK, (coord.y + 1) * CHUNK):
			server_cells.erase(Vector2i(x, y))
			roads.segments.erase(Vector2i(x, y))
	for cell in cells:
		if not cell is Dictionary: continue
		var c := Vector2i(int(cell.get("x", 0)), int(cell.get("y", 0)))
		var kind := str(cell.get("kind", ""))
		if kind == "road_changed":
			roads.segments[c] = true
		else:
			var bk := str(cell.get("building_kind", kind if kind in BUILDING_KINDS else ""))
			server_cells[c] = {"kind": "building_created", "building_kind": bk, "object_id": str(cell.get("object_id", "")), "owner": str(cell.get("owner", ""))}
	for dx in range(-1, 2):
		for dy in range(-1, 2):
			_dirty_chunks[coord + Vector2i(dx, dy)] = true
	_buildings_dirty = true

func _mark_cell(cell: Vector2i, with_neighbours: bool) -> void:
	_dirty_chunks[_chunk_of(cell)] = true
	if with_neighbours:              # a road on a chunk border changes the road marks of the neighbour chunk
		for affected in TOPOLOGY.affected_cells(cell):
			_dirty_chunks[_chunk_of(affected)] = true

static func _chunk_of(cell: Vector2i) -> Vector2i:
	return Vector2i(floori(float(cell.x) / CHUNK), floori(float(cell.y) / CHUNK))

func building_info(cell: Vector2i) -> Dictionary:
	"""Server building on a cell: {kind, object_id, owner}, or an empty dictionary."""
	if not server_cells.has(cell): return {}
	var c: Dictionary = server_cells[cell]
	if str(c.get("object_id", "")) == "": return {}
	return {"kind": str(c.get("building_kind", "")), "object_id": str(c.get("object_id", "")), "owner": str(c.get("owner", ""))}

func building_at(cell: Vector2i) -> String:
	if server_cells.has(cell):
		return str(server_cells[cell].get("building_kind", ""))
	var object_id: String = str(planner.occupied.get(cell, ""))
	if building_records.has(object_id):
		return str(building_records[object_id].get("kind", ""))
	return ""

## Buildings grouped by object id: {id: {kind, owner, cells}} (server objects and local sandbox ones).
func objects() -> Dictionary:
	var out: Dictionary = {}
	for coord in server_cells:
		var data: Dictionary = server_cells[coord]
		var oid := str(data.get("object_id", ""))
		if oid.is_empty():
			continue
		if not out.has(oid):
			out[oid] = {"kind": str(data.get("building_kind", "")), "owner": str(data.get("owner", "")), "cells": []}
		out[oid]["cells"].append(coord)
	for oid in building_records:
		var record: Dictionary = building_records[oid]
		out[oid] = {"kind": str(record.get("kind", "")), "owner": "", "cells": record.get("cells", [])}
	return out

# ---------- chunks: ground, roads, water and trees ----------
func _visible_cell_rect() -> Rect2i:
	var rect := get_viewport().get_visible_rect() if is_inside_tree() else Rect2(Vector2.ZERO, Vector2(1280, 720))
	var min_c := Vector2i(2147483647, 2147483647)
	var max_c := Vector2i(-2147483647, -2147483647)
	for corner in [rect.position, Vector2(rect.end.x, rect.position.y), Vector2(rect.position.x, rect.end.y), rect.end]:
		var cell := screen_cell(corner)
		min_c = Vector2i(mini(min_c.x, cell.x), mini(min_c.y, cell.y))
		max_c = Vector2i(maxi(max_c.x, cell.x), maxi(max_c.y, cell.y))
	min_c -= Vector2i(3, 3)          # tall buildings near the bottom edge of the screen
	max_c += Vector2i(3, 3)
	return Rect2i(min_c, max_c - min_c + Vector2i.ONE)

func _update_visible_chunks() -> void:
	if camera == null or not is_inside_tree(): return
	var cells := _visible_cell_rect()
	var min_x := cells.position.x
	var max_x := cells.end.x
	var min_y := cells.position.y
	var max_y := cells.end.y
	var needed: Dictionary = {}
	if min_x <= max_x and min_y <= max_y:
		for cx in range(floori(float(min_x) / CHUNK), floori(float(max_x) / CHUNK) + 1):
			for cy in range(floori(float(min_y) / CHUNK), floori(float(max_y) / CHUNK) + 1):
				var coord := Vector2i(cx, cy)
				needed[coord] = true
				if not active_chunks.has(coord):
					var node := Node3D.new()
					node.name = "Chunk_%d_%d" % [cx, cy]
					add_child(node)
					active_chunks[coord] = node
					_dirty_chunks[coord] = true
	for coord in active_chunks.keys():
		if not needed.has(coord):
			active_chunks[coord].queue_free()
			active_chunks.erase(coord)
			_dirty_chunks.erase(coord)

func refresh_all() -> void:
	"""Rebuild every visible chunk (season change, expansion)."""
	for coord in active_chunks:
		_dirty_chunks[coord] = true

func _season_tint(color: Color) -> Color:
	return SEASONS.tinted(color, season_month, seasons_on) if season_month >= 0 else color

func _read_season() -> void:
	var host = get_parent()
	if host == null:
		return
	var clock_data = host.get("game_clock")
	var month := -1
	if clock_data is Dictionary and not clock_data.is_empty():
		var span := maxi(int(clock_data.get("month_seconds", 86400)), 1)
		var elapsed := maxf(Time.get_unix_time_from_system() + float(host.get("clock_offset")) - float(clock_data.get("epoch", 0)), 0.0)
		month = int(clock_data.get("base_index", 0)) + int(elapsed / span)
	var on := bool(host.get("seasons_enabled")) if host.get("seasons_enabled") != null else false
	if month != season_month or on != seasons_on:
		season_month = month
		seasons_on = on
		refresh_all()

func _quad(st: SurfaceTool, x0: float, z0: float, x1: float, z1: float, y: float, color: Color) -> void:
	st.set_color(color)
	st.set_normal(Vector3.UP)
	st.add_vertex(Vector3(x0, y, z0))
	st.add_vertex(Vector3(x1, y, z0))
	st.add_vertex(Vector3(x1, y, z1))
	st.add_vertex(Vector3(x0, y, z0))
	st.add_vertex(Vector3(x1, y, z1))
	st.add_vertex(Vector3(x0, y, z1))

func build_chunk(coord: Vector2i) -> void:
	if not active_chunks.has(coord):
		return
	var start := Time.get_ticks_usec()
	var node: Node3D = active_chunks[coord]
	for child in node.get_children():
		child.queue_free()
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	var trees: Array = []
	var road_pieces := {"road_straight_1x1": [], "road_cross_1x1": [], "road_corner_1x1": []}
	var half := CELL * 0.5
	for x in range(coord.x * CHUNK, (coord.x + 1) * CHUNK):
		for y in range(coord.y * CHUNK, (coord.y + 1) * CHUNK):
			var outside := absi(x) > expansion_radius or absi(y) > expansion_radius
			var cell := Vector2i(x, y)
			var cx := x * CELL
			var cz := y * CELL
			var kind := cell_kind(x, y)
			var color: Color
			match kind:
				3:
					color = ROAD_COLOR
				4:
					color = WATER_COLOR
				6:
					color = LOT_COLOR
				_:
					var n := ROAD_SCRIPT.terrain_noise(x, y)
					color = GRASS[n % 3]
					if ROAD_SCRIPT.is_water(cell + Vector2i(1, 0)) or ROAD_SCRIPT.is_water(cell - Vector2i(1, 0)):
						color = SAND_COLOR
					elif zones.enabled and zones.zone_at(x, y) == "industrial":
						color = color.lerp(INDUSTRIAL_TINT, 0.55)
					if not deposits.is_empty():
						var deposit := deposit_at(cell)
						if not deposit.is_empty() and int(deposit.get("remaining", 0)) > 0 and DEPOSIT_COLORS.has(str(deposit.get("resource", ""))):
							color = color.lerp(DEPOSIT_COLORS[str(deposit["resource"])], 0.78)
			if kind != 3:
				color = _season_tint(color)
			if outside:
				color = color.darkened(1.0 - OUTSIDE_DIM)
			_quad(st, cx - half, cz - half, cx + half, cz + half, -0.02 if kind == 4 else 0.0, color)
			if kind == 3:
				_road_piece(cell, cx, cz, road_pieces, st)
			elif kind == 5:
				trees.append(cell)
	var ground := MeshInstance3D.new()
	ground.name = "Ground"
	ground.mesh = st.commit()
	ground.material_override = _ground_material
	node.add_child(ground)
	if not trees.is_empty():
		_plant_trees(node, trees)
	_place_road_pieces(node, road_pieces)
	last_build_usec = Time.get_ticks_usec() - start

## Road models (GLB road_straight_1x1 / road_cross_1x1) go on straight stretches and junctions; bends and dead ends stay plain asphalt. Without the
## GLB files the centre-line marks of the ground mesh are used.
func _road_piece(cell: Vector2i, cx: float, cz: float, pieces: Dictionary, st: SurfaceTool) -> void:
	var mask: int = TOPOLOGY.mask_at(roads, cell)
	var shape: String = TOPOLOGY.shape(mask)
	var name := ""
	var turn := 0.0
	if shape == "straight":
		name = "road_straight_1x1"
		turn = 0.0 if (mask == TOPOLOGY.NORTH | TOPOLOGY.SOUTH) else PI * 0.5
	elif shape == "corner":
		name = "road_corner_1x1"
		# Corner GLB's baseline arms point north and east.
		match mask:
			TOPOLOGY.NORTH | TOPOLOGY.EAST: turn = 0.0
			TOPOLOGY.EAST | TOPOLOGY.SOUTH: turn = PI * 0.5
			TOPOLOGY.SOUTH | TOPOLOGY.WEST: turn = PI
			TOPOLOGY.WEST | TOPOLOGY.NORTH: turn = PI * 1.5
	elif shape == "t_junction" or shape == "cross":
		name = "road_cross_1x1"
	if name != "" and not MODELS.piece(name).is_empty():
		pieces[name].append(Transform3D(Basis(Vector3.UP, turn), Vector3(cx, 0.0, cz)))
	else:
		_road_marks(st, cell, cx, cz)

func _place_road_pieces(node: Node3D, pieces: Dictionary) -> void:
	for name in pieces:
		var list: Array = pieces[name]
		if list.is_empty():
			continue
		var piece: Dictionary = MODELS.piece(name)
		var local: Transform3D = piece["transform"]
		var multi := MultiMesh.new()
		multi.transform_format = MultiMesh.TRANSFORM_3D
		multi.mesh = piece["mesh"]
		multi.instance_count = list.size()
		for i in list.size():
			multi.set_instance_transform(i, (list[i] as Transform3D) * local)
		var holder := MultiMeshInstance3D.new()
		holder.name = "Roads_" + name
		holder.multimesh = multi
		holder.material_override = MODELS.vertex_color_material()
		node.add_child(holder)

func _road_marks(st: SurfaceTool, cell: Vector2i, cx: float, cz: float) -> void:
	var mask: int = TOPOLOGY.mask_at(roads, cell)
	if TOPOLOGY.shape(mask) != "straight":
		return                       # centre lines only on straight stretches; junctions and bends stay plain
	var w := 0.07
	var y := 0.012
	if mask & TOPOLOGY.NORTH: _quad(st, cx - w, cz - CELL * 0.5, cx + w, cz - 0.15, y, LINE_COLOR)
	if mask & TOPOLOGY.SOUTH: _quad(st, cx - w, cz + 0.15, cx + w, cz + CELL * 0.5, y, LINE_COLOR)
	if mask & TOPOLOGY.WEST: _quad(st, cx - CELL * 0.5, cz - w, cx - 0.15, cz + w, y, LINE_COLOR)
	if mask & TOPOLOGY.EAST: _quad(st, cx + 0.15, cz - w, cx + CELL * 0.5, cz + w, y, LINE_COLOR)

func _plant_trees(node: Node3D, cells: Array) -> void:
	var crowns := MultiMesh.new()
	crowns.transform_format = MultiMesh.TRANSFORM_3D
	crowns.use_colors = true
	crowns.mesh = _crown_mesh
	crowns.instance_count = cells.size()
	var trunks := MultiMesh.new()
	trunks.transform_format = MultiMesh.TRANSFORM_3D
	trunks.mesh = _trunk_mesh
	trunks.instance_count = cells.size()
	for i in cells.size():
		var cell: Vector2i = cells[i]
		var n := ROAD_SCRIPT.terrain_noise(cell.x * 7 + 3, cell.y * 5 + 11)
		var s := 0.75 + float(n % 40) / 100.0
		if ROAD_SCRIPT.terrain_noise(cell.x, cell.y) >= 12:
			s *= 0.45                # most tree cells are bushes: the land stays readable, real woods are the denser cells
		var offset := Vector3(float(n % 7 - 3) * 0.12, 0.0, float((n / 7) % 7 - 3) * 0.12)
		var base := cell_center(cell) + offset
		trunks.set_instance_transform(i, Transform3D(Basis().scaled(Vector3(s, s, s)), base + Vector3(0, 0.3 * s, 0)))
		crowns.set_instance_transform(i, Transform3D(Basis().scaled(Vector3(s, s, s)), base + Vector3(0, (0.6 + 0.85) * s, 0)))
		crowns.set_instance_color(i, _season_tint(CROWN_COLORS[n % CROWN_COLORS.size()]))
	var trunk_node := MultiMeshInstance3D.new()
	trunk_node.name = "Trunks"
	trunk_node.multimesh = trunks
	node.add_child(trunk_node)
	var crown_node := MultiMeshInstance3D.new()
	crown_node.name = "Trees"
	crown_node.multimesh = crowns
	node.add_child(crown_node)

# ---------- buildings ----------
func _refresh_buildings() -> void:
	var current := objects()
	for oid in building_nodes.keys():
		if not current.has(oid):
			building_nodes[oid].queue_free()
			building_nodes.erase(oid)
			building_signatures.erase(oid)
	for oid in current:
		var record: Dictionary = current[oid]
		var cells: Array = record["cells"]
		if cells.is_empty():
			continue
		var min_c := Vector2i(2147483647, 2147483647)
		var max_c := Vector2i(-2147483647, -2147483647)
		for c in cells:
			min_c = Vector2i(mini(min_c.x, c.x), mini(min_c.y, c.y))
			max_c = Vector2i(maxi(max_c.x, c.x), maxi(max_c.y, c.y))
		var size := max_c - min_c + Vector2i.ONE
		var signature := "%s|%s|%s|%s" % [record["kind"], record["owner"], str(min_c), str(size)]
		if building_nodes.has(oid) and building_signatures.get(oid, "") == signature:
			continue
		if building_nodes.has(oid):
			building_nodes[oid].queue_free()
		var node: Node3D = MODELS.make(str(record["kind"]), size.x, size.y, str(oid), str(record["owner"]))
		node.name = "B_" + str(oid).left(24)
		node.position = Vector3((float(min_c.x) + float(size.x - 1) * 0.5) * CELL, 0.0, (float(min_c.y) + float(size.y - 1) * 0.5) * CELL)
		node.set_meta("object_id", str(oid))
		node.set_meta("cells", cells)
		add_child(node)
		building_nodes[oid] = node
		building_signatures[oid] = signature
	_buildings_dirty = false

# ---------- selection and the construction preview ----------
func _cells_mesh(cells: Array, color: Color, y: float) -> ArrayMesh:
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	var half := CELL * 0.48
	for c in cells:
		var p := cell_center(c)
		_quad(st, p.x - half, p.z - half, p.x + half, p.z + half, y, color)
	var mesh := st.commit()
	var material := StandardMaterial3D.new()
	material.vertex_color_use_as_albedo = true
	material.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	material.no_depth_test = true
	if mesh.get_surface_count() > 0:
		mesh.surface_set_material(0, material)
	return mesh

func _update_overlay() -> void:
	if selected == Vector2i(-1, -1):
		_selection_node.mesh = null
	else:
		_selection_node.mesh = _cells_mesh([selected], Color(0.97, 0.83, 0.42, 0.55), 0.05)
	if build_type.is_empty() or selected == Vector2i(-1, -1):
		_preview_node.mesh = null
		return
	var result := preview_build(selected)
	var ok := bool(result.get("ok", false))
	var cells: Array = planner.footprint(selected, build_size(build_type))
	var mesh := _cells_mesh(cells, Color(0.22, 0.95, 0.50, 0.45) if ok else Color(0.98, 0.22, 0.22, 0.45), 0.06)
	_preview_node.mesh = mesh
	if ok:
		var access: Array = result.get("access", [])
		if not access.is_empty():
			var road_preview := MeshInstance3D.new()
			road_preview.name = "AccessPreview"
			road_preview.mesh = _cells_mesh(access, Color(0.85, 0.85, 0.85, 0.5), 0.04)
			for child in _preview_node.get_children():
				child.queue_free()
			_preview_node.add_child(road_preview)
			return
	for child in _preview_node.get_children():
		child.queue_free()

func select_screen(pos: Vector2) -> void:
	select_cell(screen_cell(pos))

func select_cell(cell: Vector2i) -> void:
	if absi(cell.x) > expansion_radius or absi(cell.y) > expansion_radius:
		return
	selected = cell
	_update_overlay()
	if is_inside_tree():
		get_tree().call_group("world_hud", "set_selection", cell)
		if not build_type.is_empty():
			get_tree().call_group("world_hud", "show_build_preview", preview_build(cell))

func build_size(kind: String) -> Vector2i:
	if kind == build_type and build_square_size > 0:
		return Vector2i(build_square_size, build_square_size)
	match kind:
		"farm": return Vector2i(2, 2)
		"mine": return Vector2i(2, 3)
		"factory": return Vector2i(3, 2)
		"warehouse": return Vector2i(3, 3)
		"shop": return Vector2i(2, 2)
		"school": return Vector2i(3, 2)
		"hospital": return Vector2i(3, 3)
		"park": return Vector2i(2, 2)
		"grain_field": return Vector2i(3, 2)
		"elevator": return Vector2i(3, 3)
		"mill": return Vector2i(3, 2)
		"bread_plant": return Vector2i(3, 2)
		"oil_well": return Vector2i(2, 2)
		"gas_well": return Vector2i(2, 2)
		"sand_pit": return Vector2i(2, 2)
		"logging_camp": return Vector2i(2, 3)
	return Vector2i.ZERO

func preview_build(cell: Vector2i) -> Dictionary:
	if build_type.is_empty(): return {"ok": false, "reason": "no_build_mode"}
	return planner.preview(cell, build_size(build_type), roads, self, build_type)

## Reason (Russian) why the server would refuse `kind` on these cells because of the zones, or "".
func zone_refusal(kind: String, cells: Array) -> String:
	return zones.refusal(kind, cells)

## Zone and deposit rules the server would apply: "" when the building may stand on these cells, else the Russian reason.
func build_refusal(kind: String, cells: Array) -> String:
	var zone_text: String = zones.refusal(kind, cells)
	if zone_text != "":
		return zone_text
	if deposit_kinds.has(kind):
		var resource: String = deposit_kinds[kind]
		for cell in cells:
			var found := deposit_at(cell)
			if not found.is_empty() and str(found.get("resource", "")) == resource and int(found.get("remaining", 0)) > 0:
				return ""
		return "Нужно месторождение %s: оно подсвечено на карте" % str(DEPOSIT_NAMES.get(resource, resource))
	return ""

func deposit_at(cell: Vector2i) -> Dictionary:
	for id in deposits:
		var d: Dictionary = deposits[id]
		var x := int(d.get("x", 0))
		var y := int(d.get("y", 0))
		if cell.x >= x and cell.x < x + int(d.get("width", 2)) and cell.y >= y and cell.y < y + int(d.get("height", 2)):
			return d
	return {}

func set_deposits(list: Array) -> void:
	var changed := false
	for item in list:
		if item is Dictionary and str(item.get("id", "")) != "":
			var id := str(item["id"])
			if not deposits.has(id) or int(deposits[id].get("remaining", -1)) != int(item.get("remaining", -2)):
				changed = true
			deposits[id] = item
	if changed:
		refresh_all()

func set_deposit_rules(rules: Dictionary) -> void:
	deposit_kinds = rules

func set_zones(data: Dictionary) -> void:
	zones.load_data(data)
	refresh_all()

func choose_build(kind: String, square_size: int = 0) -> void:
	build_type = kind
	build_square_size = square_size
	_update_overlay()
	if selected != Vector2i(-1, -1) and is_inside_tree():
		get_tree().call_group("world_hud", "show_build_preview", preview_build(selected))

func cancel_build() -> void:
	build_type = ""
	build_square_size = 0
	_update_overlay()

## Local sandbox placement (tests, offline): never sent to the server.
func place_building() -> Dictionary:
	if build_type.is_empty() or selected == Vector2i(-1, -1):
		return {"ok": false, "reason": "no_selection"}
	var result := preview_build(selected)
	if not result.get("ok", false): return result
	build_counter += 1
	var object_id := "sandbox_%d" % build_counter
	var cells: Array[Vector2i] = result["cells"]
	if not planner.reserve_preview(cells, object_id):
		return {"ok": false, "reason": "occupied"}
	building_records[object_id] = {"kind": build_type, "origin": selected, "cells": cells}
	for cell in cells: _mark_cell(cell, false)
	var access: Array[Vector2i] = result.get("access", [] as Array[Vector2i])
	if not access.is_empty() and roads.add_path(access):
		for road_cell in access: _mark_cell(road_cell, true)
	_buildings_dirty = true
	_update_overlay()
	return {"ok": true, "reason": "sandbox_only", "object_id": object_id, "road_cells": access.size()}

func preview_access_road(site: Vector2i) -> Array[Vector2i]:
	return roads.connect_site(site)

func commit_access_road(site: Vector2i) -> bool:
	var path: Array[Vector2i] = preview_access_road(site)
	var accepted: bool = roads.add_path(path)
	if accepted:
		for cell in path: _mark_cell(cell, true)
	return accepted

func expand_city(chunks: int = 1) -> void:
	expansion_radius += maxi(chunks, 1) * CHUNK
	_update_visible_chunks()
	refresh_all()

# ---------- frame ----------
func _process(delta: float) -> void:
	var pan_alpha := 1.0 - exp(-PAN_RESPONSE * minf(delta, 0.1))
	var zoom_alpha := 1.0 - exp(-ZOOM_RESPONSE * minf(delta, 0.1))
	var old_focus := focus
	var old_size := camera.size
	focus = focus.lerp(target_focus, pan_alpha)
	camera.size = lerpf(camera.size, target_size, zoom_alpha)
	if focus.distance_squared_to(old_focus) > 0.000001 or absf(camera.size - old_size) > 0.0001:
		_sync_camera()
		_update_visible_chunks()
	_read_season()
	_flush()

## Apply pending changes now (chunk meshes and buildings). Called every frame; tests call it directly.
func _flush(limit: int = CHUNK_BUILDS_PER_FRAME) -> void:
	var built := 0
	for coord in _dirty_chunks.keys():
		if built >= limit:
			break
		_dirty_chunks.erase(coord)
		if active_chunks.has(coord):
			build_chunk(coord)
			built += 1
	if _buildings_dirty:
		_refresh_buildings()

func flush_all() -> void:
	_flush(1 << 20)

# ---------- input (one finger pans, two fingers zoom, a tap selects; the HUD never selects a tile) ----------
func _is_ui(point: Vector2) -> bool:
	var host = get_parent()
	return host != null and host.has_method("is_world_ui_point") and host.is_world_ui_point(point)

func _pan_pixels(delta: Vector2) -> void:
	var viewport_height := maxf(get_viewport().get_visible_rect().size.y, 1.0)
	var metres_per_pixel := camera.size / viewport_height
	var basis := _camera_basis()
	var right := Vector3(basis.x.x, 0.0, basis.x.z).normalized()
	var away := Vector3(-basis.z.x, 0.0, -basis.z.z).normalized()
	var ground_per_screen := 1.0 / sin(deg_to_rad(PITCH_DEGREES))
	target_focus += (-right * delta.x + away * delta.y * ground_per_screen) * metres_per_pixel * PAN_SENSITIVITY
	clamp_camera()

func _input(event: InputEvent) -> void:
	if event is InputEventScreenTouch:
		if event.pressed and _is_ui(event.position):
			ui_touch_indices[event.index] = true
			return
		if ui_touch_indices.has(event.index):
			if not event.pressed:
				ui_touch_indices.erase(event.index)
			return
	if event is InputEventScreenDrag and ui_touch_indices.has(event.index):
		return
	if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT:
		if event.pressed:
			ui_mouse_press = _is_ui(event.position)
			if ui_mouse_press: return
		elif ui_mouse_press:
			ui_mouse_press = false
			return
	if event is InputEventMouseMotion and ui_mouse_press:
		return
	if event is InputEventScreenTouch:
		if event.pressed:
			touch_points[event.index] = event.position
			if touch_points.size() == 1: moved = false
			if touch_points.size() == 2:
				var pair := touch_points.values()
				pinch_distance = pair[0].distance_to(pair[1])
				last_pinch_midpoint = (pair[0] + pair[1]) * 0.5
				moved = true
		else:
			if touch_points.size() == 1 and not moved and not _is_ui(event.position):
				select_screen(event.position)
			touch_points.erase(event.index)
			pinch_distance = 0.0
			if touch_points.size() > 0: moved = true
	elif event is InputEventScreenDrag:
		var old: Vector2 = touch_points.get(event.index, event.position - event.relative)
		touch_points[event.index] = event.position
		if touch_points.size() == 1:
			if event.position.distance_to(old) > 0.5:
				moved = true
			_pan_pixels(event.position - old)
		elif touch_points.size() == 2:
			var points := touch_points.values()
			var dist: float = points[0].distance_to(points[1])
			if pinch_distance > 0.0 and dist > 1.0:
				set_zoom(target_size / pow(dist / pinch_distance, ZOOM_SENSITIVITY))
			var midpoint: Vector2 = (points[0] + points[1]) * 0.5
			_pan_pixels(midpoint - last_pinch_midpoint)
			last_pinch_midpoint = midpoint
			pinch_distance = dist
			moved = true
	elif event is InputEventMouseButton:
		if event.button_index == MOUSE_BUTTON_WHEEL_UP and event.pressed:
			set_zoom(target_size / 1.12)
		elif event.button_index == MOUSE_BUTTON_WHEEL_DOWN and event.pressed:
			set_zoom(target_size * 1.12)
		elif event.button_index == MOUSE_BUTTON_LEFT:
			dragging = event.pressed
			if dragging:
				moved = false
			elif not moved and not _is_ui(event.position):
				select_screen(event.position)
	elif event is InputEventMouseMotion and dragging:
		if event.relative.length() > 0.5:
			moved = true
		_pan_pixels(event.relative)