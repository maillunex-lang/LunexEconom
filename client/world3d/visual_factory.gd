extends RefCounted
## Deliberate low-cost placeholders, NOT final art assets.
const PALETTE := {
    "factory": Color("#a4a9a6"), "mine": Color("#8b7765"),
    "farm": Color("#c9ad6c"), "warehouse": Color("#718a92"),
    "shop": Color("#d2a18c"), "school": Color("#c7ba9c"),
    "hospital": Color("#f1e3db"), "house": Color("#d6c8aa"),
    "park": Color("#4d875a")
}

static func box(size: Vector3, color: Color) -> MeshInstance3D:
    var instance := MeshInstance3D.new()
    var mesh := BoxMesh.new()
    mesh.size = size
    instance.mesh = mesh
    var mat := StandardMaterial3D.new()
    mat.albedo_color = color
    mat.roughness = 0.95
    instance.material_override = mat
    return instance

static func building(kind: String, footprint: Array) -> Node3D:
    var node := Node3D.new()
    var min_x := 999999
    var min_y := 999999
    var max_x := -999999
    var max_y := -999999
    for cell in footprint:
        min_x = mini(min_x, cell.x)
        min_y = mini(min_y, cell.y)
        max_x = maxi(max_x, cell.x)
        max_y = maxi(max_y, cell.y)
    var width := max_x - min_x + 1
    var depth := max_y - min_y + 1
    var height := 2.5 if kind in ["factory", "warehouse", "mine"] else 1.8
    var body := box(Vector3(width * 1.85, height, depth * 1.85), PALETTE.get(kind, Color("#b2b5a2")))
    body.position.y = height * 0.5
    node.add_child(body)
    if kind == "factory":
        var chimney := box(Vector3(0.45, 2.6, 0.45), Color("#685d55"))
        chimney.position = Vector3(width * 0.55, 2.5, -depth * 0.45)
        node.add_child(chimney)
    elif kind == "mine":
        var tower := box(Vector3(0.7, 2.4, 0.7), Color("#4b5559"))
        tower.position = Vector3(0, 2.2, 0)
        node.add_child(tower)
    elif kind == "farm":
        var roof := box(Vector3(width * 1.95, 0.3, depth * 1.95), Color("#9d5143"))
        roof.position.y = height + 0.15
        node.add_child(roof)
    return node