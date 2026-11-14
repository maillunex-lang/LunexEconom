extends Node
## Contract board. The server owns every number; this node only displays and sends commands.
## Buttons live on a panel that stays hidden until opened, so the touch router (is_visible_in_tree) cannot hit them early.

var host: Node
var panel: PanelContainer
var body: Label
var actions: VBoxContainer
var pending := false
var board: Dictionary = {}
var product := "honey"
var qty := 20
var term_months := 6
var price_choice := "ref"   # min / ref / max
var penalty_choice := "quarter"

func setup(screen: Node) -> void:
    host = screen
    var row := HBoxContainer.new()
    row.name = "ContractShortcut"
    row.add_child(host._ui_button("Контракты", open_panel, 220))
    var parent: Node = host.section_actions.get_parent()
    parent.add_child(row)
    parent.move_child(row, host.section_actions.get_index() + 1)
    host.contract_shortcut = row
    row.hide()
    panel = PanelContainer.new()
    panel.name = "ContractsPanel"
    panel.add_theme_stylebox_override("panel", host._style())
    panel.visible = false
    host.get_node("UIOverlay").add_child(panel)
    var box := VBoxContainer.new()
    panel.add_child(box)
    var header := HBoxContainer.new()
    box.add_child(header)
    var title := Label.new()
    title.text = "Контракты"
    title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    title.add_theme_font_size_override("font_size", 22)
    header.add_child(title)
    header.add_child(host._ui_button("Закрыть", hide_panel, 130))
    body = Label.new()
    body.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    body.custom_minimum_size = Vector2(460, 70)
    body.add_theme_font_size_override("font_size", 16)
    box.add_child(body)
    actions = VBoxContainer.new()
    box.add_child(actions)
    host.contracts_panel = panel

func hide_panel() -> void:
    panel.hide()
    if host.has_method("_open_section"):
        host._open_section("Экономика")

func open_panel() -> void:
    host.section_panel.hide()
    if host.contract_shortcut != null:
        host.contract_shortcut.hide()
    panel.show()
    _place()
    refresh()

func _place() -> void:
    var size: Vector2 = (host as CanvasItem).get_viewport_rect().size
    panel.size = Vector2(minf(540.0, size.x - 36.0), 460.0)
    var nav: float = host.build_toolbar.position.y
    panel.position = Vector2((size.x - panel.size.x) * 0.5, maxf(48.0, nav - panel.size.y - 12.0))

func refresh() -> void:
    if pending or not GameSession.is_authenticated():
        if not GameSession.is_authenticated():
            host.info.text = "Сначала войдите в аккаунт"
        return
    pending = true
    _request(HTTPClient.METHOD_GET, "contracts", {}, func(code: int, data: Dictionary) -> void:
        pending = false
        if code != 200:
            host.info.text = "Не удалось открыть доску контрактов"
            return
        board = data
        _render()
    )

func _product() -> Dictionary:
    for item in board.get("products", []):
        if item is Dictionary and str(item.get("id", "")) == product:
            return item
    return {"id": product, "name": product, "reference_price": 200, "min_price": 100, "max_price": 400}

func _chosen_price() -> int:
    var item := _product()
    var ref := int(item.get("reference_price", 0))
    var lo := int(item.get("min_price", ref))
    var hi := int(item.get("max_price", ref))
    if price_choice == "min":
        return lo
    if price_choice == "max":
        return hi
    return ref

func _chosen_penalty(unit: int) -> int:
    if penalty_choice == "none":
        return 0
    if penalty_choice == "full":
        return unit
    return int(unit / 4.0)

func _render() -> void:
    var item := _product()
    var unit := _chosen_price()
    var lines: PackedStringArray = []
    lines.append("Поставка мимо рынка. Цена %s–%s ₽ за %s, сейчас %s ₽." % [host._fmt_money(int(item.get("min_price", 0))), host._fmt_money(int(item.get("max_price", 0))), str(item.get("name", product)), host._fmt_money(unit)])
    var debts: Dictionary = board.get("debts", {})
    if int(debts.get("owed", 0)) > 0 or int(debts.get("receivable", 0)) > 0:
        lines.append("Долги по контрактам: вы должны %s, вам должны %s." % [host._fmt_money(int(debts.get("owed", 0))), host._fmt_money(int(debts.get("receivable", 0)))])
    var shown := 0
    for deal in board.get("mine", []):
        if deal is Dictionary and shown < 4:
            var last: Dictionary = deal.get("last", {}) if deal.get("last", null) is Dictionary else {}
            var tail := ""
            if not last.is_empty():
                tail = " · последний месяц: %d/%d, оплачено %s" % [int(last.get("delivered", 0)), int(deal.get("qty", 0)), host._fmt_money(int(last.get("paid", 0)))]
            lines.append("%s · %s %d шт. × %s · %s%s" % ["Продаёте" if str(deal.get("role", "")) == "supplier" else "Покупаете", str(deal.get("name", "")), int(deal.get("qty", 0)), host._fmt_money(int(deal.get("price", 0))), _status_name(str(deal.get("status", ""))), tail])
            shown += 1
    if shown == 0:
        lines.append("Активных контрактов пока нет.")
    body.text = "\n".join(lines)
    for child in actions.get_children():
        actions.remove_child(child)
        child.free()
    var products := HBoxContainer.new()
    actions.add_child(products)
    for entry in [["honey", "Мёд"], ["oil", "Нефть"], ["goods", "Товары"]]:
        var pid := str(entry[0])
        products.add_child(_pick(str(entry[1]), pid == product, _set_product.bind(pid)))
    var qty_row := HBoxContainer.new()
    actions.add_child(qty_row)
    for amount in [20, 50, 100]:
        qty_row.add_child(_pick("%d шт." % amount, qty == amount, _set_qty.bind(amount)))
    var price_row := HBoxContainer.new()
    actions.add_child(price_row)
    price_row.add_child(_pick("Цена мин", price_choice == "min", _set_price.bind("min")))
    price_row.add_child(_pick("База", price_choice == "ref", _set_price.bind("ref")))
    price_row.add_child(_pick("Макс", price_choice == "max", _set_price.bind("max")))
    var term_row := HBoxContainer.new()
    actions.add_child(term_row)
    for months in [3, 6, 12]:
        term_row.add_child(_pick("%d мес." % months, term_months == months, _set_term.bind(months)))
    var pen_row := HBoxContainer.new()
    actions.add_child(pen_row)
    pen_row.add_child(_pick("Без штрафа", penalty_choice == "none", _set_penalty.bind("none")))
    pen_row.add_child(_pick("Штраф 25%", penalty_choice == "quarter", _set_penalty.bind("quarter")))
    pen_row.add_child(_pick("Штраф 100%", penalty_choice == "full", _set_penalty.bind("full")))
    actions.add_child(host._ui_button("Выставить: %d × %s" % [qty, host._fmt_money(unit)], _publish, 420))
    var me := GameSession.username
    var listed := 0
    for offer in board.get("offers", []):
        if not (offer is Dictionary) or listed >= 6:
            continue
        listed += 1
        var id := str(offer.get("id", ""))
        var mine := str(offer.get("supplier", "")) == me
        var label := "%s %d×%s · %d мес. · %s" % [str(offer.get("name", "")), int(offer.get("qty", 0)), host._fmt_money(int(offer.get("price", 0))), int(offer.get("term_months", 0)), "ваше" if mine else str(offer.get("supplier", ""))]
        if mine:
            actions.add_child(_command(label + " · снять", "contracts/cancel", {"offer_id": id}, "Предложение снято"))
        else:
            actions.add_child(_command("Принять: " + label, "contracts/accept", {"offer_id": id}, "Контракт заключён"))
    for deal in board.get("mine", []):
        if deal is Dictionary and str(deal.get("status", "")) == "active":
            var cid := str(deal.get("id", ""))
            actions.add_child(_command("Расторгнуть %s (пошлина %s)" % [str(deal.get("name", "")), host._fmt_money(int(deal.get("cancel_fee", 0)))], "contracts/cancel", {"contract_id": cid}, "Контракт расторгнут"))
    _place()

func _pick(label: String, on: bool, apply: Callable) -> Button:
    var button: Button = host._ui_button(label, apply, 120)
    if on:
        button.modulate = Color(1, 0.86, 0.45)
    return button

func _set_product(id: String) -> void:
    product = id
    _render()

func _set_qty(n: int) -> void:
    qty = n
    _render()

func _set_price(kind: String) -> void:
    price_choice = kind
    _render()

func _set_term(n: int) -> void:
    term_months = n
    _render()

func _set_penalty(kind: String) -> void:
    penalty_choice = kind
    _render()

func _publish() -> void:
    var unit := _chosen_price()
    _post("contracts/offer", {"product": product, "qty": qty, "price": unit, "term_months": term_months, "penalty": _chosen_penalty(unit)}, "Предложение на доске")

func _command(label: String, path: String, fields: Dictionary, ok_text: String) -> Button:
    return host._ui_button(label, _run_command.bind(path, fields, ok_text), 460)

func _run_command(path: String, fields: Dictionary, ok_text: String) -> void:
    _post(path, fields, ok_text)

func _post(path: String, fields: Dictionary, ok_text: String) -> void:
    if pending:
        return
    var payload := fields.duplicate()
    payload["request_id"] = host._new_build_request_id()
    pending = true
    host.info.text = "Отправляем..."
    _request(HTTPClient.METHOD_POST, path, payload, func(code: int, data: Dictionary) -> void:
        pending = false
        if code == 200 or code == 201:
            host.info.text = ok_text
            if data.has("balance"):
                host._set_balance(int(data["balance"]))
            refresh()
        else:
            host.info.text = _error_text(str(data.get("error", "")), code)
    )

func _error_text(error: String, code: int) -> String:
    var known := {
        "price_out_of_range": "Цена вне 50–200% базовой",
        "invalid_qty": "Недопустимое количество",
        "invalid_term": "Срок от 1 до 24 месяцев",
        "invalid_penalty": "Штраф не больше цены",
        "too_many_offers": "Слишком много открытых предложений",
        "too_many_contracts": "Слишком много активных контрактов",
        "self_contract": "Нельзя заключить контракт с собой",
        "not_open": "Предложение уже разобрали",
        "not_owner": "Это не ваше предложение",
        "not_party": "Вы не сторона этого контракта",
        "invalid_state": "Контракт уже закрыт",
        "insufficient_funds": "Не хватает денег на пошлину",
        "unauthorized": "Сессия завершена, войдите снова",
        "npc_forbidden": "С городом и NPC контракты не заключаются",
    }
    return str(known.get(error, "Не получилось (HTTP %d)" % code))

func _status_name(status: String) -> String:
    match status:
        "active": return "идёт"
        "completed": return "исполнен"
        "cancelled": return "расторгнут"
        "dissolved": return "снят (банкротство)"
        _: return status

func _request(method: int, path: String, payload: Dictionary, callback: Callable) -> void:
    var req := HTTPRequest.new()
    req.timeout = 12.0
    host.add_child(req)
    req.request_completed.connect(func(result: int, code: int, _headers: PackedStringArray, response_body: PackedByteArray) -> void:
        req.queue_free()
        if result != HTTPRequest.RESULT_SUCCESS:
            callback.call(0, {})
            return
        var parsed = JSON.parse_string(response_body.get_string_from_utf8())
        callback.call(code, parsed if parsed is Dictionary else {})
    )
    var headers := PackedStringArray(["Content-Type: application/json", "Authorization: Bearer " + GameSession.access_token])
    var body := "" if method == HTTPClient.METHOD_GET else JSON.stringify(payload)
    if req.request(host.API_ROOT + path, headers, method, body) != OK:
        req.queue_free()
        callback.call(0, {})
