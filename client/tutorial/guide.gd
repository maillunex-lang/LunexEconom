extends PanelContainer
signal refresh_requested
const State = preload("res://tutorial/state.gd")
const Words = preload("res://enterprises/strings.gd")
const Forest = preload("res://theme/forest_glass.gd")
var progress: RefCounted
var body: VBoxContainer
var heading: Label
var hint: Label
var toggle: Button
var skip: Button
var refresh: Button
var _current_screen := ""
const VISIBLE_SCREENS := ["headquarters", "map", "enterprises", "settings", "more", "finance", "build", "supply", "store"]

func _ready() -> void:
    mouse_filter = Control.MOUSE_FILTER_STOP
    custom_minimum_size = Vector2(260, 0)
    body = VBoxContainer.new()
    add_child(body)
    heading = Label.new()
    heading.name = "TutorialProgress"
    body.add_child(heading)
    hint = Label.new()
    hint.name = "TutorialHint"
    hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    hint.custom_minimum_size.x = 260
    body.add_child(hint)
    var controls := HBoxContainer.new()
    body.add_child(controls)
    toggle = Button.new()
    toggle.text = Words.get_text("tutorial.collapse")
    toggle.custom_minimum_size.y = 48
    toggle.pressed.connect(_toggle)
    controls.add_child(toggle)
    refresh = Button.new()
    refresh.text = Words.get_text("tutorial.refresh")
    refresh.custom_minimum_size.y = 48
    refresh.pressed.connect(func(): refresh_requested.emit())
    controls.add_child(refresh)
    skip = Button.new()
    skip.text = Words.get_text("tutorial.skip")
    skip.custom_minimum_size.y = 48
    skip.pressed.connect(_skip)
    controls.add_child(skip)
    visible = false

func set_progress(value: RefCounted) -> void:
    progress = value
    redraw()

func change_screen(screen: String) -> void:
    _current_screen = screen
    redraw()

func redraw() -> void:
    visible = progress != null and not progress.account_id.is_empty() and not progress.completed and VISIBLE_SCREENS.has(_current_screen)
    if not visible:
        return
    var idx: int = progress.step
    heading.text = Words.get_text("tutorial.progress", {"step": mini(idx + 1, State.TOTAL), "total": State.TOTAL})
    var key := idx - 2
    if idx == 0:
        hint.text = Words.get_text("tutorial.start.account")
    elif idx == 1:
        hint.text = Words.get_text("tutorial.start.wallet")
    elif idx == 2:
        hint.text = Words.get_text("tutorial.start.land")
    else:
        hint.text = Words.get_text("tutorial.step.%d.title" % key) + ": " + Words.get_text("tutorial.step.%d.hint" % key)
    hint.visible = not progress.collapsed
    refresh.visible = not progress.collapsed
    skip.visible = not progress.collapsed
    skip.disabled = not progress.can_skip()
    toggle.text = Words.get_text("tutorial.expand" if progress.collapsed else "tutorial.collapse")
    custom_minimum_size.y = 56 if progress.collapsed else 150

func _toggle() -> void:
    if progress == null:
        return
    progress.collapsed = not progress.collapsed
    progress.persist()
    redraw()

func _skip() -> void:
    if progress != null and progress.can_skip():
        hide()

func refresh_size(size_now: Vector2) -> void:
    Forest.apply_touch(self, size_now)
