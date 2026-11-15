extends SceneTree
const BuildingModels = preload("res://world3d/building_models.gd")
# QA-only rendering; no world/server connection.
var count := 0
var root3d: Node3D
var viewport: SubViewport

func _initialize() -> void:
    viewport = SubViewport.new()
    viewport.size = Vector2i(960, 540)
    viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
    viewport.own_world_3d = true
    root.add_child(viewport)
    root3d = Node3D.new()
    viewport.add_child(root3d)
    var environment := WorldEnvironment.new()
    environment.environment = Environment.new()
    environment.environment.background_mode = Environment.BG_COLOR
    environment.environment.background_color = Color(0.14, 0.18, 0.22)
    root3d.add_child(environment)
    var sun := DirectionalLight3D.new()
    sun.rotation_degrees = Vector3(-55, 30, -20)
    root3d.add_child(sun)
    var camera := Camera3D.new()
    camera.position = Vector3(9, 8, 11)
    camera.current = true
    root3d.add_child(camera)
    camera.look_at.call_deferred(Vector3(0, 1, 0))
    var model := BuildingModels.make("factory", 3, 2, "qa-factory")
    root3d.add_child(model)

func _process(_delta: float) -> bool:
    count += 1
    if count == 20:
        var path := OS.get_environment("LUNEX_QA_SCREENSHOT")
        if path.is_empty():
            push_error("LUNEX_QA_SCREENSHOT required")
            quit(2)
        else:
            var err := viewport.get_texture().get_image().save_png(path)
            print("QA screenshot status: ", err, " path=", path)
            quit(0 if err == OK else 2)
    return false