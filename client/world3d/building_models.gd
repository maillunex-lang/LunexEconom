extends RefCounted
## 3D building visuals. A GLB from res://world3d/models/ is used when there is one for the footprint ("<kind>_<w>x<h>.glb" or the rotated
## "<kind>_<h>x<w>.glb", docs/WORLD3D.md); it is fitted into the footprint whatever scale it was authored at. Untextured prototype files named
## only "<kind>.glb" are ignored. Every other kind gets a low-poly
## procedural model, so no building is ever invisible. Visual only: the server stays the authority on footprints and owners.
const CELL := 2.0
const MODEL_DIR := "res://world3d/models/"
const FILL := 0.9                    # a model takes this share of its plot; the rest is the yard
static var _materials: Dictionary = {}
static var _model_cache: Dictionary = {}

static func material(color: Color) -> StandardMaterial3D:
	var key := color.to_html()
	if _materials.has(key):
		return _materials[key]
	var m := StandardMaterial3D.new()
	m.albedo_color = color
	m.roughness = 0.92
	_materials[key] = m
	return m

## GLB files carry their colours as vertex colours (COLOR_0) on one material; Godot does not switch those on by itself.
static var _vertex_material: StandardMaterial3D
static func vertex_color_material() -> StandardMaterial3D:
	if _vertex_material == null:
		_vertex_material = StandardMaterial3D.new()
		_vertex_material.vertex_color_use_as_albedo = true
		_vertex_material.roughness = 0.92
		_vertex_material.cull_mode = BaseMaterial3D.CULL_DISABLED
	return _vertex_material

static func _paint(node: Node) -> void:
	if node is MeshInstance3D:
		(node as MeshInstance3D).material_override = vertex_color_material()
	for child in node.get_children():
		_paint(child)

static func _hash(text: String) -> int:
	var value: int = 2166136261
	for byte in text.to_utf8_buffer():
		value = (value ^ int(byte)) * 16777619 & 0x7fffffff
	return value

static func owner_color(owner: String) -> Color:
	if owner.is_empty():
		return Color("#9ca3a8")
	return Color.from_hsv(float(_hash(owner) % 360) / 360.0, 0.58, 0.91)

static func _add(parent: Node3D, mesh: Mesh, pos: Vector3, color: Color, rot_y: float = 0.0) -> MeshInstance3D:
	var instance := MeshInstance3D.new()
	instance.mesh = mesh
	instance.material_override = material(color)
	instance.position = pos
	instance.rotation.y = rot_y
	parent.add_child(instance)
	return instance

static func _box(parent: Node3D, size: Vector3, pos: Vector3, color: Color) -> MeshInstance3D:
	var mesh := BoxMesh.new()
	mesh.size = size
	return _add(parent, mesh, pos, color)

## Gable roof over a w x d rectangle; the ridge runs along the longer side.
static func _roof(parent: Node3D, w: float, d: float, h: float, base_y: float, color: Color) -> void:
	var mesh := PrismMesh.new()
	if d >= w:
		mesh.size = Vector3(w, h, d)
		_add(parent, mesh, Vector3(0, base_y + h * 0.5, 0), color)
	else:
		mesh.size = Vector3(d, h, w)
		_add(parent, mesh, Vector3(0, base_y + h * 0.5, 0), color, PI * 0.5)

static func _cone(parent: Node3D, radius: float, height: float, pos: Vector3, color: Color) -> void:
	var mesh := CylinderMesh.new()
	mesh.top_radius = 0.0
	mesh.bottom_radius = radius
	mesh.height = height
	mesh.radial_segments = 7
	mesh.rings = 1
	_add(parent, mesh, pos + Vector3(0, height * 0.5, 0), color)

static func _cylinder(parent: Node3D, radius: float, height: float, pos: Vector3, color: Color) -> void:
	var mesh := CylinderMesh.new()
	mesh.top_radius = radius
	mesh.bottom_radius = radius
	mesh.height = height
	mesh.radial_segments = 8
	mesh.rings = 1
	_add(parent, mesh, pos + Vector3(0, height * 0.5, 0), color)

## The 3D node of one building, centred on its footprint at ground level. w/h: footprint in cells along x/y.
static func make(kind: String, w: int, h: int, object_id: String = "", owner: String = "") -> Node3D:
	var root := Node3D.new()
	root.name = "Building"
	var top := 0.0
	var model := _model_for(kind, w, h, object_id)
	if model != null:
		root.add_child(model)
		top = float(model.get_meta("top", 2.0))
	else:
		top = _procedural(root, kind, w, h, object_id)
	root.set_meta("kind", kind)
	root.set_meta("top", top)
	if not owner.is_empty() and not owner.begins_with("town:"):
		var flag := Node3D.new()
		flag.name = "OwnerFlag"
		root.add_child(flag)
		var x := w * CELL * 0.36
		var z := -h * CELL * 0.36
		_box(flag, Vector3(0.06, 1.1, 0.06), Vector3(x, top + 0.55, z), Color("#3b4650"))
		_box(flag, Vector3(0.5, 0.32, 0.05), Vector3(x + 0.27, top + 0.9, z), owner_color(owner))
	return root

# ---------- GLB models ----------
## Visual variants of one kind and size: files "<kind>_<variant>_<w>x<h>.glb". One is chosen per building from its object id, so a street
## of identical 1x1 houses looks mixed, and a given house always keeps its look.
const VARIANTS := {"house": ["panel", "brick", "modern"]}

static func model_path(kind: String, w: int, h: int, object_id: String = "") -> Dictionary:
	var names: Array = []
	if VARIANTS.has(kind):
		var found_variants: Array = []
		for variant in VARIANTS[kind]:
			if ResourceLoader.exists(MODEL_DIR + "%s_%s_%dx%d.glb" % [kind, variant, w, h]) or ResourceLoader.exists(MODEL_DIR + "%s_%s_%dx%d.glb" % [kind, variant, h, w]):
				found_variants.append(variant)
		if not found_variants.is_empty():
			var chosen: String = found_variants[_hash(object_id + kind) % found_variants.size()]
			names.append(["%s_%s_%dx%d.glb" % [kind, chosen, w, h], false])
			names.append(["%s_%s_%dx%d.glb" % [kind, chosen, h, w], true])
	names.append(["%s_%dx%d.glb" % [kind, w, h], false])
	names.append(["%s_%dx%d.glb" % [kind, h, w], true])
	for item in names:
		var path: String = MODEL_DIR + str(item[0])
		if ResourceLoader.exists(path):
			return {"path": path, "rotate": bool(item[1]) and w != h}
	return {}

## The mesh (with its material) of the first mesh in a GLB, for MultiMesh instancing of small repeated pieces such as road tiles. {} if absent.
static var _piece_cache: Dictionary = {}
static func piece(name: String) -> Dictionary:
	if _piece_cache.has(name):
		return _piece_cache[name]
	var out: Dictionary = {}
	var path := MODEL_DIR + name + ".glb"
	if ResourceLoader.exists(path):
		var scene = load(path)
		if scene is PackedScene:
			var instance: Node = (scene as PackedScene).instantiate()
			var found := _first_mesh(instance, Transform3D.IDENTITY)
			if not found.is_empty():
				out = found
			instance.free()
	_piece_cache[name] = out
	return out

static func _first_mesh(node: Node, xform: Transform3D) -> Dictionary:
	var here := xform
	if node is Node3D:
		here = xform * (node as Node3D).transform
	if node is MeshInstance3D and (node as MeshInstance3D).mesh != null:
		return {"mesh": (node as MeshInstance3D).mesh, "transform": here}
	for child in node.get_children():
		var found := _first_mesh(child, here)
		if not found.is_empty():
			return found
	return {}

static func _model_for(kind: String, w: int, h: int, object_id: String = "") -> Node3D:
	var found := model_path(kind, w, h, object_id)
	if found.is_empty():
		return null
	var path: String = found["path"]
	if not _model_cache.has(path):
		_model_cache[path] = load(path)
	var scene = _model_cache[path]
	if not scene is PackedScene:
		return null
	var instance: Node3D = (scene as PackedScene).instantiate() as Node3D
	if instance == null:
		return null
	_paint(instance)
	var box := _aabb(instance, Transform3D.IDENTITY)
	if box.size.x <= 0.001 or box.size.z <= 0.001:
		instance.free()
		return null
	var rotate: bool = found["rotate"]
	var span_x := (h if rotate else w) * CELL * FILL
	var span_z := (w if rotate else h) * CELL * FILL
	var s := minf(span_x / box.size.x, span_z / box.size.z)
	var pivot := Node3D.new()
	pivot.name = "Model"
	instance.scale = instance.scale * s
	var center := box.get_center()
	instance.position = Vector3(-center.x * s, -box.position.y * s, -center.z * s)
	pivot.add_child(instance)
	if rotate:
		pivot.rotation.y = PI * 0.5
	pivot.set_meta("top", box.size.y * s)
	return pivot

static func _aabb(node: Node, xform: Transform3D) -> AABB:
	var result := AABB()
	var first := true
	var here := xform
	if node is Node3D:
		here = xform * (node as Node3D).transform
	if node is MeshInstance3D and (node as MeshInstance3D).mesh != null:
		result = here * (node as MeshInstance3D).mesh.get_aabb()
		first = false
	for child in node.get_children():
		var sub := _aabb(child, here)
		if sub.size == Vector3.ZERO:
			continue
		if first:
			result = sub
			first = false
		else:
			result = result.merge(sub)
	return result

# ---------- procedural low-poly models (any kind without a GLB) ----------
const WALLS := [Color("#e8dcc0"), Color("#d9cdb0"), Color("#cfd8d4"), Color("#e2cdbd"), Color("#d6c6a4")]
const ROOFS := [Color("#b5533f"), Color("#7e6a55"), Color("#4f6f63"), Color("#9b4a3a"), Color("#5d6470")]

static func _procedural(root: Node3D, kind: String, w: int, h: int, object_id: String) -> float:
	var W := w * CELL
	var D := h * CELL
	var v := _hash(object_id + kind) % WALLS.size()
	match kind:
		"house":
			var height := 1.5 if w * h == 1 else 1.8
			_box(root, Vector3(W * 0.78, height, D * 0.78), Vector3(0, height * 0.5, 0), WALLS[v])
			_roof(root, W * 0.86, D * 0.86, 1.0, height, ROOFS[v])
			var long_x := W > D
			# a door and windows on the side facing the camera (+z or +x)
			if long_x:
				for i in range(w):
					_box(root, Vector3(0.36, 0.42, 0.04), Vector3(-W * 0.5 + CELL * (i + 0.5), height * 0.6, D * 0.39 + 0.02), Color("#8fb2c4"))
			else:
				for i in range(h):
					_box(root, Vector3(0.04, 0.42, 0.36), Vector3(W * 0.39 + 0.02, height * 0.6, -D * 0.5 + CELL * (i + 0.5)), Color("#8fb2c4"))
			_box(root, Vector3(0.34, 0.75, 0.04), Vector3(W * 0.15, 0.38, D * 0.39 + 0.02), Color("#5b4636"))
			return height + 1.0
		"shop":
			_box(root, Vector3(W * 0.84, 1.7, D * 0.84), Vector3(0, 0.85, 0), Color("#d8efe4"))
			_box(root, Vector3(W * 0.9, 0.14, D * 0.9), Vector3(0, 1.77, 0), Color("#c9d3cf"))
			_box(root, Vector3(W * 0.84, 0.12, 0.7), Vector3(0, 1.25, D * 0.42 + 0.3), Color("#e7b45d"))
			_box(root, Vector3(W * 0.6, 0.9, 0.05), Vector3(0, 0.55, D * 0.42 + 0.03), Color("#7fb0c2"))
			_box(root, Vector3(W * 0.5, 0.35, 0.08), Vector3(0, 2.05, D * 0.3), Color("#c94e3f"))
			return 2.3
		"warehouse":
			_box(root, Vector3(W * 0.88, 2.2, D * 0.88), Vector3(0, 1.1, 0), Color("#8a7d5c"))
			_roof(root, W * 0.92, D * 0.92, 0.8, 2.2, Color("#b5a47a"))
			_box(root, Vector3(W * 0.35, 1.4, 0.05), Vector3(0, 0.7, D * 0.44 + 0.03), Color("#4b5c65"))
			return 3.0
		"factory":
			_box(root, Vector3(W * 0.86, 2.6, D * 0.8), Vector3(0, 1.3, 0), Color("#668b9d"))
			for i in range(3):
				_roof(root, W * 0.86 / 3.0, D * 0.8, 0.6, 2.6, Color("#9eb7c1"))
				root.get_child(root.get_child_count() - 1).position.x = -W * 0.86 / 3.0 + W * 0.86 / 3.0 * i
			_cylinder(root, 0.3, 4.6, Vector3(W * 0.3, 0, -D * 0.28), Color("#536572"))
			return 4.6
		"mine":
			_box(root, Vector3(W * 0.5, 1.4, D * 0.5), Vector3(-W * 0.15, 0.7, D * 0.15), Color("#676e75"))
			_box(root, Vector3(0.18, 3.6, 0.18), Vector3(W * 0.18 - 0.4, 1.8, -D * 0.2), Color("#303d48"))
			_box(root, Vector3(0.18, 3.6, 0.18), Vector3(W * 0.18 + 0.4, 1.8, -D * 0.2), Color("#303d48"))
			_box(root, Vector3(1.1, 0.2, 0.3), Vector3(W * 0.18, 3.5, -D * 0.2), Color("#303d48"))
			_cone(root, 0.9, 0.8, Vector3(W * 0.25, 0, D * 0.25), Color("#3a3533"))
			return 3.6
		"grain_field":
			for i in range(5):
				_box(root, Vector3(W * 0.92, 0.1, D * 0.15), Vector3(0, 0.05, -D * 0.4 + i * D * 0.2), Color("#d6b95a") if i % 2 == 0 else Color("#b79a3f"))
			return 0.4
		"elevator":
			_box(root, Vector3(W * 0.5, 0.9, D * 0.8), Vector3(-W * 0.2, 0.45, 0), Color("#8a8f94"))
			for i in range(3):
				_cylinder(root, 0.7, 3.8, Vector3(W * 0.12 + i * 1.5 - 1.5 + W * 0.1, 0.0, 0.0), Color("#b9bfc4"))
			return 3.8
		"mill":
			_box(root, Vector3(W * 0.7, 2.2, D * 0.8), Vector3(0, 1.1, 0), Color("#cdbb94"))
			_roof(root, W * 0.74, D * 0.84, 0.9, 2.2, Color("#8a5a44"))
			_cylinder(root, 0.45, 3.2, Vector3(W * 0.32, 0.0, -D * 0.25), Color("#9a9d9f"))
			return 3.2
		"bread_plant":
			_box(root, Vector3(W * 0.84, 2.0, D * 0.8), Vector3(0, 1.0, 0), Color("#e6c98f"))
			_roof(root, W * 0.88, D * 0.84, 0.6, 2.0, Color("#a35a3c"))
			_cylinder(root, 0.28, 3.2, Vector3(W * 0.3, 0.0, -D * 0.28), Color("#6f6a66"))
			return 3.2
		"oil_well":
			_box(root, Vector3(W * 0.7, 0.2, D * 0.7), Vector3(0, 0.1, 0), Color("#6f6a5c"))
			_box(root, Vector3(0.14, 3.4, 0.14), Vector3(-0.5, 1.7, 0), Color("#4b5559"))
			_box(root, Vector3(0.14, 3.4, 0.14), Vector3(0.5, 1.7, 0), Color("#4b5559"))
			_box(root, Vector3(1.4, 0.16, 0.16), Vector3(0, 3.3, 0), Color("#4b5559"))
			return 3.5
		"gas_well":
			_box(root, Vector3(W * 0.7, 0.2, D * 0.7), Vector3(0, 0.1, 0), Color("#7a7d80"))
			_cylinder(root, 0.35, 1.8, Vector3(0, 0.2, 0), Color("#c0463a"))
			_cylinder(root, 0.12, 3.0, Vector3(0.9, 0.2, 0.6), Color("#8d949a"))
			return 3.2
		"sand_pit":
			_box(root, Vector3(W * 0.9, 0.12, D * 0.9), Vector3(0, 0.06, 0), Color("#d8c88f"))
			_cone(root, 1.1, 1.3, Vector3(-0.6, 0.12, -0.5), Color("#cdb77a"))
			_cone(root, 0.8, 1.0, Vector3(0.7, 0.12, 0.5), Color("#c4ad6d"))
			return 1.5
		"logging_camp":
			_box(root, Vector3(W * 0.9, 0.08, D * 0.9), Vector3(0, 0.04, 0), Color("#7c6a4f"))
			for i in range(4):
				_cylinder(root, 0.22, 1.6, Vector3(-W * 0.3 + i * 0.5, 0.1, D * 0.25), Color("#7a5a3a"))
			_box(root, Vector3(1.2, 1.1, 1.0), Vector3(W * 0.25, 0.55, -D * 0.25), Color("#9a7b52"))
			return 1.8
		"farm":
			for i in range(4):
				_box(root, Vector3(W * 0.9, 0.08, D * 0.12), Vector3(0, 0.04, -D * 0.4 + D * 0.12 + i * D * 0.16), Color("#c9ad6c") if i % 2 == 0 else Color("#8fa65e"))
			_box(root, Vector3(W * 0.36, 1.3, D * 0.36), Vector3(-W * 0.22, 0.65, -D * 0.22), Color("#b9463a"))
			_roof(root, W * 0.4, D * 0.4, 0.7, 1.3, Color("#6b4a3a"))
			root.get_child(root.get_child_count() - 1).position += Vector3(-W * 0.22, 0, -D * 0.22)
			return 2.0
		"school":
			_box(root, Vector3(W * 0.86, 2.6, D * 0.7), Vector3(0, 1.3, 0), Color("#e6d49a"))
			_box(root, Vector3(W * 0.9, 0.15, D * 0.74), Vector3(0, 2.68, 0), Color("#9a8f74"))
			_box(root, Vector3(0.06, 1.6, 0.06), Vector3(W * 0.36, 2.75 + 0.8, D * 0.3), Color("#3b4650"))
			_box(root, Vector3(0.6, 0.38, 0.04), Vector3(W * 0.36 + 0.32, 3.4, D * 0.3), Color("#3d7fc0"))
			return 2.8
		"hospital":
			_box(root, Vector3(W * 0.86, 3.0, D * 0.86), Vector3(0, 1.5, 0), Color("#f1ece6"))
			_box(root, Vector3(1.4, 0.06, 0.4), Vector3(0, 3.03, 0), Color("#d23b3b"))
			_box(root, Vector3(0.4, 0.06, 1.4), Vector3(0, 3.03, 0), Color("#d23b3b"))
			return 3.1
		"park":
			_box(root, Vector3(W * 0.94, 0.06, D * 0.94), Vector3(0, 0.03, 0), Color("#5f9a5a"))
			_box(root, Vector3(W * 0.94, 0.07, 0.4), Vector3(0, 0.04, 0), Color("#d0c39e"))
			for i in range(4):
				var p := Vector3((-0.3 + 0.6 * (i % 2)) * W, 0.06, (-0.3 + 0.6 * (i / 2)) * D)
				_cylinder(root, 0.1, 0.5, p, Color("#6b4f37"))
				_cone(root, 0.6, 1.4, p + Vector3(0, 0.45, 0), Color("#3f7a4a"))
			return 1.9
	_box(root, Vector3(W * 0.8, 1.6, D * 0.8), Vector3(0, 0.8, 0), Color("#b1a67c"))
	return 1.6
