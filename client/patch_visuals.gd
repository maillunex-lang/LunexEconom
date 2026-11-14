extends Node
## Optional visual-only texture bridge. No network requests and no autoload.
## Call activate_from_cache() explicitly after validating a local patch.
signal visuals_changed
const PATCH_SCRIPT = preload("res://livepatch.gd")
const SUPPORTED := ["farm", "mine", "factory", "warehouse", "school", "hospital", "park"]
const MAX_DIMENSION := 2048
var textures: Dictionary = {}
var active_revision: int = 0

func activate_from_cache() -> bool:
    var path := "user://livepatch/manifest.json"
    if not FileAccess.file_exists(path):
        return false
    var file := FileAccess.open(path, FileAccess.READ)
    if file == null:
        return false
    var data = JSON.parse_string(file.get_as_text())
    var verifier = PATCH_SCRIPT.new()
    if not verifier._valid_manifest(data):
        verifier.free()
        return false
    var next_textures: Dictionary = {}
    for kind in SUPPORTED:
        var ident: String = "building_" + kind
        var entry: Dictionary = {}
        for candidate in data["assets"]:
            if str(candidate.get("id", "")) == ident:
                entry = candidate
                break
        if entry.is_empty():
            continue
        var local_path := "user://livepatch/" + str(entry["sha256"]) + "." + str(entry["extension"])
        if not FileAccess.file_exists(local_path) or FileAccess.get_sha256(local_path) != str(entry["sha256"]):
            verifier.free()
            return false
        var img := Image.new()
        if img.load(local_path) != OK:
            verifier.free()
            return false
        if img.get_width() > MAX_DIMENSION or img.get_height() > MAX_DIMENSION or img.get_width() < 1 or img.get_height() < 1:
            verifier.free()
            return false
        next_textures[kind] = ImageTexture.create_from_image(img)
    verifier.free()
    textures = next_textures
    active_revision = int(data["revision"])
    visuals_changed.emit()
    return true

func texture_for(kind: String) -> Texture2D:
    return textures.get(kind, null)
