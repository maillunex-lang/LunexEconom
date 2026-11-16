extends RefCounted
## Empty until the operator publishes reviewed, permanent HTTPS documents.
static func url(kind: String) -> String:
    if kind not in ["policy","terms"]:
        return ""
    var value := str(ProjectSettings.get_setting("lunex/consent_" + kind + "_url", ""))
    if not value.begins_with("https://") or "@" in value or "\\" in value or "#" in value or "?" in value or ".." in value or " " in value:
        return ""
    return value
