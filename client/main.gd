extends Control
## LunexEconom V2.1 platform client: Android landscape / Forest Glass.

const BACKGROUND := Color("0a201b")
const PANEL := Color("173a30")
const ACCENT := Color("b7efa5")
const MUTED := Color("a1b9ad")
const TEXT := Color("eef5e8")
const VERSION := "2.1.0"
const PUBLIC_KEY_PATH := "res://security/config_public.pem"
const SESSION_PATH := "user://platform_session.cfg"
const CONFIG_CACHE_PATH := "user://platform_config.cfg"

var base_url := "https://rikagro.ru/lunexeconom/api"
var shell: MarginContainer
var form: VBoxContainer
var headquarters: VBoxContainer
var login_username: LineEdit
var login_email: LineEdit
var login_password: LineEdit
var status_label: Label
var hq_status: Label
var wallet_label: Label
var calendar_label: Label
var update_label: Label
var token := ""
var refresh_token := ""
var _auth_busy := false

func _ready() -> void:
    get_viewport().size_changed.connect(_on_viewport_resized)
    _build_shell()
    _build_login()
    _build_headquarters()
    headquarters.hide()
    _on_viewport_resized()
    call_deferred("_restore_session")

func _on_viewport_resized() -> void:
    if shell == null:
        return
    var viewport_size: Vector2 = get_viewport_rect().size
    var safe_rect: Rect2i = DisplayServer.get_display_safe_area()
    var top := 18
    var left := 24
    var right := 24
    var bottom := 18
    if OS.has_feature("mobile") and safe_rect.size.x > 0:
        var sx: float = viewport_size.x / maxf(1.0, float(DisplayServer.screen_get_size().x))
        var sy: float = viewport_size.y / maxf(1.0, float(DisplayServer.screen_get_size().y))
        left = maxi(24, roundi(safe_rect.position.x * sx) + 12)
        top = maxi(18, roundi(safe_rect.position.y * sy) + 12)
        right = maxi(24, roundi((DisplayServer.screen_get_size().x - safe_rect.end.x) * sx) + 12)
        bottom = maxi(18, roundi((DisplayServer.screen_get_size().y - safe_rect.end.y) * sy) + 12)
    shell.add_theme_constant_override("margin_left",left)
    shell.add_theme_constant_override("margin_top",top)
    shell.add_theme_constant_override("margin_right",right)
    shell.add_theme_constant_override("margin_bottom",bottom)

func _build_shell() -> void:
    var background := ColorRect.new()
    background.color = BACKGROUND
    background.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    background.mouse_filter = Control.MOUSE_FILTER_IGNORE
    add_child(background)
    shell = MarginContainer.new()
    shell.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    add_child(shell)
    var center := CenterContainer.new()
    center.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    center.size_flags_vertical = Control.SIZE_EXPAND_FILL
    shell.add_child(center)
    var card := PanelContainer.new()
    card.custom_minimum_size = Vector2(550, 440)
    var style := StyleBoxFlat.new()
    style.bg_color = PANEL
    style.border_color = Color("386c57")
    style.set_border_width_all(1)
    style.set_corner_radius_all(24)
    style.content_margin_left = 36
    style.content_margin_right = 36
    style.content_margin_top = 20
    style.content_margin_bottom = 20
    card.add_theme_stylebox_override("panel", style)
    center.add_child(card)
    var stack := VBoxContainer.new()
    stack.add_theme_constant_override("separation", 13)
    card.add_child(stack)
    var title := Label.new()
    title.text = "БАШКИРИЯ: МЁД И НЕФТЬ"
    title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
    title.add_theme_font_size_override("font_size", 24)
    title.add_theme_color_override("font_color", ACCENT)
    stack.add_child(title)
    var subtitle := Label.new()
    subtitle.text = "Экономический тренажёр · V2.1"
    subtitle.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
    subtitle.add_theme_color_override("font_color", MUTED)
    stack.add_child(subtitle)
    form = VBoxContainer.new()
    form.add_theme_constant_override("separation", 10)
    stack.add_child(form)
    headquarters = VBoxContainer.new()
    headquarters.add_theme_constant_override("separation", 16)
    stack.add_child(headquarters)

func _field(placeholder: String, hidden: bool = false) -> LineEdit:
    var field := LineEdit.new()
    field.placeholder_text = placeholder
    field.secret = hidden
    field.custom_minimum_size.y = 45
    form.add_child(field)
    return field

func _button(label_text: String) -> Button:
    var btn := Button.new()
    btn.text = label_text
    btn.custom_minimum_size = Vector2(150, 45)
    btn.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    btn.add_theme_font_size_override("font_size", 15)
    return btn

func _label(value: String, parent: Node, font_size: int = 17) -> Label:
    var label := Label.new()
    label.text = value
    label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
    label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    label.add_theme_font_size_override("font_size",font_size)
    label.add_theme_color_override("font_color",TEXT)
    parent.add_child(label)
    return label

func _build_login() -> void:
    login_username = _field("Имя пользователя (3–24 символа)")
    login_email = _field("Электронная почта (для регистрации)")
    login_password = _field("Пароль (от 10 символов)", true)
    var buttons := HBoxContainer.new()
    buttons.add_theme_constant_override("separation",12)
    form.add_child(buttons)
    var login_button := _button("Войти")
    var register_button := _button("Создать аккаунт")
    buttons.add_child(login_button)
    buttons.add_child(register_button)
    login_button.pressed.connect(func(): _send_auth("login"))
    register_button.pressed.connect(func(): _send_auth("register"))
    status_label = _label("Войдите или создайте аккаунт",form,14)
    status_label.add_theme_color_override("font_color",MUTED)

func _build_headquarters() -> void:
    _label("Штаб-квартира",headquarters,27)
    wallet_label = _label("Кошелёк: загрузка…",headquarters,23)
    wallet_label.add_theme_color_override("font_color",ACCENT)
    calendar_label = _label("Игровое время: загрузка…",headquarters)
    _label("Предприятия появятся в следующем модуле.",headquarters,14)
    hq_status = _label("Связь с игровым сервером…",headquarters,14)
    update_label = _label("Подписанные обновления ещё не проверены",headquarters,14)
    var buttons := HBoxContainer.new()
    buttons.add_theme_constant_override("separation",10)
    headquarters.add_child(buttons)
    var refresh_btn := _button("Обновить данные")
    refresh_btn.pressed.connect(_load_hq)
    buttons.add_child(refresh_btn)
    var update_btn := _button("Проверить обновление")
    update_btn.pressed.connect(_check_update)
    buttons.add_child(update_btn)
    var logout := _button("Выйти")
    logout.pressed.connect(_logout)
    headquarters.add_child(logout)

func _api(path: String, method: int = HTTPClient.METHOD_GET, payload: Dictionary = {}, authenticated: bool = false) -> Dictionary:
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
        form.hide()
        headquarters.show()
        _load_hq()

func _send_auth(mode: String) -> void:
    if _auth_busy:
        return
    var username := login_username.text.strip_edges()
    var email := login_email.text.strip_edges()
    var password := login_password.text
    if username.length() < 3 or username.length() > 24 or password.length() < 10 or (mode == "register" and not email.contains("@")):
        status_label.text = "Проверьте имя, email и пароль (от 10 символов)"
        return
    _auth_busy = true
    status_label.text = "Подключаемся…"
    var data := {"username":username,"password":password}
    if mode == "register":
        data["email"] = email
    var response: Dictionary = await _api("/auth/" + mode,HTTPClient.METHOD_POST,data)
    _auth_busy = false
    if response.code != 200 and response.code != 201:
        status_label.text = "Ошибка: " + str((response.data as Dictionary).get("error",response.code))
        return
    if mode == "register":
        status_label.text = "Аккаунт создан. Теперь войдите."
        return
    token = str((response.data as Dictionary).get("access_token",""))
    refresh_token = str((response.data as Dictionary).get("refresh_token",""))
    if token.is_empty() or refresh_token.is_empty():
        status_label.text = "Сервер не выдал полноценную сессию"
        return
    _save_refresh(refresh_token)
    form.hide()
    headquarters.show()
    _load_hq()

func _authorized_api(path: String) -> Dictionary:
    var result: Dictionary = await _api(path,HTTPClient.METHOD_GET,{},true)
    if result.code == 401 and await _renew_tokens():
        result = await _api(path,HTTPClient.METHOD_GET,{},true)
    return result

func _load_hq() -> void:
    if token.is_empty():
        form.show()
        headquarters.hide()
        return
    var wallet: Dictionary = await _authorized_api("/ledger/balance")
    if wallet.code == 200:
        wallet_label.text = "Капитал: " + str((wallet.data as Dictionary).get("balance",0)) + " игровых ₽"
    else:
        wallet_label.text = "Капитал: недоступен"
    var clock: Dictionary = await _api("/clock")
    if clock.code == 200:
        var data: Dictionary = clock.data
        calendar_label.text = "Год %s · Месяц %s · День %s" % [data.get("year",2027),data.get("month",1),data.get("day",1)]
        hq_status.text = "До 09:00 (Уфа): %s сек · Сервер на связи" % [data.get("seconds_until_month",0)]
    else:
        calendar_label.text = "Игровые часы недоступны"
        hq_status.text = "Нет связи с игровыми часами"

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

func _check_update() -> void:
    update_label.text = "Проверяем подписанную конфигурацию…"
    var response: Dictionary = await _api("/config")
    if response.code != 200:
        update_label.text = "Конфигурация ещё не подписана или недоступна"
        return
    var config: Dictionary = response.data
    if not _verify_signed_config(config):
        update_label.text = "Обновление отклонено: подпись RSA не подтверждена"
        return
    var cache := ConfigFile.new()
    cache.load(CONFIG_CACHE_PATH)
    var previous := int(cache.get_value("config","revision",0))
    var revision := int(config.get("revision",0))
    if revision < previous:
        update_label.text = "Обновление отклонено: устаревшая ревизия"
        return
    var payload: Variant = JSON.parse_string(Marshalls.base64_to_raw(str(config.get("payload_b64",""))).get_string_from_utf8())
    if not payload is Dictionary:
        update_label.text = "Недействительный формат конфигурации"
        return
    cache.set_value("config","revision",revision)
    cache.save(CONFIG_CACHE_PATH)
    var latest := str((payload as Dictionary).get("android_version",VERSION))
    update_label.text = "Проверено · Ревизия %s · Версия %s" % [revision,latest]
    if latest != VERSION:
        update_label.text += " · Доступна новая версия"

func _logout() -> void:
    var old := refresh_token
    var old_access := token
    _clear_tokens()
    headquarters.hide()
    form.show()
    status_label.text = "Вы вышли из аккаунта"
    if not old.is_empty():
        token = old_access
        await _api("/auth/logout",HTTPClient.METHOD_POST,{"refresh_token":old},true)
        token = ""
