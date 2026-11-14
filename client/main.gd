extends Control
## Forest Glass entry screen for Android landscape. Authentication is server-backed.
const API := "https://rikagro.ru/lunexeconom/api"
var request: HTTPRequest
var form: VBoxContainer
var status_label: Label
var username: LineEdit
var email: LineEdit
var password: LineEdit
var security_email: LineEdit
var security_code: LineEdit
var new_password: LineEdit
var login_id: LineEdit
var token := ""
var api_base := API          # tests only
var mode := "home"
var busy := false
var pending := ""
var reduce_motion := false
var music_enabled := true

func _ready() -> void:
    if OS.has_feature("mobile"):
        DisplayServer.screen_set_orientation(DisplayServer.SCREEN_SENSOR_LANDSCAPE)
    for child in get_children():
        if child.name != "Background":
            child.queue_free()
    request = HTTPRequest.new()
    request.timeout = 15.0        # never hang on a bad connection
    add_child(request)
    request.request_completed.connect(_on_response)
    get_viewport().size_changed.connect(_layout)
    _show_home()
    AssetDownloader.start()
    call_deferred("_layout")
    # Remembered account: check it with the server (this also renews it) and go straight into the game.
    if GameSession.load_saved():
        call_deferred("_resume")

func _panel() -> void:
    var old_panel := get_node_or_null("MenuSafeArea")
    if old_panel != null:
        old_panel.name = "RetiredMenu"
        old_panel.queue_free()
    var margin := MarginContainer.new()
    margin.name = "MenuSafeArea"
    margin.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    margin.add_theme_constant_override("margin_left", 48)
    margin.add_theme_constant_override("margin_right", 48)
    margin.add_theme_constant_override("margin_top", 20)
    margin.add_theme_constant_override("margin_bottom", 20)
    add_child(margin)
    var center := CenterContainer.new()
    center.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    center.size_flags_vertical = Control.SIZE_EXPAND_FILL
    margin.add_child(center)
    var glass := PanelContainer.new()
    glass.custom_minimum_size = Vector2(440, 0)
    var style := StyleBoxFlat.new()
    style.bg_color = Color(0.07, 0.16, 0.14, 0.94)
    style.border_color = Color(0.35, 0.67, 0.51, 0.7)
    style.set_border_width_all(1)
    style.set_corner_radius_all(20)
    style.content_margin_left = 24
    style.content_margin_right = 24
    style.content_margin_top = 16
    style.content_margin_bottom = 16
    glass.add_theme_stylebox_override("panel", style)
    center.add_child(glass)
    form = VBoxContainer.new()
    form.add_theme_constant_override("separation", 9)
    glass.add_child(form)
    _label("БАШКИРИЯ: МЁД И НЕФТЬ", 26)
    _label("Экономическая онлайн-стратегия", 15)
    status_label = _label("", 14)

func _layout() -> void:
    var margin := get_node_or_null("MenuSafeArea") as MarginContainer
    if margin == null: return
    var view := get_viewport_rect().size
    var screen := DisplayServer.screen_get_size()
    var safe := DisplayServer.get_display_safe_area()
    var left := 24.0
    var right := 24.0
    var top := 12.0
    var bottom := 12.0
    if OS.has_feature("mobile") and screen.x > 0 and screen.y > 0 and safe.size.x > 0 and safe.size.y > 0:
        var sx := view.x / float(screen.x)
        var sy := view.y / float(screen.y)
        left = maxf(left, float(safe.position.x) * sx + 12.0)
        right = maxf(right, float(screen.x - safe.end.x) * sx + 12.0)
        top = maxf(top, float(safe.position.y) * sy + 8.0)
        bottom = maxf(bottom, float(screen.y - safe.end.y) * sy + 8.0)
    margin.add_theme_constant_override("margin_left", int(left))
    margin.add_theme_constant_override("margin_right", int(right))
    margin.add_theme_constant_override("margin_top", int(top))
    margin.add_theme_constant_override("margin_bottom", int(bottom))

func _label(value: String, font_size: int) -> Label:
    var item := Label.new()
    item.text = value
    item.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
    item.add_theme_font_size_override("font_size", font_size)
    form.add_child(item)
    return item

func _button(value: String, action: Callable) -> void:
    var button := Button.new()
    button.text = value
    button.custom_minimum_size.y = 48
    button.pressed.connect(action)
    form.add_child(button)

func _field(hint: String, secret: bool = false) -> LineEdit:
    var item := LineEdit.new()
    item.placeholder_text = hint
    item.secret = secret
    item.custom_minimum_size.y = 43
    form.add_child(item)
    return item

func _resume() -> void:
    if GameSession.is_authenticated():
        _send("/auth/rotate", {})
        status_label.text = "Входим в аккаунт " + GameSession.username + "..."

func _show_home() -> void:
    mode = "home"
    _panel()
    if GameSession.is_authenticated():
        _button("ПРОДОЛЖИТЬ: " + GameSession.username, func(): _resume())
    _button("ВОЙТИ В ИГРУ", func(): _show_login())
    _button("СОЗДАТЬ АККАУНТ", func(): _show_register())
    _button("НАСТРОЙКИ", func(): _show_settings())
    _button("ВЫХОД", func(): get_tree().quit())
    _layout()

func _show_login() -> void:
    mode = "login"
    _panel()
    login_id = _field("Логин или электронная почта")
    password = _field("Пароль", true)
    _button("ВОЙТИ", func(): _submit_login())
    _button("ЗАБЫЛИ ПАРОЛЬ?", func(): _show_recovery())
    _button("ПОДТВЕРДИТЬ EMAIL", func(): _show_verification())
    _button("НАЗАД", func(): _show_home())
    _layout()

func _show_register() -> void:
    mode = "register"
    _panel()
    username = _field("Имя игрока (3–24 символа)")
    email = _field("Электронная почта")
    password = _field("Пароль (минимум 4 символа)", true)
    _button("ЗАРЕГИСТРИРОВАТЬСЯ", func(): _submit_register())
    _button("НАЗАД", func(): _show_home())
    _layout()

func _show_recovery() -> void:
    mode = "recovery"
    _panel()
    security_email = _field("Email аккаунта")
    security_code = _field("Код из письма (для смены пароля)")
    new_password = _field("Новый пароль (от 4 символов)", true)
    _button("ПОЛУЧИТЬ КОД", func(): _send("/auth/password/request", {"email":security_email.text.strip_edges()}))
    _button("СМЕНИТЬ ПАРОЛЬ", func(): _send("/auth/password/reset", {"token":security_code.text.strip_edges(), "password":new_password.text}))
    _button("НАЗАД", func(): _show_login())
    _layout()

func _show_verification() -> void:
    mode = "verification"
    _panel()
    security_email = _field("Email аккаунта")
    security_code = _field("Код подтверждения из письма")
    _button("ОТПРАВИТЬ КОД", func(): _send("/auth/verify/request", {"email":security_email.text.strip_edges()}))
    _button("ПОДТВЕРДИТЬ", func(): _send("/auth/verify/confirm", {"token":security_code.text.strip_edges()}))
    _button("НАЗАД", func(): _show_login())
    _layout()

func _show_settings() -> void:
    mode = "settings"
    _panel()
    _button("Музыка: " + ("ВКЛ" if music_enabled else "ВЫКЛ"), func():
        music_enabled = not music_enabled
        _show_settings()
    )
    _button("Уменьшить анимации: " + ("ДА" if reduce_motion else "НЕТ"), func():
        reduce_motion = not reduce_motion
        _show_settings()
    )
    _label("Горизонтальный экран · безопасные поля", 13)
    if GameSession.is_authenticated():
        _button("ВЫЙТИ ИЗ АККАУНТА", func(): _send("/auth/logout", {}))
        _button("ВЫЙТИ СО ВСЕХ УСТРОЙСТВ", func(): _send("/auth/logout-all", {}))
    _button("НАЗАД", func(): _show_home())
    _layout()

func _submit_login() -> void:
    _send("/auth/login", {"identifier":login_id.text.strip_edges(), "password":password.text})

func _submit_register() -> void:
    _send("/auth/register", {"username":username.text.strip_edges(), "email":email.text.strip_edges(), "password":password.text})

func _send(route: String, payload: Dictionary) -> void:
    if busy: return
    busy = true
    pending = route
    status_label.text = "Подключение к серверу..."
    var headers := PackedStringArray(["Content-Type: application/json"])
    if GameSession.is_authenticated():
        headers.append("Authorization: Bearer " + GameSession.access_token)
    var err := request.request(api_base + route, headers, HTTPClient.METHOD_POST, JSON.stringify(payload))
    if err != OK:
        busy = false
        status_label.text = "Ошибка сети: %d" % err

func _on_response(result: int, code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
    busy = false
    if pending == "/auth/logout":
        # Leave this device: forget the session locally whatever the network says (the server session simply expires otherwise).
        GameSession.sign_out()
        _show_home()
        return
    if result != HTTPRequest.RESULT_SUCCESS:
        # A remembered session stays on the device: the player may just be offline.
        if pending == "/auth/rotate":
            _show_home()          # rebuilds the panel: set the message afterwards
            status_label.text = "Нет связи с сервером. Проверьте интернет и нажмите «Продолжить»."
        else:
            status_label.text = "Не удалось подключиться к серверу"
        return
    var data = JSON.parse_string(body.get_string_from_utf8())
    if not data is Dictionary:
        status_label.text = "Некорректный ответ сервера"
        return
    if code == 200 and pending == "/auth/logout-all":
        GameSession.sign_out()
        _show_home()
        return
    if code == 200 and pending.begins_with("/auth/") and not data.has("token"):
        status_label.text = "Операция выполнена. Проверьте почту, если запрашивали код."
        return
    if code == 200 and data.has("token"):
        token = str(data.token)
        GameSession.sign_in(token, str(data.get("username", "")))
        _enter_world()
    else:
        if pending == "/auth/rotate" and (code == 401 or code == 403):
            GameSession.sign_out()          # expired, revoked or banned: the remembered session is useless
            _show_home()
            status_label.text = "Сессия истекла. Войдите снова."
            return
        var errors := {"invalid_username":"Проверьте имя игрока", "invalid_email":"Некорректная почта", "invalid_password":"Пароль должен содержать 4–128 символов", "account_exists":"Аккаунт уже существует", "invalid_credentials":"Неверный логин или пароль", "rate_limited":"Слишком много попыток, попробуйте позже", "email_unavailable":"Почтовый сервис пока недоступен", "invalid_or_expired_token":"Неверный или просроченный код", "unauthorized":"Необходимо войти в аккаунт"}
        status_label.text = errors.get(str(data.get("error","")), "Сервер ответил: %d" % code)

func _enter_world() -> void:
    get_tree().change_scene_to_file("res://world.tscn")
