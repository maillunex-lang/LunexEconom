extends SceneTree
const Forest = preload("res://theme/forest_glass.gd")
func _initialize() -> void:
    var theme := Forest.create_theme()
    var result := ResourceSaver.save(theme,"res://theme/forest_glass.tres")
    assert(result == OK)
    print("Forest Glass theme resource saved")
    quit(0)
