extends SceneTree
## Safe offline headless smoke test: no world scene, auth or network requests.

func _initialize() -> void:
    call_deferred("_run")


func _run() -> void:
    var canvas := Control.new()
    root.add_child(canvas)
    var rank = load("res://leaderboard_panel.gd").new()
    canvas.add_child(rank)
    rank.show()
    rank.choose_sort("income")
    rank.render({"top": [{"rank": 1, "owner": "alice", "name": "Алиса",
        "npc": false, "income": 7000, "networth": 9000, "buildings": 2}],
        "me": {"rank": 1}, "total": 1})
    var feed = load("res://feed_panel.gd").new()
    canvas.add_child(feed)
    feed.show()
    feed.render({"events": [{"kind": "build", "title": "Построена ферма",
        "month_index": 0}], "total": 1})
    if rank.get_child_count() == 0 or feed.get_child_count() == 0:
        push_error("Stats panel was not instantiated")
        quit(1)
        return
    var world_script = load("res://world_screen.gd")
    if world_script == null:
        push_error("world_screen.gd did not compile")
        quit(1)
        return
    print("STATS_PANELS_SMOKE_PASS")
    quit(0)
