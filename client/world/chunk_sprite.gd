extends Node2D
## A single static draw list per chunk, automatically transformed by its parent.
const CHUNK := 12
var texture: Texture2D
var buildings: Array = []
var enterprise_info: Dictionary = {}

func set_content(tile: Texture2D, cells: Array, metadata: Dictionary) -> void:
    texture = tile
    buildings = cells
    enterprise_info = metadata
    queue_redraw()

func _draw() -> void:
    if texture == null:
        return
    draw_texture_rect(texture, Rect2(Vector2.ZERO,Vector2(CHUNK,CHUNK)), false)
    var grid := Color(0.8,0.94,0.8,0.19)
    for i in range(3):
        draw_line(Vector2(i*6,0),Vector2(i*6,12),grid,0.05)
        draw_line(Vector2(0,i*6),Vector2(12,i*6),grid,0.05)
    for cell in buildings:
        var px := int(cell["x"]) - int(position.x)
        var py := int(cell["y"]) - int(position.y)
        var detail: Dictionary = enterprise_info.get(str(cell.get("ref","")), {})
        var stage := int(detail.get("stage_index",4))
        var color := Color("dfaa61") if stage == 4 else Color("a5a4a1")
        draw_rect(Rect2(px,py,1,1),color,true)
        draw_rect(Rect2(px,py,1,1),Color("563f30"),false,0.04)
