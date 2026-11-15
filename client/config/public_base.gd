extends RefCounted
## Single configurable public origin for Android. Override with ProjectSettings
## 'lunex/public_base_url' in trusted local build configuration.
static var default_base_url: String = "https://rikagro.ru/lunexeconom"

static func base_url() -> String:
    var value := str(ProjectSettings.get_setting("lunex/public_base_url", default_base_url)).trim_suffix("/")
    if not value.begins_with("https://") or "@" in value or "?" in value or "#" in value:
        return ""
    return value

static func url(relative_path: String) -> String:
    if relative_path.begins_with("/") or ".." in relative_path or "://" in relative_path:
        return ""
    var base := base_url()
    if base.is_empty():
        return ""
    return base + "/" + relative_path

static func allows_file_url(url_value: String) -> bool:
    var base := base_url()
    return not base.is_empty() and url_value.begins_with(base + "/") and not "?" in url_value and not "#" in url_value and not "%" in url_value and not ".." in url_value and not "@" in url_value and not "\\" in url_value
