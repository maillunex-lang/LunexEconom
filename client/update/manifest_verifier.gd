extends RefCounted
## Rejects manifests with no pinned public key or a detached invalid signature.
const PublicBase = preload("res://config/public_base.gd")
const PUBLIC_KEY := "res://config/update_public.pem"
const LIMIT := 65536

static func verify(raw: PackedByteArray, signature_b64: String, key_path: String = PUBLIC_KEY) -> bool:
    if raw.is_empty() or raw.size() > LIMIT or signature_b64.is_empty() or signature_b64.length() > 4096:
        return false
    if not FileAccess.file_exists(key_path):
        return false
    var key := CryptoKey.new()
    if key.load(key_path, true) != OK:
        return false
    var signature := Marshalls.base64_to_raw(signature_b64.strip_edges())
    if signature.is_empty():
        return false
    var context := HashingContext.new()
    context.start(HashingContext.HASH_SHA256)
    context.update(raw)
    return Crypto.new().verify(HashingContext.HASH_SHA256, context.finish(), signature, key)

static func valid_payload(data: Variant, max_bytes: int) -> bool:
    if not data is Dictionary:
        return false
    var sha := str(data.get("sha256", "")).to_lower()
    if sha.length() != 64 or not sha.is_valid_hex_number():
        return false
    var size := int(data.get("size", 0))
    return size > 0 and size <= max_bytes and PublicBase.allows_file_url(str(data.get("url", data.get("apk_url", ""))))

static func valid_update(data: Variant) -> bool:
    if not data is Dictionary:
        return false
    if int(data.get("version_code", 0)) <= 0 or int(data.get("min_version_code", 0)) < 1:
        return false
    if int(data.get("min_version_code", 0)) > int(data.get("version_code", 0)):
        return false
    if str(data.get("version_name", "")).is_empty() or not data.get("notes", "") is String:
        return false
    if str(data.get("released", "")).is_empty():
        return false
    return str(data.get("apk_url", "")).ends_with(".apk") and valid_payload(data, 250 * 1024 * 1024)

static func valid_content(data: Variant) -> bool:
    if not data is Dictionary or int(data.get("schema", 0)) != 1:
        return false
    if not data.get("packs") is Array or data["packs"].size() > 100:
        return false
    var seen := {}
    for pack in data["packs"]:
        if not valid_payload(pack, 100 * 1024 * 1024):
            return false
        var name := str(pack.get("name", ""))
        var version := str(pack.get("version", ""))
        if name.is_empty() or version.is_empty() or not name.is_valid_identifier() or not version.is_valid_filename() or ".." in name or ".." in version:
            return false
        if seen.has(name):
            return false
        seen[name] = true
        if str(pack.get("url", "")) != PublicBase.url("packs/" + name + "-" + version + ".pck"):
            return false
        if not pack.get("priority", "") in ["required", "background"]:
            return false
        if not pack.get("dependencies", []) is Array or int(pack.get("min_version_code", 0)) < 1:
            return false
    for pack in data["packs"]:
        for dependency in pack.get("dependencies", []):
            if not dependency is String or not seen.has(dependency) or dependency == pack["name"]:
                return false
    return true
