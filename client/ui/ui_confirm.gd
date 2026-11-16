extends ConfirmationDialog
## Modal confirmation only; callers decide when an action is irreversible.
const Words = preload("res://i18n/strings.gd")
func _ready() -> void:
    exclusive = true
    ok_button_text = Words.get_text("ui.confirm.yes")
    cancel_button_text = Words.get_text("ui.confirm.no")
func ask(title_key: String, body_key: String) -> void:
    title = Words.get_text(title_key)
    dialog_text = Words.get_text(body_key)
    popup_centered()
