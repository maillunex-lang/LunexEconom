extends Control
## Unified V2 update status: APK, content packs, progress, Wi-Fi setting.
const Strings = preload("res://update/strings.gd")
const UpdateManager = preload("res://update/update_manager.gd")
const ContentManager = preload("res://content/content_manager.gd")
const DARK := Color("0a201b")
const FOREST := Color("173a30")
const ACCENT := Color("b7efa5")
var manager: Node
var content: Node
var card: PanelContainer
var message: Label
var packs: Label
var version: Label
var progress: ProgressBar
var mandatory := false
var check_button: Button
var download_button: Button
var install_button: Button
var wifi_toggle: CheckBox
var close_button: Button

func _ready() -> void:
    set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    mouse_filter = Control.MOUSE_FILTER_STOP
    _make_layout()
    manager = UpdateManager.new()
    add_child(manager)
    manager.state_changed.connect(_update_state)
    manager.progress.connect(_progress)
    content = ContentManager.new()
    add_child(content)
    content.status.connect(func(text: String): packs.text = text)
    content.download_progress.connect(_progress)
    content.pack_ready.connect(func(name: String): packs.text = Strings.get_text("update.screen.resources.downloaded", {"amount": name}))
    var preferences := ConfigFile.new()
    if preferences.load("user://update_settings.cfg") == OK:
        wifi_toggle.button_pressed = bool(preferences.get_value("download", "wifi_only", false))
    version.text = Strings.get_text("update.screen.version.current", {"version": manager._version_code()})
    hide()

func _make_layout() -> void:
    var shadow := ColorRect.new()
    shadow.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    shadow.color = Color(0,0,0,0.84)
    add_child(shadow)
    var center := CenterContainer.new()
    center.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    add_child(center)
    card = PanelContainer.new()
    card.custom_minimum_size = Vector2(550,350)
    var style := StyleBoxFlat.new()
    style.bg_color = FOREST
    style.set_corner_radius_all(18)
    style.set_content_margin_all(22)
    card.add_theme_stylebox_override("panel", style)
    center.add_child(card)
    var stack := VBoxContainer.new()
    stack.add_theme_constant_override("separation", 10)
    card.add_child(stack)
    var title := Label.new()
    title.text = Strings.get_text("update.screen.title")
    title.add_theme_color_override("font_color", ACCENT)
    title.add_theme_font_size_override("font_size", 23)
    stack.add_child(title)
    version = Label.new()
    stack.add_child(version)
    message = Label.new()
    message.text = Strings.get_text("update.screen.checking")
    message.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    stack.add_child(message)
    packs = Label.new()
    packs.text = Strings.get_text("update.screen.resources.checking")
    packs.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    stack.add_child(packs)
    progress = ProgressBar.new()
    progress.max_value = 100
    progress.show_percentage = true
    progress.value = 0
    stack.add_child(progress)
    wifi_toggle = CheckBox.new()
    wifi_toggle.text = Strings.get_text("update.screen.wifi_only")
    wifi_toggle.toggled.connect(func(checked: bool):
        manager.wifi_only = checked
        content.wifi_only = checked
        var preferences := ConfigFile.new()
        preferences.set_value("download", "wifi_only", checked)
        preferences.save("user://update_settings.cfg")
    )
    stack.add_child(wifi_toggle)
    var controls := HBoxContainer.new()
    stack.add_child(controls)
    check_button = _make_button(Strings.get_text("update.screen.checking"), controls)
    check_button.pressed.connect(func():
        manager.check()
        content.refresh()
    )
    download_button = _make_button(Strings.get_text("update.screen.download"), controls)
    download_button.pressed.connect(manager_download)
    install_button = _make_button(Strings.get_text("update.screen.install"), controls)
    install_button.disabled = true
    install_button.pressed.connect(func(): manager.install())
    close_button = _make_button(Strings.get_text("update.screen.later"), controls)
    close_button.pressed.connect(_close_panel)

func _make_button(label: String, parent: HBoxContainer) -> Button:
    var btn := Button.new()
    btn.text = label
    btn.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    parent.add_child(btn)
    return btn

func manager_download() -> void:
    if manager != null:
        manager.download_apk()

func open() -> void:
    show()

func _update_state(text: String, can_install: bool, must_update: bool) -> void:
    message.text = text
    mandatory = must_update
    install_button.disabled = not can_install
    close_button.disabled = must_update
    download_button.disabled = manager.manifest.is_empty() or int(manager.manifest.get("version_code", 0)) <= manager.current_version_code
    if must_update:
        show()

func _progress(received: int, total: int) -> void:
    if total > 0:
        progress.value = (100.0 * received) / float(total)

func _close_panel() -> void:
    if not mandatory:
        hide()
