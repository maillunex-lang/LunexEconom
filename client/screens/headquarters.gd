extends Control
signal refresh_requested
signal navigate(screen: String)
signal logout_requested
const Strings = preload("res://i18n/strings.gd")
const Forest = preload("res://theme/forest_glass.gd")
const Components = preload("res://ui/components.gd")
const Columns = preload("res://ui/two_columns.gd")
var wallet: Label
var calendar: Label
var status: Label
var tabs: HBoxContainer
var _layout: Control
var _hint: Label
var _metric: Label

func _ready() -> void:
    set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    _layout = Columns.new()
    _layout.name = "HeadquartersColumns"
    add_child(_layout)
    _layout.list_area.add_child(_headline())
    _layout.list_area.add_child(_balance_card())
    _layout.list_area.add_child(_actions())
    var help := Components.card()
    _layout.detail_area.add_child(help)
    var stack := VBoxContainer.new()
    help.add_child(stack)
    var heading := Label.new()
    heading.text = Strings.get_text("ui2.hq.next")
    heading.add_theme_font_size_override("font_size",22)
    stack.add_child(heading)
    _hint = Label.new()
    _hint.text = Strings.get_text("ui2.hq.hint")
    _hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    stack.add_child(_hint)
    status = Label.new()
    status.text = Strings.get_text("loading")
    status.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    stack.add_child(status)
    _layout.back_button.text = Strings.get_text("ui2.hq.back")
    _layout.refresh_size(get_viewport_rect().size)

func _headline() -> Control:
    var card := Components.card()
    card.name = "CompanyHeading"
    var box := VBoxContainer.new()
    card.add_child(box)
    var title := Label.new()
    title.text = Strings.get_text("player.company")
    title.add_theme_font_size_override("font_size",26)
    box.add_child(title)
    var subtitle := Label.new()
    subtitle.text = Strings.get_text("ui2.hq.intro")
    subtitle.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    box.add_child(subtitle)
    return card

func _balance_card() -> Control:
    var card := Components.card()
    card.name = "BalanceCard"
    var box := VBoxContainer.new()
    card.add_child(box)
    wallet = Label.new()
    wallet.text = Strings.get_text("finance.balance") + ": " + Strings.get_text("loading")
    wallet.add_theme_font_size_override("font_size",26)
    wallet.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    box.add_child(wallet)
    calendar = Label.new()
    calendar.text = Strings.get_text("time.month") + ": " + Strings.get_text("loading")
    calendar.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    box.add_child(calendar)
    _metric = Label.new()
    _metric.text = Strings.get_text("ui2.hq.metrics.empty")
    _metric.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    box.add_child(_metric)
    return card

func _actions() -> Control:
    var card := Components.card()
    card.name = "HeadquartersActions"
    var buttons := GridContainer.new()
    buttons.columns = 2
    card.add_child(buttons)
    for key in [["ui2.hq.map","map"],["nav.enterprises","enterprises"],["update.screen.retry","refresh"],["main.menu.settings","settings"],["client.update","updates"],["auth.logout","logout"]]:
        var button := Components.button(str(key[0]),"secondary")
        button.name = str(key[1]).capitalize()
        button.custom_minimum_size.y = 52
        button.pressed.connect(_action.bind(str(key[1])))
        buttons.add_child(button)
    return card

func _action(target: String) -> void:
    match target:
        "refresh": refresh_requested.emit()
        "logout": logout_requested.emit()
        _: navigate.emit(target)

func resize_ui(view_size: Vector2) -> void:
    Forest.apply_touch(self,view_size)
    if _layout != null:
        _layout.refresh_size(view_size)
        if _layout.list_area.get_parent() != null:
            _layout.list_area.custom_minimum_size.x = 0
        if not _layout._wide:
            _layout.list_area.visible = true
            _layout.detail_area.visible = true
            _layout.back_button.hide()
