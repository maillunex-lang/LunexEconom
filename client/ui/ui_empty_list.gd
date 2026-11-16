extends VBoxContainer
signal action_requested
const Words = preload("res://i18n/strings.gd")
const ActionButton = preload("res://ui/ui_button.gd")
var heading: Label
var explanation: Label
var action: Button
func _ready() -> void:
    var symbol := Label.new()
    symbol.text = "◇"
    symbol.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
    add_child(symbol)
    heading = Label.new()
    heading.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
    heading.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    add_child(heading)
    explanation = Label.new()
    explanation.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
    explanation.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    add_child(explanation)
    action = ActionButton.new()
    action.variant = "secondary"
    action.pressed.connect(func(): action_requested.emit())
    add_child(action)
    configure("ui.empty.title","ui.empty.description","ui.empty.action")
func configure(title_key: String, body_key: String, action_key: String) -> void:
    heading.text = Words.get_text(title_key)
    explanation.text = Words.get_text(body_key)
    action.text = Words.get_text(action_key)
