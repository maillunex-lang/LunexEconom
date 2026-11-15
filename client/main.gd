extends Control
## Forest Glass V2: login + empty headquarters; no real economy content yet.

const BACKGROUND := Color("0a201b")
const PANEL := Color("173a30")
const ACCENT := Color("b7efa5")
const TEXT := Color("eef5e8")
const MUTED := Color("a1b9ad")
const FONT := 27

var base_url := "https://rikagro.ru/lunexeconom/api"
var shell: MarginContainer
var form: VBoxContainer
var headquarters: VBoxContainer
var login_username: LineEdit
var login_password: LineEdit
var status_label: Label
var hq_status: Label
var token := ""
var _http: HTTPRequest
var _health_http: HTTPRequest

func _ready() -> void:
    get_viewport().size_changed.connect(_on_viewport_resized)
    _build_shell()
    _build_login()
    _build_headquarters()
    headquarters.hide()
    _on_viewport_resized()

func _on_viewport_resized() -> void:
    if shell == null:
        return
    var viewport_size: Vector2 = get_viewport_rect().size
    var safe_rect: Rect2i = DisplayServer.get_display_safe_area()
    var top := 20
    var left := 24
    var right := 24
    var bottom := 20
    if OS.has_feature("mobile") and safe_rect.size.x > 0:
        var sx: float = viewport_size.x / maxf(1.0, float(DisplayServer.screen_get_size().x))
        var sy: float = viewport_size.y / maxf(1.0, float(DisplayServer.screen_get_size().y))
        left = maxi(24, roundi(safe_rect.position.x * sx) + 12)
        top = maxi(20, roundi(safe_rect.position.y * sy) + 12)
        right = maxi(24, roundi((DisplayServer.screen_get_size().x - safe_rect.end.x) * sx) + 12)
        bottom = maxi(20, roundi((DisplayServer.screen_get_size().y - safe_rect.end.y) * sy) + 12)
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
    card.custom_minimum_size = Vector2(500, 390)
    card.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
    var style := StyleBoxFlat.new()
    style.bg_color = PANEL
    style.border_color = Color("386c57")
    style.set_border_width_all(1)
    style.set_corner_radius_all(24)
    style.content_margin_left = 42
    style.content_margin_right = 42
    style.content_margin_top = 28
    style.content_margin_bottom = 28
    card.add_theme_stylebox_override("panel", style)
    center.add_child(card)
    var stack := VBoxContainer.new()
    stack.add_theme_constant_override("separation",18)
    card.add_child(stack)
    var title := Label.new()
    title.text = "БАШКИРИЯ: МЁД И НЕФТЬ"
    title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
    title.add_theme_font_size_override("font_size",24)
    title.add_theme_color_override("font_color",ACCENT)
    stack.add_child(title)
    var subtitle := Label.new()
    subtitle.text = "Экономический тренажёр · Версия 2"
    subtitle.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
    subtitle.add_theme_font_size_override("font_size",14)
    subtitle.add_theme_color_override("font_color",MUTED)
    stack.add_child(subtitle)
    form = VBoxContainer.new()
    form.add_theme_constant_override("separation",12)
    stack.add_child(form)
    headquarters = VBoxContainer.new()
    headquarters.add_theme_constant_override("separation",20)
    stack.add_child(headquarters)

func _build_login() -> void:
    login_username = LineEdit.new()
    login_username.placeholder_text = "Логин"
    login_username.custom_minimum_size.y = 46
    form.add_child(login_username)
    login_password = LineEdit.new()
    login_password.placeholder_text = "Пароль (не менее 4 символов)"
    login_password.secret = true
    login_password.custom_minimum_size.y = 46
    form.add_child(login_password)
    var buttons := HBoxContainer.new()
    buttons.add_theme_constant_override("separation",12)
    form.add_child(buttons)
    var login_button := _button("Войти")
    var register_button := _button("Создать аккаунт")
    buttons.add_child(login_button)
    buttons.add_child(register_button)
    login_button.pressed.connect(func(): _send_auth("login"))
    register_button.pressed.connect(func(): _send_auth("register"))
    status_label = Label.new()
    status_label.text = "Войдите или зарегистрируйтесь"
    status_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
    status_label.add_theme_color_override("font_color",MUTED)
    form.add_child(status_label)

func _button(text: String) -> Button:
    var btn := Button.new()
    btn.text = text
    btn.custom_minimum_size = Vector2(150,46)
    btn.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    btn.add_theme_font_size_override("font_size",15)
    return btn

func _build_headquarters() -> void:
    var title := Label.new()
    title.text = "Штаб-квартира"
    title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
    title.add_theme_font_size_override("font_size",28)
    title.add_theme_color_override("font_color",TEXT)
    headquarters.add_child(title)
    var empty := Label.new()
    empty.text = "Предприятий пока нет. Экономика появится в следующей фазе."
    empty.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    empty.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
    empty.add_theme_color_override("font_color",MUTED)
    headquarters.add_child(empty)
    hq_status = Label.new()
    hq_status.text = "Состояние сервера: проверка…"
    hq_status.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
    headquarters.add_child(hq_status)
    var btn := _button("Проверить сервер")
    btn.pressed.connect(_check_health)
    headquarters.add_child(btn)
    var logout := _button("Выйти")
    logout.pressed.connect(func():
        token = ""
        headquarters.hide()
        form.show()
    )
    headquarters.add_child(logout)

func _send_auth(mode: String) -> void:
    if _http != null:
        return
    var username := login_username.text.strip_edges()
    var password := login_password.text
    if username.length() < 3 or password.length() < 4:
        status_label.text = "Проверьте логин и пароль"
        return
    _http = HTTPRequest.new()
    add_child(_http)
    _http.request_completed.connect(func(_result: int, code: int, _headers: PackedStringArray, body: PackedByteArray):
        var response = JSON.parse_string(body.get_string_from_utf8())
        _http.queue_free()
        _http = null
        if code != 200 and code != 201:
            status_label.text = "Ошибка: " + str(response.get("error", code) if response is Dictionary else code)
            return
        if mode == "register":
            status_label.text = "Аккаунт создан. Теперь войдите."
            return
        if response is Dictionary and response.has("token"):
            token = response["token"]
            form.hide()
            headquarters.show()
            _check_health()
    )
    var err := _http.request(base_url + "/auth/" + mode, PackedStringArray(["Content-Type: application/json"]), HTTPClient.METHOD_POST, JSON.stringify({"username":username,"password":password}))
    if err != OK:
        status_label.text = "Нет подключения к серверу"
        _http.queue_free()
        _http = null

func _check_health() -> void:
    if _health_http != null:
        return
    _health_http = HTTPRequest.new()
    add_child(_health_http)
    _health_http.request_completed.connect(func(_result: int, code: int, _headers: PackedStringArray, body: PackedByteArray):
        var response = JSON.parse_string(body.get_string_from_utf8())
        var ok: bool = code == 200 and response is Dictionary and response.get("ok",false) == true
        hq_status.text = "Сервер V2: " + ("на связи" if ok else "недоступен")
        _health_http.queue_free()
        _health_http = null
    )
    if _health_http.request(base_url + "/health") != OK:
        hq_status.text = "Сервер V2: нет соединения"
        _health_http.queue_free()
        _health_http = null
