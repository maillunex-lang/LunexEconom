extends Node3D
## Standalone 2.5D renderer prototype; does not mutate the live 2D world.
const GRID = preload("res://world3d/grid_projection.gd")
const CHUNK_RADIUS := 2
var chunk_nodes: Dictionary = {}
var camera: Camera3D
var focus := Vector3.ZERO
var zoom_distance := 35.0
var touches: Dictionary = {}
var dragged := false
var selected_cell := Vector2i(-99999, -99999)
var selection: MeshInstance3D

func _ready() -> void:
    camera = Camera3D.new()
    camera.name = "IsometricCamera"
    camera.projection = Camera3D.PROJECTION_ORTHOGONAL
    camera.size = 32.0
    camera.rotation_degrees = Vector3(-35.264, 45.0, 0.0)
    camera.current = true
    add_child(camera)
    var sun := DirectionalLight3D.new()
    sun.rotation_degrees = Vector3(-55.0, -35.0, 0.0)
    sun.light_energy = 0.9
    add_child(sun)
    var env := WorldEnvironment.new()
    var environment := Environment.new()
    environment.background_mode = Environment.BG_COLOR
    environment.background_color = Color("#a8c3c5")
    environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
    environment.ambient_light_color = Color("#b8c5b5")
    environment.ambient_light_energy = 0.7
    env.environment = environment
    add_child(env)
    selection = MeshInstance3D.new()
    var highlight := BoxMesh.new()
    highlight.size = Vector3(1.92, 0.07, 1.92)
    selection.mesh = highlight
    var material := StandardMaterial3D.new()
    material.albedo_color = Color(0.95, 0.72, 0.17, 0.6)
    material.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
    material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
    selection.material_override = material
    selection.visible = false
    add_child(selection)
    _sync_camera()
    _update_chunks()

func _sync_camera() -> void:
    var rotation_basis := Basis.from_euler(Vector3(deg_to_rad(-35.264), deg_to_rad(45.0), 0.0))
    camera.global_position = focus + rotation_basis * Vector3(0.0, 0.0, zoom_distance)
    camera.look_at(focus, Vector3.UP)

func _update_chunks() -> void:
    var center := GRID.chunk_for(GRID.world_to_cell(focus))
    var wanted: Dictionary = {}
    for cx in range(center.x - CHUNK_RADIUS, center.x + CHUNK_RADIUS + 1):
        for cy in range(center.y - CHUNK_RADIUS, center.y + CHUNK_RADIUS + 1):
            var coord := Vector2i(cx, cy)
            wanted[coord] = true
            if not chunk_nodes.has(coord):
                var node := _make_chunk(coord)
                chunk_nodes[coord] = node
                add_child(node)
    for coord in chunk_nodes.keys():
        if not wanted.has(coord):
            chunk_nodes[coord].queue_free()
            chunk_nodes.erase(coord)

func _make_chunk(coord: Vector2i) -> Node3D:
    var root := Node3D.new()
    root.name = "Chunk_%d_%d" % [coord.x, coord.y]
    var mesh := PlaneMesh.new()
    mesh.size = Vector2(GRID.CHUNK_CELLS * GRID.CELL_METERS, GRID.CHUNK_CELLS * GRID.CELL_METERS)
    var ground := MeshInstance3D.new()
    ground.mesh = mesh
    var material := StandardMaterial3D.new()
    material.albedo_color = Color("#728b60") if (coord.x + coord.y) % 2 == 0 else Color("#79936a")
    material.roughness = 1.0
    ground.material_override = material
    ground.position = Vector3((coord.x * GRID.CHUNK_CELLS + GRID.CHUNK_CELLS * 0.5 - 0.5) * GRID.CELL_METERS, 0.0, (coord.y * GRID.CHUNK_CELLS + GRID.CHUNK_CELLS * 0.5 - 0.5) * GRID.CELL_METERS)
    root.add_child(ground)
    return root

func apply_server_cells(_cells: Dictionary) -> void:
    # Contract reserved for server snapshots. Prototype intentionally does not
    # invent buildings or take authority over placement.
    pass

func _unhandled_input(event: InputEvent) -> void:
    if event is InputEventScreenTouch:
        if event.pressed:
            touches[event.index] = event.position
            if touches.size() == 1:
                dragged = false
        else:
            if touches.size() == 1 and not dragged:
                _select_screen_cell(event.position)
            touches.erase(event.index)
            if touches.is_empty():
                dragged = false
    elif event is InputEventScreenDrag:
        if not touches.has(event.index):
            return
        var previous: Vector2 = touches[event.index]
        touches[event.index] = event.position
        if touches.size() == 1:
            if event.position.distance_to(previous) > 1.0:
                dragged = true
            _pan(event.position - previous)
        elif touches.size() == 2:
            var points := touches.values()
            var before_distance: float = (points[0] - points[1]).length()
            var prior := points.duplicate()
            var idx := touches.keys().find(event.index)
            prior[idx] = previous
            var prior_distance: float = (prior[0] - prior[1]).length()
            if prior_distance > 1.0 and before_distance > 1.0:
                camera.size = clampf(camera.size * prior_distance / before_distance, 12.0, 95.0)
            dragged = true

func _pan(delta: Vector2) -> void:
    var right := camera.global_transform.basis.x
    var up := camera.global_transform.basis.y
    var movement := (-right * delta.x + up * delta.y) * (camera.size / maxf(get_viewport().get_visible_rect().size.y, 1.0))
    focus += Vector3(movement.x, 0.0, movement.z)
    _sync_camera()
    _update_chunks()

func _select_screen_cell(screen_position: Vector2) -> void:
    var origin := camera.project_ray_origin(screen_position)
    var direction := camera.project_ray_normal(screen_position)
    var cell := GRID.cell_from_ground_ray(origin, direction)
    if cell.x == -2147483648:
        return
    selected_cell = cell
    selection.position = GRID.cell_to_world(cell) + Vector3(0.0, 0.07, 0.0)
    selection.visible = true