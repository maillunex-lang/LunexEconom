extends Node2D
## A single static draw list per chunk, automatically transformed by its parent.
const CHUNK := 12
var texture: Texture2D
var buildings: Array = []
var enterprise_info: Dictionary = {}
var event_cells: Dictionary = {}
var redraw_count := 0

func set_content(tile: Texture2D, cells: Array, metadata: Dictionary) -> void:
    texture = tile
    buildings = cells
    event_cells.clear()
    enterprise_info = metadata.duplicate()
    queue_redraw()

func update_building_cell(object_id: String,x: int,y: int,details: Dictionary) -> void:
    var key := "%d,%d" % [x,y]
    # Replace any snapshot cell with the same footprint instead of duplicating it.
    buildings = buildings.filter(func(item: Dictionary) -> bool:
        return not (int(item.get("x",0))==x and int(item.get("y",0))==y))
    event_cells[key] = {"x":x,"y":y,"ref":object_id}
    enterprise_info[object_id] = details
    redraw_count += 1
    queue_redraw()

func remove_building_cell(object_id: String,x: int,y: int) -> void:
    var key := "%d,%d" % [x,y]
    event_cells.erase(key)
    buildings = buildings.filter(func(item: Dictionary) -> bool:
        return not (int(item.get("x",0))==x and int(item.get("y",0))==y and str(item.get("ref",""))==object_id))
    redraw_count += 1
    queue_redraw()

func _draw() -> void:
    if texture == null:
        return
    draw_texture_rect(texture, Rect2(Vector2.ZERO,Vector2(CHUNK,CHUNK)), false)
    var grid := Color(0.8,0.94,0.8,0.19)
    for i in range(3):
        draw_line(Vector2(i*6,0),Vector2(i*6,12),grid,0.05)
        draw_line(Vector2(0,i*6),Vector2(12,i*6),grid,0.05)
    var all_cells: Array = buildings.filter(func(cell: Dictionary) -> bool:
        return not event_cells.has("%d,%d" % [int(cell.get("x",0)),int(cell.get("y",0))]))
    all_cells.append_array(event_cells.values())
    for cell in all_cells:
        var px := int(cell["x"]) - int(position.x)
        var py := int(cell["y"]) - int(position.y)
        var detail: Dictionary = enterprise_info.get(str(cell.get("ref","")), {})
        var stage := int(detail.get("stage_index",4))
        var color := Color("dfaa61") if stage == 4 else Color("a5a4a1")
        draw_rect(Rect2(px,py,1,1),color,true)
        draw_rect(Rect2(px,py,1,1),Color("563f30"),false,0.04)
