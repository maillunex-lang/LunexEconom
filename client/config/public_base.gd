extends RefCounted
## Single configurable public origin for Android. Override with ProjectSettings
## 'lunex/public_base_url' in trusted local build configuration.
static var default_base_url: String = "https://rikagro.ru/lunexeconom/v2"

static func base_url() -> String:
    var value := str(ProjectSettings.get_setting("lunex/public_base_url", default_base_url)).trim_suffix("/")
    if not value.begins_with("https://") or value.length() <= 8 or "@" in value or "?" in value or "#" in value or "%" in value or "\\" in value or ".." in value or " " in value or "	" in value or "
" in value or "//" in value.substr(8):
        return ""
    return value

## API route is separate from the public update/download origin.
## V2 uses /api under the V2 public base. Change only for an approved future cutover.
static var default_api_path: String = "api"

static func api_url() -> String:
    var api_path := str(ProjectSettings.get_setting("lunex/api_path", default_api_path))
    if api_path.is_empty() or api_path != api_path.strip_edges():
        return ""
    if api_path.begins_with("/") or api_path.ends_with("/") or "\\" in api_path:
        return ""
    if "@" in api_path or "?" in api_path or "#" in api_path or ".." in api_path or "://" in api_path:
        return ""
    for segment in api_path.split("/"):
        if segment.is_empty():
            return ""
        for character in segment:
            if not (character.is_valid_identifier() or character.is_valid_int() or character == "-"):
                return ""
    var base := base_url()
    if base.is_empty() or ".." in base:
        return ""
    return base + "/" + api_path

static func url(relative_path: String) -> String:
    if relative_path.is_empty() or relative_path.begins_with("/") or relative_path.ends_with("/") or ".." in relative_path or "://" in relative_path or "//" in relative_path or "?" in relative_path or "#" in relative_path or "%" in relative_path or "@" in relative_path or "\\" in relative_path:
        return ""
    var base := base_url()
    if base.is_empty():
        return ""
    return base + "/" + relative_path

static func allows_file_url(url_value: String) -> bool:
    var base := base_url()
    return not base.is_empty() and url_value.begins_with(base + "/") and not "?" in url_value and not "#" in url_value and not "%" in url_value and not ".." in url_value and not "@" in url_value and not "\\" in url_value
