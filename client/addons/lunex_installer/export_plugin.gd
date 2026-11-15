@tool
extends EditorPlugin

var plugin: AndroidExportPlugin

func _enter_tree() -> void:
    plugin = AndroidExportPlugin.new()
    add_export_plugin(plugin)

func _exit_tree() -> void:
    remove_export_plugin(plugin)
    plugin = null

class AndroidExportPlugin extends EditorExportPlugin:
    func _get_name() -> String:
        return "LunexInstaller"

    func _supports_platform(platform: EditorExportPlatform) -> bool:
        return platform is EditorExportPlatformAndroid

    func _get_android_libraries(_platform: EditorExportPlatform, debug: bool) -> PackedStringArray:
        var file := "res://addons/lunex_installer/bin/debug/LunexInstaller-debug.aar" if debug else "res://addons/lunex_installer/bin/release/LunexInstaller-release.aar"
        return PackedStringArray([file]) if FileAccess.file_exists(file) else PackedStringArray()
