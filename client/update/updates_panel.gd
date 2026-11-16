extends Control
## Unified V2 update status: APK, content packs, progress, Wi-Fi setting.
const Strings = preload("res://update/strings.gd")
const UpdateManager = preload("res://update/update_manager.gd")
const ContentManager = preload("res://content/content_manager.gd")
const Forest = preload("res://theme/forest_glass.gd")
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
var notes: Label
var size_label: Label
var progress_label: Label
var scroll: ScrollContainer

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
    _refresh_manifest_details()
    hide()

func _make_layout() -> void:
    var background := ColorRect.new()
    background.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    background.color = DARK
    background.mouse_filter = Control.MOUSE_FILTER_IGNORE
    add_child(background)
    var margin := MarginContainer.new()
    margin.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    for edge in ["left","right","top","bottom"]:
        margin.add_theme_constant_override("margin_"+edge,20)
    add_child(margin)
    scroll = ScrollContainer.new()
    scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
    scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
    margin.add_child(scroll)
    var center := CenterContainer.new()
    center.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    scroll.add_child(center)
    card = PanelContainer.new()
    card.custom_minimum_size.x = 600
    var style := Forest.rounded(FOREST,18)
    style.set_content_margin_all(24)
    card.add_theme_stylebox_override("panel",style)
    center.add_child(card)
    var stack := VBoxContainer.new()
    stack.add_theme_constant_override("separation",12)
    card.add_child(stack)
    var title := Label.new()
    title.text = Strings.get_text("update.screen.title")
    title.add_theme_color_override("font_color",ACCENT)
    title.add_theme_font_size_override("font_size",24)
    stack.add_child(title)
    version = Label.new()
    version.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    stack.add_child(version)
    message = Label.new()
    message.text = Strings.get_text("update.screen.checking")
    message.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    stack.add_child(message)
    var notes_title := Label.new()
    notes_title.text = Strings.get_text("update.screen.changelog")
    notes_title.add_theme_color_override("font_color",ACCENT)
    stack.add_child(notes_title)
    notes = Label.new()
    notes.text = Strings.get_text("update.screen.changelog.empty")
    notes.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    stack.add_child(notes)
    size_label = Label.new()
    size_label.text = Strings.get_text("update.screen.size",{"size":"—"})
    stack.add_child(size_label)
    packs = Label.new()
    packs.text = Strings.get_text("update.screen.resources.checking")
    packs.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    stack.add_child(packs)
    progress = ProgressBar.new()
    progress.max_value = 100
    progress.show_percentage = true
    progress.value = 0
    progress.custom_minimum_size.y = 24
    stack.add_child(progress)
    progress_label = Label.new()
    progress_label.text = Strings.get_text("update.screen.progress.preparing")
    progress_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    stack.add_child(progress_label)
    wifi_toggle = CheckBox.new()
    wifi_toggle.text = Strings.get_text("update.screen.wifi_only")
    wifi_toggle.toggled.connect(func(checked: bool):
        manager.wifi_only = checked
        content.wifi_only = checked
        var preferences := ConfigFile.new()
        preferences.set_value("download","wifi_only",checked)
        preferences.save("user://update_settings.cfg")
    )
    stack.add_child(wifi_toggle)
    check_button = _make_button(Strings.get_text("update.screen.check"),stack)
    check_button.pressed.connect(func():
        manager.check()
        content.refresh()
    )
    download_button = _make_button(Strings.get_text("update.screen.download"),stack)
    download_button.pressed.connect(manager_download)
    install_button = _make_button(Strings.get_text("update.screen.install"),stack)
    install_button.disabled = true
    install_button.pressed.connect(func(): manager.install())
    close_button = _make_button(Strings.get_text("update.screen.later"),stack)
    close_button.pressed.connect(_close_panel)
    _select_primary()

func _make_button(label: String, parent: VBoxContainer) -> Button:
    var btn := Button.new()
    btn.text = label
    btn.custom_minimum_size.y = 48
    btn.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    parent.add_child(btn)
    return btn

func _select_primary() -> void:
    # Exactly one primary action is visible; existing state callbacks stay intact.
    var can_install := not install_button.disabled
    var can_download := not download_button.disabled
    install_button.visible = can_install
    download_button.visible = not can_install and can_download
    check_button.visible = not can_install and not can_download

func resize_ui(view_size: Vector2) -> void:
    # Card is capped at 720dp; the backdrop fills the complete 21:9 canvas.
    var target := minf(720.0,maxf(280.0,view_size.x-80.0))
    card.custom_minimum_size.x = target
    Forest.apply_touch(self,view_size)
    _select_primary()

func _human_error(raw: String) -> String:
    if raw.contains("Нет подписанного") or raw.contains("не удалось проверить") or raw.contains("Не удалось проверить"):
        return Strings.get_text("update.screen.error.manifest")
    if raw.contains("Подпись манифеста") or raw.contains("проверку безопасности"):
        return Strings.get_text("update.screen.error.signature")
    return raw

func _refresh_manifest_details() -> void:
    if manager == null:
        return
    var current := str(manager._version_code())
    var manifest: Dictionary = manager.manifest
    if manifest.is_empty():
        version.text = Strings.get_text("update.screen.version.current",{"version":current})
        notes.text = Strings.get_text("update.screen.changelog.empty")
        size_label.text = Strings.get_text("update.screen.size",{"size":"—"})
        return
    var newest := str(manifest.get("version_name", ""))
    version.text = Strings.get_text("update.screen.versions",{"current":current,"new":newest})
    var note_text := str(manifest.get("notes","")).strip_edges()
    notes.text = note_text if not note_text.is_empty() else Strings.get_text("update.screen.changelog.empty")
    var bytes := int(manifest.get("size",0))
    size_label.text = Strings.get_text("update.screen.size",{"size":"%.1f МБ" % (float(bytes)/1048576.0) if bytes>0 else "—"})

func manager_download() -> void:
    if manager != null:
        manager.download_apk()

func open() -> void:
    _refresh_manifest_details()
    resize_ui(get_viewport_rect().size)
    show()

func _update_state(text: String, can_install: bool, must_update: bool) -> void:
    message.text = _human_error(text)
    mandatory = must_update
    _refresh_manifest_details()
    install_button.disabled = not can_install
    close_button.disabled = must_update
    download_button.disabled = manager.manifest.is_empty() or int(manager.manifest.get("version_code", 0)) <= manager.current_version_code
    _select_primary()
    if must_update:
        show()

func _progress(received: int, total: int) -> void:
    if total > 0:
        progress.value = (100.0 * received) / float(total)
        progress_label.text = Strings.get_text("update.screen.progress.full",{"downloaded":"%.1f МБ" % (float(received)/1048576.0),"total":"%.1f МБ" % (float(total)/1048576.0),"percent":roundi(progress.value)})

func _close_panel() -> void:
    if not mandatory:
        hide()
