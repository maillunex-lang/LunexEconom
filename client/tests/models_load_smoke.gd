extends SceneTree
const STAGES := ["Foundation","Frame","Walls","Roof","Details"]
func _initialize() -> void:
    call_deferred("_run")

func _run() -> void:
    var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string("res://models/manifest.json"))
    assert(parsed is Dictionary)
    var models: Dictionary = parsed["models"]
    assert(models.size() == 64)
    var total := 0
    for name in models:
        var state := GLTFState.new()
        var document := GLTFDocument.new()
        var error := document.append_from_file("res://models/"+str(name),state)
        assert(error == OK,"GLTF import: "+str(name)+" error "+str(error))
        var scene := document.generate_scene(state)
        assert(scene != null)
        var triangles := 0
        for stage_name in STAGES:
            var stage := scene.find_child(stage_name,true,false)
            assert(stage != null,"missing "+stage_name+" "+str(name))
            triangles += _triangles(stage)
        assert(triangles > 0 and triangles <= 400,str(name)+" triangles "+str(triangles))
        assert(triangles == int(models[name]["triangles"]),str(name)+" expected "+str(models[name]["triangles"])+" got "+str(triangles))
        total += 1
        scene.free()
    print("models load OK: ",total," GLB, staged, triangles <=400")
    quit(0)

func _triangles(node: Node) -> int:
    var total := 0
    if node is MeshInstance3D:
        var mesh: Mesh = node.mesh
        if mesh != null:
            for i in range(mesh.get_surface_count()):
                var arrays := mesh.surface_get_arrays(i)
                var idx: PackedInt32Array = arrays[Mesh.ARRAY_INDEX]
                if not idx.is_empty():
                    total += idx.size()/3
                else:
                    var coords: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
                    total += coords.size()/3
    for child in node.get_children():
        total += _triangles(child)
    return total
