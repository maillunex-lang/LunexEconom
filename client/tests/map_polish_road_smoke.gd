extends SceneTree
const Map = preload("res://screens/map.tscn")
const Mock = preload("res://tests/world_mock.gd")
const Service = preload("res://enterprises/api.gd")
var page: Control
var mock: Node
func _initialize() -> void:
    call_deferred("_run")

func _run() -> void:
    root.size=Vector2i(1280,720)
    mock=Mock.new()
    root.add_child(mock)
    page=Map.instantiate()
    root.add_child(page)
    page.api.mock=Callable(mock,"respond")
    page.open("https://roads-v207c.invalid/api","token")
    for i in range(300):
        await process_frame
        if page.stream.parcels.has(Vector2i(1,0)) and page.stream.chunks.has(Vector2i(1,0)):
            break
    assert(page.stream.chunks.has(Vector2i(1,0)),"road sample chunk not available")
    var purchased: Dictionary=await page.stream.buy(2,0)
    assert(purchased.get("code",0)==201)
    for i in range(20):
        await process_frame
    page._on_parcel_tapped(2,0)
    assert(str(page.stream.parcel_at(2,0).get("owner_kind",""))=="player","own parcel missing")
    var service: Node=Service.new()
    root.add_child(service)
    service.configure(page.api)
    var before: Dictionary=await service.create("field",2,0,14,3)
    assert(before.get("data",{}).get("error","")=="no_road_access","no-road building should be rejected")
    page._begin_road()
    assert(page.canvas.road_mode,"map did not enter road editing mode")
    for cell in [Vector2i(17,1),Vector2i(17,2),Vector2i(16,2),Vector2i(16,3)]:
        page._on_road_cell(cell)
    assert(page.road_selection.size()==4,"adjacent road cells not selected")
    assert(page.canvas.road_preview.size()==4,"road preview missing")
    page._finish_road()
    for i in range(180):
        await process_frame
        if mock.road_posts.size()>0 and not page.canvas.road_mode:
            break
    assert(mock.road_posts.size()==1,"POST /world/roads not submitted")
    assert(str(mock.road_posts[0].get("request_id","")).begins_with("road."),"idempotent request id missing")
    assert(mock.road_cells.has("16,3"),"road did not reach building access")
    assert(not page.canvas.road_mode and page.canvas.road_preview.is_empty(),"road preview not closed")
    var after: Dictionary=await service.create("field",2,0,14,3)
    assert(int(after.get("code",0))==201,"building still failed after road: "+str(after))
    assert(mock.built.size()==1,"enterprise not created")
    page._on_parcel_tapped(2,0)
    var picked := {}
    page.build_requested.connect(func(parcel: Dictionary, position: Vector2i):
        picked["parcel"]=parcel
        picked["cell"]=position)
    page._build_selected()
    assert(picked.has("parcel") and picked["parcel"].get("site_cells",[]).size()>0,
        "building picker did not receive zone/road/occupation cells")
    print("map polish road smoke OK: no-road refusal, adjacent preview, idempotency key, road POST, build success")
    page.queue_free()
    service.queue_free()
    quit(0)
