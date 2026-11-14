extends SceneTree
## Headless check: the account session survives closing the game, is encrypted on disk, is renewed at start,
## is wiped on sign-out / refusal, and an offline start keeps it. Always quits.

var failures := 0

func _initialize() -> void:
	call_deferred("_run")

func _check(condition: bool, label: String) -> void:
	if not condition:
		failures += 1
		print("FAIL: ", label)

func _fresh(path: String) -> Node:
	var session = load("res://game_session.gd").new()
	session.save_path = path
	get_root().add_child(session)
	return session

func _wait(seconds: float) -> void:
	await create_timer(seconds).timeout

func _run() -> void:
	var path := "user://session_test.cfg"
	if FileAccess.file_exists(path):
		DirAccess.remove_absolute(ProjectSettings.globalize_path(path))
	var token := "tok_" + "x".repeat(40)

	# --- storage ---
	var first := _fresh(path)
	_check(not first.load_saved(), "nothing stored yet")
	first.sign_in(token, "alice")
	_check(first.has_saved(), "sign-in is remembered")
	_check(not FileAccess.get_file_as_string(path).contains(token), "the token is not readable in the file")
	var second := _fresh(path)                                  # "the game was closed and reopened"
	_check(second.load_saved() and second.access_token == token and second.username == "alice", "session restored after restart")
	second.sign_out()
	_check(not second.has_saved() and not second.is_authenticated(), "sign-out wipes memory and disk")
	_check(not _fresh(path).load_saved(), "nothing to restore after sign-out")
	first.sign_in("", "nobody")
	_check(not first.has_saved(), "an empty token is not remembered")
	first.forget_saved()

	# --- damaged / foreign / implausible files are discarded, never trusted ---
	var f := FileAccess.open(path, FileAccess.WRITE)
	f.store_string("garbage that is not an encrypted config")
	f.close()
	_check(not _fresh(path).load_saved() and not FileAccess.file_exists(path), "a damaged file is rejected and deleted")
	var cfg := ConfigFile.new()
	cfg.set_value("session", "token", "short")
	cfg.save_encrypted_pass(path, "lunex-session-v1:" + OS.get_unique_id())
	_check(not _fresh(path).load_saved() and not FileAccess.file_exists(path), "an implausible token is rejected and deleted")
	cfg = ConfigFile.new()
	cfg.set_value("session", "token", token)
	cfg.save_encrypted_pass(path, "another device")
	_check(not _fresh(path).load_saved(), "a file encrypted for another device is rejected")
	DirAccess.remove_absolute(ProjectSettings.globalize_path(path))

	# --- the entry screen (uses the real autoload; the real save path is restored afterwards) ---
	var auto = get_root().get_node_or_null("GameSession")
	_check(auto != null, "GameSession autoload is registered")
	if auto != null:
		auto.save_path = path
		auto.sign_in(token, "alice")
		auto.access_token = ""                                    # simulate a fresh process that only has the file
		auto.username = ""
		var menu: Control = load("res://main.tscn").instantiate()
		menu.api_base = "http://127.0.0.1:9"                      # refused at once: the "offline" case
		get_root().add_child(menu)
		await _wait(2.0)
		_check(auto.is_authenticated() and auto.has_saved(), "offline start keeps the remembered session")
		_check(menu.status_label != null and menu.status_label.text.contains("Нет связи"), "offline start explains itself: " + str(menu.status_label.text if menu.status_label != null else ""))

		# the server refuses the remembered session -> it is wiped and the player is asked to sign in again
		menu.pending = "/auth/rotate"
		menu._on_response(HTTPRequest.RESULT_SUCCESS, 401, PackedStringArray(), '{"error":"unauthorized"}'.to_utf8_buffer())
		_check(not auto.is_authenticated() and not auto.has_saved(), "a refused session is wiped")
		_check(menu.status_label.text.contains("Войдите снова"), "refusal asks to sign in again")

		# the server renews the session -> the NEW token is the one remembered
		auto.sign_in(token, "alice")
		menu.pending = "/auth/rotate"
		var renewed := "new_" + "y".repeat(40)
		menu._on_response(HTTPRequest.RESULT_SUCCESS, 200, PackedStringArray(), JSON.stringify({"token": renewed, "username": "alice", "expires_at": 1}).to_utf8_buffer())
		_check(auto.access_token == renewed and auto.has_saved(), "renewed token replaces the old one")
		var again := _fresh(path)
		_check(again.load_saved() and again.access_token == renewed, "the renewed token survives a restart")

		# "Выйти" leaves the device even when the network is gone
		menu.pending = "/auth/logout"
		menu._on_response(HTTPRequest.RESULT_CANT_CONNECT, 0, PackedStringArray(), PackedByteArray())
		_check(not auto.is_authenticated() and not auto.has_saved(), "sign-out works offline")

		# inside the game: "Меню" has "Выйти из аккаунта", which forgets the remembered login
		auto.sign_in(token, "alice")
		auto.access_token = ""                                    # no network call in the test; the saved file is what matters
		var world: Control = load("res://world.tscn").instantiate()
		get_root().add_child(world)
		await process_frame
		await process_frame
		for child in world.get_node("UIOverlay/BottomNavigation").get_children():
			if child is Button and child.text == "Меню":
				child.pressed.emit()
		await process_frame
		var leave: Button = null
		for node in world.section_panel.find_children("*", "Button", true, false):
			if node.text == "Выйти из аккаунта":
				leave = node
		_check(leave != null and leave.is_visible_in_tree(), "the menu offers to sign out")
		_check(world.account_actions != null and world.account_actions.visible, "account actions are visible in the menu only")
		_check(auto.has_saved(), "the remembered login exists before sign-out")
		if leave != null:
			leave.pressed.emit()
			await process_frame
		_check(not auto.has_saved() and not auto.is_authenticated(), "signing out inside the game forgets the login")
		auto.save_path = "user://session.cfg"
	if FileAccess.file_exists(path):
		DirAccess.remove_absolute(ProjectSettings.globalize_path(path))
	print("SESSION_PERSISTENCE_SMOKE_PASS" if failures == 0 else "SESSION_PERSISTENCE_SMOKE_FAILED " + str(failures))
	quit(1 if failures > 0 else 0)
