# Android hybrid updater (0.2.1 experimental)

- Android only; on startup GET `https://rikagro.ru/lunexeconom/updates/manifest.json`.
- APK: version_code gate, allowlisted HTTPS origin/path, bounded size, SHA-256 verification, then explicit system installer handoff using Android FileProvider. No silent installs. Test APK 0.2.1 uses same debug signing certificate as 0.2 (not 0.1).
- Content: optional JSON-only pack, bounded download, SHA-256 verification, schema check, stored as inert `user://verified_content.json`. **No gameplay consumer yet**. No remote scripts/scenes/packed resources or economic rules are executed.
- APK 0.2.1 was built in isolated VPS project; source scripts are in this branch. Test APK: https://rikagro.ru/lunexeconom/versions/Bashkiria-Honey-Oil-0.2.1-updater.apk
- Headless Godot 4.7.2 scene import/launch and updater_smoke passed. Android install intent, downloads, safe-area layout and on-device lifecycle remain **unverified**. User must confirm. The release manifest currently points at 0.2.1; updater download path requires a later 0.2.2 test build.
- This is a prototype, not production OTA. HTTPS and hashes detect accidental or transport corruption but are not independent authentication of a compromised release server. Before public rollout use offline-signed manifests or equivalent verified release signing, stable production keystore, recovery/rollback and stronger failure-path tests.
- The VPS site retains APK archives. No changes were made to other games.
