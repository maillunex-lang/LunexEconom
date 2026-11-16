extends Control
signal authenticate(mode: String)
const Strings = preload("res://i18n/strings.gd")
const Forest = preload("res://theme/forest_glass.gd")
var card: PanelContainer
var scroll: ScrollContainer
var form: VBoxContainer
var title: Label
var username: LineEdit
var email: LineEdit
var password: LineEdit
var status: Label
var mode := "login"
var tab_login: Button
var tab_register: Button
var action: Button

func _ready() -> void:
    set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    var center := CenterContainer.new()
    center.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    add_child(center)
    scroll = ScrollContainer.new()
    scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
    scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
    center.add_child(scroll)
    var align := CenterContainer.new()
    align.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    scroll.add_child(align)
    card = PanelContainer.new()
    align.add_child(card)
    form = VBoxContainer.new()
    card.add_child(form)
    title = Label.new()
    title.text = Strings.get_text("main.title")
    title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
    title.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    title.add_theme_color_override("font_color",Forest.COLORS.accent)
    form.add_child(title)
    var tabs := HBoxContainer.new()
    form.add_child(tabs)
    var group := ButtonGroup.new()
    tab_login = _tab("auth.mode.login",group)
    tabs.add_child(tab_login)
    tab_login.pressed.connect(func(): set_mode("login"))
    tab_register = _tab("auth.mode.register",group)
    tabs.add_child(tab_register)
    tab_register.pressed.connect(func(): set_mode("register"))
    username = _field("auth.login.name")
    email = _field("auth.login.email")
    email.virtual_keyboard_type = LineEdit.KEYBOARD_TYPE_EMAIL_ADDRESS
    password = _field("auth.login.password",true)
    action = _button("auth.login.button")
    form.add_child(action)
    action.pressed.connect(func(): authenticate.emit(mode))
    status = Label.new()
    status.text = Strings.get_text("auth.login.title")
    status.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
    status.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    form.add_child(status)
    for field in [username,email,password]:
        field.focus_entered.connect(_ensure_field_visible.bind(field))
    set_mode("login")

## Separate sign-in and registration: sign-in asks only for login (name or email) and password.
func set_mode(new_mode: String) -> void:
    mode = new_mode if new_mode in ["login","register"] else "login"
    var registering := mode == "register"
    email.visible = registering
    username.placeholder_text = Strings.get_text("auth.register.name" if registering else "auth.login.name")
    action.text = Strings.get_text("auth.register.button" if registering else "auth.login.button")
    tab_login.button_pressed = not registering
    tab_register.button_pressed = registering
    if status != null:
        status.text = Strings.get_text("auth.register.title" if registering else "auth.login.title")

func _tab(key: String, group: ButtonGroup) -> Button:
    var button := Button.new()
    button.text = Strings.get_text(key)
    button.toggle_mode = true
    button.button_group = group
    button.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    return button

func _field(key: String, hidden: bool = false) -> LineEdit:
    var field := LineEdit.new()
    field.placeholder_text = Strings.get_text(key)
    field.secret = hidden
    field.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    form.add_child(field)
    return field

func _button(key: String) -> Button:
    var button := Button.new()
    button.text = Strings.get_text(key)
    button.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    return button

func resize_ui(view_size: Vector2, keyboard_height: float = 0.0) -> void:
    # Keyboard height arrives in physical px; caller converts before passing.
    scroll.custom_minimum_size = Vector2.ZERO
    var available_height := maxf(175.0,view_size.y - keyboard_height - 32.0)
    scroll.custom_minimum_size.y = minf(available_height,620.0)
    scroll.custom_minimum_size.x = minf(maxf(280.0,view_size.x * 0.62),830.0)
    card.custom_minimum_size.x = minf(maxf(280.0,view_size.x * 0.58),800.0)
    title.add_theme_font_size_override("font_size",roundi(24.0 * Forest.scale_for(view_size)))
    var margin := roundi(Forest.METRICS.padding * Forest.scale_for(view_size))
    var panel := Forest.rounded(Forest.COLORS.panel,roundi(Forest.METRICS.radius))
    panel.content_margin_left = margin
    panel.content_margin_right = margin
    panel.content_margin_top = margin
    panel.content_margin_bottom = margin
    card.add_theme_stylebox_override("panel",panel)
    Forest.apply_touch(form,view_size)
    if keyboard_height > 0.0:
        call_deferred("_scroll_focused")

func _scroll_focused() -> void:
    for field in [username,email,password]:
        if field.has_focus():
            scroll.ensure_control_visible(field)
            break

func _ensure_field_visible(_field_node: Control) -> void:
    call_deferred("_scroll_focused")
