extends SceneTree

func _initialize() -> void:
    call_deferred("_run")

func _run() -> void:
    var args := OS.get_cmdline_user_args()
    if args.size() != 1:
        printerr("Expected PCK path: " + str(args))
        quit(10)
        return
    var before := FileAccess.file_exists("res://content/core_start/icon.png")
    if before:
        printerr("Asset unexpectedly already present")
        quit(11)
        return
    if not ProjectSettings.load_resource_pack(args[0], false):
        printerr("Pack mounting failed")
        quit(12)
        return
    var image = load("res://content/core_start/icon.png")
    if image == null:
        printerr("Imported PNG failed to load")
        quit(14)
        return
    print("runtime content pack mounted and asset available with no restart")
    quit(0)
