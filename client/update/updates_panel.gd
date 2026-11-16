extends Control
## Unified V2 update status: APK, content packs, progress, Wi-Fi setting.
const Strings = preload("res://update/strings.gd")
const UpdateManager = preload("res://update/update_manager.gd")
const ContentManager = preload("res://content/content_manager.gd")
const DARK := Color("0a201b")
const FOREST := Color("173a30")
const ACCENT := Color("b7efa5")
const UI = preload("res://ui/components.gd")
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
var progress_caption: Label
var controls: HBoxContainer

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
    _sync_manifest_info()
    # Visibility is owned by the screen router, not by the panel itself.

func _make_layout() -> void:
    var background := ColorRect.new()
    background.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    background.color = DARK
    background.mouse_filter = Control.MOUSE_FILTER_IGNORE
    add_child(background)
    var center := CenterContainer.new()
    center.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    add_child(center)
    var scroller := ScrollContainer.new()
    scroller.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    scroller.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
    center.add_child(scroller)
    var align := CenterContainer.new()
    align.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    align.size_flags_vertical = Control.SIZE_EXPAND_FILL
    scroller.add_child(align)
    card = UI.card()
    card.custom_minimum_size.x = 0
    var style := StyleBoxFlat.new()
    style.bg_color = FOREST
    style.set_corner_radius_all(18)
    style.set_content_margin_all(24)
    card.add_theme_stylebox_override("panel",style)
    align.add_child(card)
    card.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
    var stack := VBoxContainer.new()
    stack.add_theme_constant_override("separation", 10)
    stack.custom_minimum_size.x = 400
    card.add_child(stack)
    var title := Label.new()
    title.text = Strings.get_text("update.screen.title")
    title.add_theme_color_override("font_color", ACCENT)
    title.add_theme_font_size_override("font_size", 23)
    stack.add_child(title)
    version = Label.new()
    version.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    stack.add_child(version)
    size_label = Label.new()
    size_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    stack.add_child(size_label)
    var changelog_title := Label.new()
    changelog_title.text = Strings.get_text("update.screen.changelog")
    stack.add_child(changelog_title)
    notes = Label.new()
    notes.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    notes.text = Strings.get_text("update.screen.changelog.empty")
    stack.add_child(notes)
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
    progress_caption = Label.new()
    progress_caption.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    stack.add_child(progress_caption)
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
    controls = HBoxContainer.new()
    stack.add_child(controls)
    check_button = _make_button(Strings.get_text("update.screen.retry"), controls)
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
    _choose_action()

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
    resize_panel(get_viewport_rect().size)

func resize_panel(view_size: Vector2) -> void:
    card.custom_minimum_size.x = minf(720.0,maxf(360.0,view_size.x * 0.58))
    UI.Forest.apply_touch(self,view_size)

func _update_state(text: String, can_install: bool, must_update: bool) -> void:
    message.text = text
    _sync_manifest_info()
    mandatory = must_update
    install_button.disabled = not can_install
    close_button.disabled = must_update
    download_button.disabled = manager.manifest.is_empty() or int(manager.manifest.get("version_code", 0)) <= manager.current_version_code
    _choose_action()
    if must_update:
        show()

func _progress(received: int, total: int) -> void:
    if total > 0:
        progress.value = (100.0 * received) / float(total)
        progress_caption.text = Strings.get_text("update.screen.download_progress", {"downloaded": _bytes(received), "total": _bytes(total)})

func _close_panel() -> void:
    if not mandatory:
        hide()

func _bytes(amount: int) -> String:
    if amount >= 1048576:
        return "%.1f МБ" % (float(amount) / 1048576.0)
    return "%d КБ" % ceili(float(amount) / 1024.0)

func _sync_manifest_info() -> void:
    if manager == null:
        return
    var current := str(manager._version_code())
    var manifest_data: Dictionary = manager.manifest
    if manifest_data.is_empty() or int(manifest_data.get("version_code",0)) <= manager.current_version_code:
        version.text = Strings.get_text("update.screen.version.current", {"version": current})
    else:
        version.text = Strings.get_text("update.screen.version.pair", {"current":current,"new":str(manifest_data.get("version_name",""))})
    size_label.text = Strings.get_text("update.screen.size",{"size":_bytes(int(manifest_data.get("size",0)))}) if int(manifest_data.get("size",0)) > 0 else ""
    var changes: Variant = manifest_data.get("notes",manifest_data.get("release_notes",manifest_data.get("changelog","")))
    if changes is Array:
        notes.text = "
".join(PackedStringArray(changes))
    elif changes is String and not changes.is_empty():
        notes.text = changes
    else:
        notes.text = Strings.get_text("update.screen.changelog.empty")

func _choose_action() -> void:
    if check_button == null or manager == null:
        return
    var available: bool = not manager.manifest.is_empty() and int(manager.manifest.get("version_code",0)) > manager.current_version_code
    check_button.visible = not available
    download_button.visible = available and install_button.disabled
    install_button.visible = available and not install_button.disabled
