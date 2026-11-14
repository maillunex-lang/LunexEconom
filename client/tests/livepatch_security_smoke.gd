extends SceneTree
## Headless check of the LivePatch trust model: signed manifests only, header-only size checks, real JSON numbers, garbage collection.
## Needs the `openssl` command line (the same tool the administrator signs with). Always quits, also on failure.

var failures := 0

func _initialize() -> void:
	call_deferred("_run")

func _check(condition: bool, label: String) -> void:
	if not condition:
		failures += 1
		print("FAIL: ", label)

func _openssl(args: Array) -> bool:
	var output := []
	return OS.execute("openssl", args, output, true) == 0

func _png_header(width: int, height: int) -> PackedByteArray:
	var b := PackedByteArray([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0, 0, 0, 13, 0x49, 0x48, 0x44, 0x52])
	for value in [width, height]:
		b.append((value >> 24) & 255); b.append((value >> 16) & 255); b.append((value >> 8) & 255); b.append(value & 255)
	b.append_array(PackedByteArray([8, 0, 0, 0, 0, 0, 0, 0, 0]))
	b.resize(40)
	return b

func _write(path: String, bytes: PackedByteArray) -> void:
	var f := FileAccess.open(path, FileAccess.WRITE)
	f.store_buffer(bytes)
	f.close()

func _clean(directory: String) -> void:
	var dir := DirAccess.open(directory)
	if dir != null:
		for name in dir.get_files():
			dir.remove(name)

func _manifest(sha: String, size: int, revision: int) -> PackedByteArray:
	var doc := {"schema": 1, "revision": revision, "assets": [{"id": "building_farm", "category": "agriculture", "title": "Farm", "sha256": sha, "size": size, "extension": "png", "url": "blobs/" + sha + ".png"}]}
	return JSON.stringify(doc).to_utf8_buffer()

func _sign(private_key: String, message: PackedByteArray, name: String) -> String:
	var message_path := OS.get_user_data_dir() + "/" + name + ".msg"
	var sig_path := OS.get_user_data_dir() + "/" + name + ".sig"
	_write(message_path, message)
	if not _openssl(["dgst", "-sha256", "-sign", private_key, "-out", sig_path, message_path]):
		return ""
	return Marshalls.raw_to_base64(FileAccess.get_file_as_bytes(sig_path))

func _run() -> void:
	var base := OS.get_user_data_dir()
	var private_key := base + "/lp_private.pem"
	var public_key := base + "/lp_public.pem"
	var other_private := base + "/lp_other.pem"
	if not (_openssl(["genrsa", "-out", private_key, "2048"]) and _openssl(["rsa", "-in", private_key, "-pubout", "-out", public_key]) and _openssl(["genrsa", "-out", other_private, "2048"])):
		print("LIVEPATCH_SECURITY_SKIP no openssl")
		quit(0)
		return
	var patch = load("res://livepatch.gd").new()
	get_root().add_child(patch)
	patch.public_key_path = public_key

	# --- header-only size checks (a 249 KB file can declare a 16000 x 16000 canvas) ---
	_check(patch.header_dimensions("png", _png_header(64, 48)) == Vector2i(64, 48), "png dimensions")
	_check(patch.dimensions_ok(Vector2i(2048, 2048)), "2048x2048 is exactly the pixel budget")
	_check(not patch.dimensions_ok(Vector2i(2048, 2049)), "2048x2049 exceeds the limit")
	_check(patch.dimensions_ok(Vector2i(1024, 1024)), "1024x1024 is fine")
	_check(not patch.bytes_dimensions_ok("png", _png_header(40000, 40000)), "bomb header rejected")
	_check(not patch.bytes_dimensions_ok("png", _png_header(2049, 10)), "too wide rejected")
	_check(not patch.bytes_dimensions_ok("png", PackedByteArray([1, 2, 3])), "garbage rejected")
	var vp8x := PackedByteArray([0x52, 0x49, 0x46, 0x46, 0, 0, 0, 0, 0x57, 0x45, 0x42, 0x50, 0x56, 0x50, 0x38, 0x58, 10, 0, 0, 0, 0, 0, 0, 0, 99, 0, 0, 49, 0, 0, 0, 0])
	_check(patch.header_dimensions("webp", vp8x) == Vector2i(100, 50), "webp vp8x dimensions")

	# --- real JSON numbers are floats in Godot; the validator must still accept a real manifest ---
	var key: CryptoKey = patch.load_public_key()
	_check(key != null, "public key loads")
	var image := Image.create(8, 8, false, Image.FORMAT_RGBA8)
	image.fill(Color.RED)
	var directory := "user://livepatch/"
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(directory))
	_clean(directory)
	var png_path := directory + "tmp_farm.png"
	image.save_png(png_path)
	var png_bytes := FileAccess.get_file_as_bytes(png_path)
	var sha := FileAccess.get_sha256(png_path)
	DirAccess.remove_absolute(ProjectSettings.globalize_path(png_path))
	_write(directory + sha + ".png", png_bytes)
	var manifest := _manifest(sha, png_bytes.size(), 5)
	_check(patch._valid_manifest(JSON.parse_string(manifest.get_string_from_utf8())), "a real parsed manifest is valid (numbers are floats)")
	var good_sig := _sign(private_key, manifest, "good")
	_check(good_sig != "", "signing works")

	# --- signature verification ---
	_check(patch.verify_manifest(manifest, good_sig, key), "valid signature accepted")
	var tampered := _manifest(sha, png_bytes.size(), 6)
	_check(not patch.verify_manifest(tampered, good_sig, key), "tampered manifest rejected")
	_check(not patch.verify_manifest(manifest, _sign(other_private, manifest, "other"), key), "signature from another key rejected")
	_check(not patch.verify_manifest(manifest, "bm90IGEgc2lnbmF0dXJl", key), "garbage signature rejected")
	_check(not patch.verify_manifest(manifest, "", key) and not patch.verify_manifest(manifest, good_sig, null), "empty signature / missing key rejected")

	# --- activation ---
	_write(directory + "manifest.json", manifest)
	_write(directory + "manifest.sig", good_sig.to_ascii_buffer())
	var bridge = load("res://patch_visuals.gd").new()
	get_root().add_child(bridge)
	bridge.key_override = public_key
	_check(bridge.activate_from_cache(), "signed cache activates")
	_check(bridge.texture_for("farm") != null and bridge.active_revision == 5, "farm texture is available")
	_check(patch.image_for("building_farm") != null, "image_for resolves a verified asset")
	bridge.key_override = base + "/does_not_exist.pem"
	_check(not bridge.activate_from_cache(), "no public key -> nothing activates")
	bridge.key_override = public_key
	_write(directory + "manifest.json", tampered)
	_check(not bridge.activate_from_cache(), "tampered cached manifest is not activated")

	# --- an oversized canvas is refused before decoding, even with a valid signature and hash ---
	var bomb := _png_header(40000, 40000)
	var bomb_sha := bomb.get_string_from_ascii().sha256_text()
	_write(directory + "bomb.tmp", bomb)
	var bomb_hash := FileAccess.get_sha256(directory + "bomb.tmp")
	DirAccess.remove_absolute(ProjectSettings.globalize_path(directory + "bomb.tmp"))
	_write(directory + bomb_hash + ".png", bomb)
	var bomb_manifest := _manifest(bomb_hash, bomb.size(), 7)
	_write(directory + "manifest.json", bomb_manifest)
	_write(directory + "manifest.sig", _sign(private_key, bomb_manifest, "bomb").to_ascii_buffer())
	_check(not bridge.activate_from_cache(), "oversized canvas refused")
	_check(patch.image_for("building_farm") == null, "image_for refuses an oversized canvas")

	# --- garbage collection keeps referenced images and removes strays ---
	_write(directory + "manifest.json", manifest)
	_write(directory + "manifest.sig", good_sig.to_ascii_buffer())
	_write(directory + "stray.png", PackedByteArray([1, 2, 3]))
	_write(directory + "left_over.part", PackedByteArray([1]))
	var removed: int = patch.collect_garbage()
	_check(removed >= 2, "stray files removed")
	_check(FileAccess.file_exists(directory + sha + ".png"), "referenced image kept")
	_check(not FileAccess.file_exists(directory + "stray.png"), "stray image gone")

	_clean(directory)
	if failures == 0:
		print("LIVEPATCH_SECURITY_SMOKE_PASS")
	else:
		print("LIVEPATCH_SECURITY_SMOKE_FAILED ", failures)
	quit(1 if failures > 0 else 0)
