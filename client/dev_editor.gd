extends PanelContainer
## Operator-granted editor. The server independently verifies every command.
const ROOT := "https://rikagro.ru/lunexeconom/api/"
const BRUSH = preload("res://dev_brush.gd")
var selected := Vector2i.ZERO
var mode := "tree"
var brush_size := 1
var status: Label
var send_button: Button
var object_id_input: LineEdit

func _ready() -> void:
    name = "DeveloperEditor"
    custom_minimum_size = Vector2(330, 0)
    var column := VBoxContainer.new()
    add_child(column)
    var heading := Label.new()
    heading.text = "Редактор мира"
    column.add_child(heading)
    var modes := OptionButton.new()
    for kind in ["tree", "grass", "water", "clear", "road_add", "road_remove"]:
        modes.add_item(kind)
    modes.item_selected.connect(func(index: int) -> void: mode = modes.get_item_text(index))
    column.add_child(modes)
    var sizes := OptionButton.new()
    for n in [1, 3, 5]:
        sizes.add_item("%d × %d" % [n, n])
    sizes.item_selected.connect(func(index: int) -> void: brush_size = [1, 3, 5][index])
    column.add_child(sizes)
    object_id_input = LineEdit.new()
    object_id_input.placeholder_text = "ID здания для перемещения"
    column.add_child(object_id_input)
    var move_button := Button.new()
    move_button.text = "Переместить здание в выбранную клетку"
    move_button.pressed.connect(_move_building)
    column.add_child(move_button)
    status = Label.new()
    status.text = "Выберите клетку на карте"
    column.add_child(status)
    send_button = Button.new()
    send_button.text = "Применить"
    send_button.pressed.connect(_apply)
    column.add_child(send_button)
    var undo_button := Button.new()
    undo_button.text = "Отменить последнее"
    undo_button.pressed.connect(func() -> void: _send("dev/undo", {"request_id": _uuid()}))
    column.add_child(undo_button)
    var close_button := Button.new()
    close_button.text = "Закрыть"
    close_button.pressed.connect(hide)
    column.add_child(close_button)

func select_cell(cell: Vector2i) -> void:
    selected = cell
    if status != null:
        status.text = "Клетка %d:%d" % [cell.x, cell.y]

func _uuid() -> String:
    var bytes := Crypto.new().generate_random_bytes(16)
    bytes[6] = (bytes[6] & 15) | 64
    bytes[8] = (bytes[8] & 63) | 128
    var hex := bytes.hex_encode()
    return "%s-%s-%s-%s-%s" % [hex.substr(0,8), hex.substr(8,4), hex.substr(12,4), hex.substr(16,4), hex.substr(20,12)]

func _apply() -> void:
    var cells := BRUSH.cells(selected, brush_size)
    if mode.begins_with("road_"):
        _send("dev/roads", {"request_id": _uuid(), "operation": mode.trim_prefix("road_"), "cells": cells})
    else:
        _send("dev/terrain", {"request_id": _uuid(), "kind": mode, "cells": cells})

func _move_building() -> void:
    var oid := object_id_input.text.strip_edges()
    if oid.is_empty():
        status.text = "Укажите ID здания"
        return
    _send("dev/move", {"request_id": _uuid(), "object_id": oid, "x": selected.x, "y": selected.y})

func _send(endpoint: String, payload: Dictionary) -> void:
    if not GameSession.is_authenticated(): return
    send_button.disabled = true
    var request := HTTPRequest.new()
    add_child(request)
    request.request_completed.connect(func(result: int, code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
        send_button.disabled = false
        status.text = "Ответ %d: %s" % [code, body.get_string_from_utf8().substr(0, 150)] if result == HTTPRequest.RESULT_SUCCESS else "Ошибка сети"
        request.queue_free()
    )
    var headers := PackedStringArray(["Authorization: Bearer " + GameSession.access_token, "Content-Type: application/json"])
    if request.request(ROOT + endpoint, headers, HTTPClient.METHOD_POST, JSON.stringify(payload)) != OK:
        send_button.disabled = false
        request.queue_free()