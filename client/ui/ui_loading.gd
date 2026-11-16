extends VBoxContainer
signal retry_requested
const Words = preload("res://i18n/strings.gd")
var label: Label
var retry: Button
func _ready() -> void:
    label = Label.new()
    label.text = Words.get_text("ui.loading")
    label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    add_child(label)
    retry = Button.new()
    retry.text = Words.get_text("ui.retry")
    retry.custom_minimum_size = Vector2(48,48)
    retry.pressed.connect(func(): retry_requested.emit())
    add_child(retry)
    retry.hide()
func set_failed() -> void:
    label.text = Words.get_text("ui.load.failed")
    retry.show()
func set_busy() -> void:
    label.text = Words.get_text("ui.loading")
    retry.hide()
