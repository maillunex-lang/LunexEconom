# ChatGPT8 Android APK build verification — 2026-11-15

A **fresh, separate, gamedev-owned Git worktree** was created from `origin/ChatGPT8` (commit `069a07b`). Godot 4.7.2 editor import succeeded. Debug Android export succeeded (exit code 0) after avoiding an older root-owned `.godot` export cache that had caused scene export errors.

Artifact on isolated VPS only: `/tmp/chatgpt8-apk-qa/LunexEconom-ChatGPT8-clean-debug.apk`, approximately 55 MiB. This is a **debug** build, not a production release or published APK.

Validation:
- `unzip -t`: no compressed-data errors.
- `aapt dump badging`: package `ru.lunex.bashkiriahoneyoil`, versionCode 13, versionName `0.2.8.1-main-menu-test`, minSdk 24, targetSdk 36, native ABIs `arm64-v8a`, `x86_64`.
- `apksigner verify --verbose`: **Verifies**, v2/v3 signing valid, one signer.
- SHA256: `e208570ac042b79cb8c747e336126e0be51771ca5345980455f0ee22729830e4`.
- Export log still reports `No project icon specified`; must be fixed for polished release.
- No Android device/emulator launch was performed. No claim of visual/touch acceptance.
- APK has **not** been deployed to the public landing page, nor made available through a download URL.

The VPS production game, nginx, database and GitHub `main` were not modified.
