extends Control
## V2-03c: UI foundation. Network, token refresh, RSA and presence stay intact.
const UpdatesPanel = preload("res://screens/updates.tscn")
const Strings = preload("res://i18n/strings.gd")
const Forest = preload("res://theme/forest_glass.gd")
const SafeArea = preload("res://ui/safe_area.gd")
const Router = preload("res://screens/router.gd")
const LoginScreen = preload("res://screens/login.tscn")
const HeadquartersScreen = preload("res://screens/headquarters.tscn")
const SettingsScreen = preload("res://screens/settings.tscn")
const MapScreen = preload("res://screens/map.tscn")
const EnterprisesScreen = preload("res://screens/enterprises.tscn")
const BuildScreen = preload("res://screens/build.tscn")
const SupplyScreen = preload("res://screens/supply.tscn")
const StoreScreen = preload("res://screens/store.tscn")
const MoreScreen = preload("res://screens/more.tscn")
const FinanceScreen = preload("res://screens/finance.tscn")
const NavBar = preload("res://ui/navigation_bar.gd")
const TutorialState = preload("res://tutorial/state.gd")
const TutorialGuide = preload("res://tutorial/guide.gd")
const TutorialService = preload("res://tutorial/service.gd")
const PublicBase = preload("res://config/public_base.gd")
const VERSION := "2.1.0"
const PUBLIC_KEY_PATH := "res://security/config_public.pem"
const SESSION_PATH := "user://platform_session.cfg"
const CONFIG_CACHE_PATH := "user://platform_config.cfg"
var base_url := PublicBase.api_url()
var shell: MarginContainer
var router: Control
var login_screen: Control
var headquarters_screen: Control
var settings_screen: Control
var map_screen: Control
var enterprises_screen: Control
var build_screen: Control
var supply_screen: Control
var store_screen: Control
var more_screen: Control
var finance_screen: Control
var navigation_bar: Control
var tutorial_state: RefCounted
var tutorial_guide: Control
var tutorial_service: Node
var account_id := ""
var login_card: PanelContainer
var form: VBoxContainer
var headquarters: VBoxContainer
var login_username: LineEdit
var login_email: LineEdit
var login_password: LineEdit
var status_label: Label
var hq_status: Label
var wallet_label: Label
var calendar_label: Label
var update_screen: Control
var token := ""
var refresh_token := ""
var _auth_busy := false

func _ready() -> void:
    theme = Forest.create_theme(get_viewport_rect().size)
    var backdrop := ColorRect.new()
    backdrop.color = Forest.COLORS.background
    backdrop.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    backdrop.mouse_filter = Control.MOUSE_FILTER_IGNORE
    add_child(backdrop)
    shell = MarginContainer.new()
    shell.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    add_child(shell)
    router = Router.new()
    shell.add_child(router)
    login_screen = LoginScreen.instantiate()
    headquarters_screen = HeadquartersScreen.instantiate()
    settings_screen = SettingsScreen.instantiate()
    map_screen = MapScreen.instantiate()
    enterprises_screen = EnterprisesScreen.instantiate()
    build_screen = BuildScreen.instantiate()
    supply_screen = SupplyScreen.instantiate()
    store_screen = StoreScreen.instantiate()
    more_screen = MoreScreen.instantiate()
    finance_screen = FinanceScreen.instantiate()
    router.register_screen("login",login_screen)
    router.register_screen("headquarters",headquarters_screen)
    router.register_screen("settings",settings_screen)
    router.register_screen("map",map_screen)
    router.register_screen("enterprises",enterprises_screen)
    router.register_screen("build",build_screen)
    router.register_screen("supply",supply_screen)
    router.register_screen("store",store_screen)
    router.register_screen("more",more_screen)
    router.register_screen("finance",finance_screen)
    # Existing V2-01b implementation stays untouched.
    update_screen = UpdatesPanel.instantiate()
    router.register_screen("updates", update_screen)
    update_screen.manager.state_changed.connect(_on_update_state)
    login_screen.authenticate.connect(_send_auth)
    headquarters_screen.refresh_requested.connect(_load_hq)
    headquarters_screen.navigate.connect(_navigate)
    headquarters_screen.logout_requested.connect(_logout)
    settings_screen.back_requested.connect(func(): router.back())
    map_screen.back_requested.connect(func(): router.back())
    map_screen.wallet_changed.connect(_load_hq)
    map_screen.stream.land_purchased.connect(func(_data: Dictionary): _refresh_tutorial())
    map_screen.build_requested.connect(_on_build_requested)
    map_screen.enterprise_requested.connect(_on_enterprise_requested)
    enterprises_screen.back_requested.connect(func(): router.back())
    enterprises_screen.wallet_changed.connect(_load_hq)
    enterprises_screen.supply_requested.connect(_on_supply_requested)
    enterprises_screen.store_requested.connect(_on_store_requested)
    build_screen.back_requested.connect(func(): router.back())
    supply_screen.back_requested.connect(func(): router.back())
    store_screen.back_requested.connect(func(): router.back())
    more_screen.navigate.connect(_navigate)
    more_screen.logout_requested.connect(_logout)
    navigation_bar = NavBar.new()
    navigation_bar.name = "BottomNavigation"
    navigation_bar.target_requested.connect(_navigate)
    navigation_bar.visible = false
    add_child(navigation_bar)
    router.changed.connect(_on_screen_changed)
    tutorial_state = TutorialState.new()
    tutorial_service = TutorialService.new()
    add_child(tutorial_service)
    tutorial_service.verified.connect(_on_tutorial_verified)
    tutorial_service.clock_observed.connect(_on_tutorial_clock)
    tutorial_guide = TutorialGuide.new()
    tutorial_guide.name = "TutorialGuide"
    tutorial_guide.refresh_requested.connect(_refresh_tutorial)
    add_child(tutorial_guide)
    tutorial_guide.set_progress(tutorial_state)
    settings_screen.reset_tutorial_requested.connect(_reset_tutorial)
    build_screen.built.connect(_on_enterprise_built)
    build_screen.preview_changed.connect(func(footprint: Dictionary): map_screen.canvas.preview = footprint; map_screen.canvas.queue_redraw())
    build_screen.road_preview_changed.connect(_show_planned_road)
    form = login_screen.form
    login_card = login_screen.card
    login_username = login_screen.username
    login_email = login_screen.email
    login_password = login_screen.password
    status_label = login_screen.status
    headquarters = headquarters_screen.get_child(0)
    headquarters.hide()
    hq_status = headquarters_screen.status
    wallet_label = headquarters_screen.wallet
    calendar_label = headquarters_screen.calendar
    router.reset("login")
    get_viewport().size_changed.connect(_on_viewport_resized)
    _on_viewport_resized()
    call_deferred("_restore_session")
    var presence_timer := Timer.new()
    presence_timer.name = "PresenceTimer"
    presence_timer.wait_time = 60.0
    presence_timer.timeout.connect(_presence_heartbeat)
    add_child(presence_timer)
    presence_timer.start()

func _navigate(screen: String) -> void:
    router.go(screen)
    if screen == "updates":
        update_screen.open()
    elif screen == "map":
        map_screen.api.refresh = Callable(self,"_refresh_map_access")
        map_screen.open(base_url,token)
    elif screen == "enterprises":
        enterprises_screen.open(_enterprise_transport())
        _refresh_tutorial()

func _show_planned_road(cells: Array) -> void:
    map_screen.canvas.road_preview.clear()
    for cell in cells:
        if cell is Array and cell.size() >= 2:
            map_screen.canvas.road_preview.append(Vector2i(int(cell[0]),int(cell[1])))
    map_screen.canvas.queue_redraw()


func _on_screen_changed(screen: String) -> void:
    if navigation_bar != null:
        navigation_bar.change_screen(screen)
    if tutorial_guide != null:
        tutorial_guide.change_screen(screen)
    if router != null and router.host != null:
        router.host.offset_bottom = -maxf(60.0, Forest.touch_size(get_viewport_rect().size) + 10.0) if navigation_bar.visible else 0.0
    if screen in ["map", "enterprises", "headquarters", "supply", "store"] and not account_id.is_empty():
        _refresh_tutorial()


func _enterprise_transport() -> Node:
    map_screen.api.base_url = base_url
    map_screen.api.token = token
    map_screen.api.refresh = Callable(self, "_refresh_map_access")
    return map_screen.api

func _on_build_requested(parcel: Dictionary, cell: Vector2i) -> void:
    router.go("build")
    build_screen.open(_enterprise_transport(), parcel, cell)

func _on_enterprise_requested(id: int) -> void:
    router.go("enterprises")
    enterprises_screen.open(_enterprise_transport(), id)

func _on_supply_requested(id: int) -> void:
    router.go("supply")
    supply_screen.open(_enterprise_transport(), id)

func _on_store_requested(id: int) -> void:
    router.go("store")
    store_screen.open(_enterprise_transport(), id)

func _on_enterprise_built() -> void:
    map_screen.canvas.preview = {}
    map_screen.canvas.road_preview.clear()
    map_screen.canvas.queue_redraw()
    for key in map_screen.stream.cache.keys():
        map_screen.stream.revalidate(key)
    _load_hq()
    map_screen.stream.poll_events()
    _refresh_tutorial()
    router.go("enterprises")
    enterprises_screen.open(_enterprise_transport())

func _refresh_map_access() -> String:
    if await _renew_tokens():
        return token
    return ""

func _on_update_state(_message: String, _can_install: bool, mandatory: bool) -> void:
    if mandatory and not token.is_empty():
        _navigate("updates")

func _show_headquarters() -> void:
    headquarters.show()
    router.reset("headquarters")
    if not account_id.is_empty() and not token.is_empty():
        _begin_tutorial()

func _show_login() -> void:
    headquarters.hide()
    router.reset("login")
    account_id = ""
    tutorial_service.active_account = ""
    tutorial_state.use_account("")
    tutorial_guide.redraw()

func _unhandled_key_input(event: InputEvent) -> void:
    if event is InputEventKey and event.pressed and not event.echo and (event.keycode == KEY_ESCAPE or event.keycode == KEY_BACK):
        if router.current == "updates" and update_screen.mandatory:
            get_viewport().set_input_as_handled()
        elif router.back():
            get_viewport().set_input_as_handled()

func _on_viewport_resized() -> void:
    if shell == null:
        return
    var size_now := get_viewport_rect().size
    theme = Forest.create_theme(size_now)
    SafeArea.apply(shell,size_now)
    var physical := DisplayServer.screen_get_size()
    var keyboard_px := DisplayServer.virtual_keyboard_get_height() if OS.has_feature("mobile") else 0
    var keyboard_canvas := float(keyboard_px) * size_now.y / maxf(1.0,float(physical.y))
    if keyboard_canvas > 0.0 and router.current == "login":
        var safe_bottom := shell.get_theme_constant("margin_bottom")
        shell.add_theme_constant_override("margin_bottom",safe_bottom + roundi(keyboard_canvas))
    login_screen.resize_ui(size_now,keyboard_canvas)
    headquarters_screen.resize_ui(size_now)
    settings_screen.resize_ui(size_now)
    map_screen.resize_ui(size_now)
    enterprises_screen.resize_ui(size_now)
    build_screen.resize_ui(size_now)
    supply_screen.resize_ui(size_now)
    store_screen.resize_ui(size_now)
    Forest.apply_touch(update_screen,size_now)
    if tutorial_guide != null:
        tutorial_guide.set_anchors_and_offsets_preset(Control.PRESET_TOP_RIGHT)
        tutorial_guide.offset_left = -minf(450.0, size_now.x * 0.39)
        tutorial_guide.offset_right = -float(shell.get_theme_constant("margin_right"))
        tutorial_guide.offset_top = float(shell.get_theme_constant("margin_top")) + 5.0
        tutorial_guide.offset_bottom = tutorial_guide.offset_top + (56.0 if tutorial_state.collapsed else 172.0)
        tutorial_guide.refresh_size(size_now)
    more_screen.resize_ui(size_now)
    finance_screen.resize_ui(size_now)
    if navigation_bar != null:
        navigation_bar.set_anchors_and_offsets_preset(Control.PRESET_BOTTOM_WIDE)
        var nav_height := maxf(60.0, Forest.touch_size(size_now) + 10.0)
        navigation_bar.offset_top = -nav_height - float(shell.get_theme_constant("margin_bottom"))
        navigation_bar.offset_bottom = -float(shell.get_theme_constant("margin_bottom"))
        if router != null and router.host != null:
            router.host.offset_bottom = -nav_height if navigation_bar.visible else 0.0
        navigation_bar.offset_left = float(shell.get_theme_constant("margin_left"))
        navigation_bar.offset_right = -float(shell.get_theme_constant("margin_right"))
        navigation_bar.refresh_size(size_now)

func _process(_delta: float) -> void:
    if router.current == "updates" and not update_screen.visible and not update_screen.mandatory:
        router.back()
    if not OS.has_feature("mobile") or router.current != "login":
        return
    var keyboard_height := DisplayServer.virtual_keyboard_get_height()
    if keyboard_height != _last_keyboard_height:
        _last_keyboard_height = keyboard_height
        _on_viewport_resized()

var _last_keyboard_height := 0

func _api(path: String, method: int = HTTPClient.METHOD_GET, payload: Dictionary = {}, authenticated: bool = false) -> Dictionary:
    base_url = PublicBase.api_url()
    if base_url.is_empty():
        return {"code": 0, "data": {"error": "service_unavailable"}}
    var req := HTTPRequest.new()
    req.timeout = 12.0
    add_child(req)
    var headers := PackedStringArray(["Content-Type: application/json", "X-Client-Version: " + VERSION])
    if authenticated and not token.is_empty():
        headers.append("Authorization: Bearer " + token)
    var body := JSON.stringify(payload) if method == HTTPClient.METHOD_POST else ""
    var err := req.request(base_url + path,headers,method,body)
    if err != OK:
        req.queue_free()
        return {"code":0,"data":{"error":"connection_failed"}}
    var finished: Array = await req.request_completed
    req.queue_free()
    var parsed: Variant = JSON.parse_string((finished[3] as PackedByteArray).get_string_from_utf8())
    return {"code":int(finished[1]),"data":parsed if parsed is Dictionary else {}}

func _save_refresh(value: String) -> void:
    var cfg := ConfigFile.new()
    cfg.set_value("session","refresh",value)
    cfg.save(SESSION_PATH)

func _load_refresh() -> String:
    var cfg := ConfigFile.new()
    if cfg.load(SESSION_PATH) != OK:
        return ""
    return str(cfg.get_value("session","refresh",""))

func _clear_tokens() -> void:
    token = ""
    refresh_token = ""
    if FileAccess.file_exists(SESSION_PATH):
        DirAccess.remove_absolute(ProjectSettings.globalize_path(SESSION_PATH))

func _renew_tokens() -> bool:
    if refresh_token.is_empty():
        return false
    var response: Dictionary = await _api("/auth/refresh",HTTPClient.METHOD_POST,{"refresh_token":refresh_token})
    if response.code != 200:
        _clear_tokens()
        return false
    var data: Dictionary = response.data
    token = str(data.get("access_token",""))
    refresh_token = str(data.get("refresh_token",""))
    if token.is_empty() or refresh_token.is_empty():
        _clear_tokens()
        return false
    _save_refresh(refresh_token)
    return true

func _restore_session() -> void:
    refresh_token = _load_refresh()
    if not refresh_token.is_empty() and await _renew_tokens():
        # Session restoration must not interrupt an explicit screen navigation
        # that happened while the refresh request was in flight.
        if router.current in ["", "login", "headquarters"]:
            _show_headquarters()
        _load_hq()
        _identify_tutorial()

func _send_auth(mode: String) -> void:
    if _auth_busy:
        return
    var username := login_username.text.strip_edges()
    var email := login_email.text.strip_edges()
    var password := login_password.text
    if username.length() < 3 or username.length() > 24 or password.length() < 10 or (mode == "register" and not email.contains("@")):
        status_label.text = Strings.get_text("auth.register.error.weak")
        return
    _auth_busy = true
    status_label.text = Strings.get_text("loading")
    var data := {"username":username,"password":password}
    if mode == "register":
        data["email"] = email
    var response: Dictionary = await _api("/auth/" + mode,HTTPClient.METHOD_POST,data)
    _auth_busy = false
    if response.code != 200 and response.code != 201:
        status_label.text = "Сервер временно недоступен. Попробуйте позже." if response.data.get("error", "") == "service_unavailable" else (Strings.get_text("error.auth") if response.code in [401, 403] else Strings.get_text("error.generic"))
        return
    if mode == "register":
        status_label.text = Strings.get_text("auth.login.title")
        return
    token = str((response.data as Dictionary).get("access_token",""))
    refresh_token = str((response.data as Dictionary).get("refresh_token",""))
    if token.is_empty() or refresh_token.is_empty():
        status_label.text = Strings.get_text("error.auth")
        return
    _save_refresh(refresh_token)
    account_id = str((response.data as Dictionary).get("account_id", ""))
    _show_headquarters()
    _load_hq()

func _authorized_api(path: String) -> Dictionary:
    var result: Dictionary = await _api(path,HTTPClient.METHOD_GET,{},true)
    if result.code == 401 and await _renew_tokens():
        result = await _api(path,HTTPClient.METHOD_GET,{},true)
    return result

func _begin_tutorial() -> void:
    if token.is_empty():
        return
    if account_id.is_empty():
        _identify_tutorial()
        return
    tutorial_state.use_account(account_id)
    tutorial_guide.set_progress(tutorial_state)
    navigation_bar.focus_tutorial(tutorial_state.step)
    tutorial_service.configure(_enterprise_transport(), account_id, tutorial_state.started_day)
    _refresh_tutorial()


func _identify_tutorial() -> void:
    var me: Dictionary = await _authorized_api("/auth/me")
    if int(me.get("code", 0)) == 200:
        account_id = str(me.get("data", {}).get("id", ""))
        _begin_tutorial()


func _refresh_tutorial() -> void:
    if account_id.is_empty() or tutorial_state.completed:
        return
    tutorial_service.configure(_enterprise_transport(), account_id, tutorial_state.started_day)
    var chunks: Array = map_screen.stream.parcels.keys()
    map_screen.api.set_meta("tutorial_chunks", chunks)
    tutorial_service.refresh()


func _on_tutorial_clock(day: int) -> void:
    if tutorial_state != null and not tutorial_state.account_id.is_empty():
        tutorial_state.note_start_day(day)


func _on_tutorial_verified(verified_step: int) -> void:
    tutorial_state.accept_verified(verified_step)
    navigation_bar.focus_tutorial(-1 if tutorial_state.completed else tutorial_state.step)
    tutorial_guide.redraw()


func _reset_tutorial() -> void:
    if account_id.is_empty():
        return
    tutorial_state.reset_progress()
    navigation_bar.focus_tutorial(tutorial_state.step)
    tutorial_guide.redraw()
    _refresh_tutorial()


func _presence_heartbeat() -> void:
    if token.is_empty():
        return
    var result: Dictionary = await _authorized_api("/auth/me")
    if result.code == 401 and token.is_empty():
        _show_login()
        status_label.text = Strings.get_text("error.auth")

func _load_hq() -> void:
    if token.is_empty():
        _show_login()
        return
    var wallet: Dictionary = await _authorized_api("/ledger/balance")
    if wallet.code == 200:
        wallet_label.text = Strings.get_text("finance.balance") + ": " + str((wallet.data as Dictionary).get("balance",0)) + " " + Strings.get_text("unit.rub")
    else:
        wallet_label.text = Strings.get_text("finance.balance") + ": " + Strings.get_text("status.offline")
    var clock: Dictionary = await _api("/clock")
    if clock.code == 200:
        var data: Dictionary = clock.data
        calendar_label.text = "%s %s · %s %s · %s %s" % [Strings.get_text("time.year"), data.get("year",2027), Strings.get_text("time.month"), data.get("month",1), Strings.get_text("time.day"), data.get("day",1)]
        hq_status.text = Strings.get_text("status.online")
    else:
        calendar_label.text = Strings.get_text("time.month") + ": " + Strings.get_text("status.offline")
        hq_status.text = Strings.get_text("error.network")

func _verify_signed_config(config: Dictionary, public_pem: String = "") -> bool:
    if int(config.get("schema",0)) != 1:
        return false
    if public_pem.is_empty():
        if not FileAccess.file_exists(PUBLIC_KEY_PATH):
            return false
        public_pem = FileAccess.get_file_as_string(PUBLIC_KEY_PATH)
    var key := CryptoKey.new()
    if key.load_from_string(public_pem,true) != OK:
        return false
    var raw := Marshalls.base64_to_raw(str(config.get("payload_b64","")))
    var sig := Marshalls.base64_to_raw(str(config.get("signature","")))
    if raw.is_empty() or sig.is_empty():
        return false
    var hasher := HashingContext.new()
    hasher.start(HashingContext.HASH_SHA256)
    hasher.update(raw)
    var sha256: PackedByteArray = hasher.finish()
    return Crypto.new().verify(HashingContext.HASH_SHA256,sha256,sig,key)

func _logout() -> void:
    var old := refresh_token
    var old_access := token
    _clear_tokens()
    _show_login()
    status_label.text = Strings.get_text("auth.logout")
    if not old.is_empty():
        token = old_access
        await _api("/auth/logout",HTTPClient.METHOD_POST,{"refresh_token":old},true)
        token = ""