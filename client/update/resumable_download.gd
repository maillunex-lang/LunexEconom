extends Node
## Range downloader with content validation. Partial files keyed by expected SHA.
signal progress(received: int, total: int)
signal finished(path: String)
signal failed(reason: String)
const PublicBase = preload("res://config/public_base.gd")
const CHUNK := 512 * 1024
const MAX_RETRIES := 4
var busy := false
## Optional pinned HTTPS certificate for isolated integration tests.
var tls_options: TLSOptions = null

func download(file_url: String, destination: String, expected_size: int, digest: String, wifi_only: bool = false) -> void:
    if busy:
        return
    if not PublicBase.allows_file_url(file_url) or expected_size < 1 or expected_size > 250 * 1024 * 1024 or digest.length() != 64 or not digest.is_valid_hex_number():
        failed.emit("Небезопасный адрес или метаданные")
        return
    if wifi_only and not _is_wifi():
        failed.emit("Включена загрузка только по Wi-Fi")
        return
    busy = true
    var temp_path := destination + "." + digest.to_lower() + ".part"
    DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(destination.get_base_dir()))
    if FileAccess.file_exists(temp_path) and _file_size(temp_path) > expected_size:
        DirAccess.remove_absolute(ProjectSettings.globalize_path(temp_path))
    var offset := _file_size(temp_path) if FileAccess.file_exists(temp_path) else 0
    var retries := 0
    while offset < expected_size:
        if wifi_only and not _is_wifi():
            busy = false
            failed.emit("Wi-Fi отключён")
            return
        var end: int = mini(offset + CHUNK, expected_size) - 1
        var request := HTTPRequest.new()
        request.timeout = 30
        request.max_redirects = 0
        request.body_size_limit = CHUNK + 512
        if tls_options != null:
            request.set_tls_options(tls_options)
        add_child(request)
        var err := request.request(file_url, PackedStringArray(["Range: bytes=%d-%d" % [offset, end], "Accept-Encoding: identity"]))
        var result: Array = []
        if err == OK:
            result = await request.request_completed
        request.queue_free()
        var ok := err == OK and result.size() == 4
        if ok:
            var status_code := int(result[1])
            var payload: PackedByteArray = result[3]
            ok = status_code == 206 and payload.size() == end - offset + 1 and _valid_range(result[2], offset, end, expected_size)
            if ok:
                var writer: FileAccess = null
                if FileAccess.file_exists(temp_path):
                    writer = FileAccess.open(temp_path, FileAccess.READ_WRITE)
                else:
                    writer = FileAccess.open(temp_path, FileAccess.WRITE_READ)
                if writer == null:
                    ok = false
                else:
                    writer.seek_end()
                    writer.store_buffer(payload)
                    writer.close()
                    offset += payload.size()
                    retries = 0
                    progress.emit(offset, expected_size)
        if not ok:
            retries += 1
            if retries > MAX_RETRIES:
                busy = false
                failed.emit("Загрузка прервана; можно продолжить позднее")
                return
            await get_tree().create_timer(float(1 << (retries - 1))).timeout
    if FileAccess.get_sha256(temp_path).to_lower() != digest.to_lower():
        DirAccess.remove_absolute(ProjectSettings.globalize_path(temp_path))
        busy = false
        failed.emit("SHA-256 не совпадает, файл удалён")
        return
    if FileAccess.file_exists(destination):
        DirAccess.remove_absolute(ProjectSettings.globalize_path(destination))
    if DirAccess.rename_absolute(ProjectSettings.globalize_path(temp_path), ProjectSettings.globalize_path(destination)) != OK:
        busy = false
        failed.emit("Не удалось сохранить скачанный файл")
        return
    busy = false
    finished.emit(destination)

func _file_size(path: String) -> int:
    var f := FileAccess.open(path, FileAccess.READ)
    return f.get_length() if f else 0

func _valid_range(headers: PackedStringArray, start: int, end: int, total: int) -> bool:
    var expected := "bytes %d-%d/%d" % [start, end, total]
    for header in headers:
        if header.to_lower().begins_with("content-range:"):
            return header.split(":", false, 1)[1].strip_edges() == expected
    return false

func _is_wifi() -> bool:
    if OS.get_name() != "Android" or not Engine.has_singleton("LunexInstaller"):
        return false
    return bool(Engine.get_singleton("LunexInstaller").isWifiConnected())
