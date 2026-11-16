extends Control
signal refresh_requested
signal navigate(screen: String)
signal logout_requested
const Strings = preload("res://i18n/strings.gd")
const Forest = preload("res://theme/forest_glass.gd")
var wallet: Label
var calendar: Label
var status: Label
var tabs: HBoxContainer

func _ready() -> void:
    set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    var stack := VBoxContainer.new()
    stack.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    add_child(stack)
    var header := PanelContainer.new()
    header.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    stack.add_child(header)
    var heading := HBoxContainer.new()
    header.add_child(heading)
    var title := Label.new()
    title.text = Strings.get_text("player.company")
    title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    heading.add_child(title)
    wallet = Label.new()
    wallet.text = Strings.get_text("finance.balance") + ": " + Strings.get_text("loading")
    heading.add_child(wallet)
    calendar = Label.new()
    calendar.text = Strings.get_text("time.month") + ": " + Strings.get_text("loading")
    heading.add_child(calendar)
    var content := PanelContainer.new()
    content.size_flags_vertical = Control.SIZE_EXPAND_FILL
    stack.add_child(content)
    var inner := VBoxContainer.new()
    content.add_child(inner)
    var placeholder := Label.new()
    placeholder.text = Strings.get_text("player.enterprises") + " · " + Strings.get_text("empty.list")
    placeholder.size_flags_vertical = Control.SIZE_EXPAND_FILL
    inner.add_child(placeholder)
    status = Label.new()
    status.text = Strings.get_text("loading")
    inner.add_child(status)
    var actions := HBoxContainer.new()
    inner.add_child(actions)
    var refresh := _button("update.screen.retry",actions)
    refresh.pressed.connect(func(): refresh_requested.emit())
    var updates := _button("client.update",actions)
    updates.pressed.connect(func(): navigate.emit("updates"))
    var settings := _button("main.menu.settings",actions)
    settings.pressed.connect(func(): navigate.emit("settings"))
    var logout := _button("auth.logout",actions)
    logout.pressed.connect(func(): logout_requested.emit())

func _button(key: String, parent: HBoxContainer) -> Button:
    var control := Button.new()
    control.text = Strings.get_text(key)
    control.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    parent.add_child(control)
    return control

func resize_ui(view_size: Vector2) -> void:
    Forest.apply_touch(self,view_size)