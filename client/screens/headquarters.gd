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
var _company: Label
var _metrics: GridContainer
var _metrics_by_key: Dictionary = {}

func _ready() -> void:
    set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    _layout = Columns.new()
    _layout.name = "HeadquartersColumns"
    add_child(_layout)
    _layout.list_area.add_child(_headline())
    _layout.list_area.add_child(_balance_card())
    _layout.list_area.add_child(_actions())
    _layout.list_area.size_flags_horizontal = Control.SIZE_EXPAND_FILL
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
    _company = Label.new()
    _company.text = Strings.get_text("player.company")
    _company.add_theme_font_size_override("font_size",26)
    _company.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    box.add_child(_company)
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
    _metrics = GridContainer.new()
    _metrics.columns = 2
    box.add_child(_metrics)
    for item in [["enterprises","ui2.hq.enterprises"],["parcels","ui2.hq.parcels"],["revenue","ui2.hq.revenue"]]:
        var card_metric := Components.card()
        _metrics.add_child(card_metric)
        var metric_label := Label.new()
        metric_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
        metric_label.text = Strings.get_text(str(item[1])) + ": " + Strings.get_text("ui2.hq.no.data")
        card_metric.add_child(metric_label)
        _metrics_by_key[str(item[0])] = metric_label
    return card

func set_company(value: String) -> void:
    if _company != null and not value.strip_edges().is_empty():
        _company.text = value.strip_edges()

func set_tutorial_hint(key: String) -> void:
    if _hint != null:
        _hint.text = Strings.get_text(key)

func set_counts(values: Dictionary) -> void:
    for key in _metrics_by_key:
        var metric_label: Label = _metrics_by_key[key]
        var prefix := "ui2.hq." + str(key)
        metric_label.text = Strings.get_text(prefix) + ": " + (str(values[key]) if values.has(key) else Strings.get_text("ui2.hq.no.data"))
    _metric.visible = values.is_empty()

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
