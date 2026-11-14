extends Node
## Account session. The access token is kept in RAM and, so that the player does not have to sign in again after closing the game,
## remembered on this device in the app's private storage (user://), encrypted with a key derived from the device id.
## It is wiped on every sign-out, whenever the server refuses it, and by "Выйти". The server-side session expires after 7 days
## and is renewed (rotated) at each start. Local encryption is defence in depth: the Android app sandbox is the main protection.
var access_token: String = ""
var username: String = ""
var save_path := "user://session.cfg"      # overridable for tests

func _secret() -> String:
    return "lunex-session-v1:" + OS.get_unique_id()

func sign_in(token: String, name: String) -> void:
    access_token = token
    username = name
    _save()

func sign_out() -> void:
    access_token = ""
    username = ""
    forget_saved()

func is_authenticated() -> bool:
    return not access_token.is_empty()

func _save() -> void:
    if access_token.is_empty():
        return
    var config := ConfigFile.new()
    config.set_value("session", "token", access_token)
    config.set_value("session", "username", username)
    if config.save_encrypted_pass(save_path, _secret()) != OK:
        push_warning("session could not be remembered on this device")

## Restores a remembered session into memory. False when nothing usable is stored (a damaged or foreign file is deleted).
func load_saved() -> bool:
    if not FileAccess.file_exists(save_path):
        return false
    var config := ConfigFile.new()
    if config.load_encrypted_pass(save_path, _secret()) != OK:
        forget_saved()
        return false
    var token := str(config.get_value("session", "token", ""))
    if token.length() < 20 or token.length() > 200:
        forget_saved()
        return false
    access_token = token
    username = str(config.get_value("session", "username", "")).substr(0, 40)
    return true

func has_saved() -> bool:
    return FileAccess.file_exists(save_path)

func forget_saved() -> void:
    if FileAccess.file_exists(save_path):
        DirAccess.remove_absolute(ProjectSettings.globalize_path(save_path))
