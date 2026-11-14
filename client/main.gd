extends Control

@onready var status_label: Label = $Center/Status
@onready var retry_button: Button = $Center/Retry
var request: HTTPRequest

func _ready() -> void:
    retry_button.pressed.connect(_check_server)
    request = HTTPRequest.new()
    add_child(request)
    request.request_completed.connect(_on_request_completed)
    _check_server()

func _check_server() -> void:
    status_label.text = "Подключение к тестовому серверу..."
    # Development-only loopback. Android builds will use a separately configured HTTPS endpoint.
    var err := request.request("http://127.0.0.1:18761/health")
    if err != OK:
        status_label.text = "Сервер недоступен (код %s)" % err

func _on_request_completed(_result: int, code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
    if code != 200:
        status_label.text = "Сервер не подключён. Код HTTP: %s" % code
        return
    var parsed = JSON.parse_string(body.get_string_from_utf8())
    if parsed is Dictionary and parsed.get("ok", false):
        status_label.text = "Сервер Foundation доступен"
    else:
        status_label.text = "Некорректный ответ сервера"