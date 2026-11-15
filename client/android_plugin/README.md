# Android installation plugin (Godot 4.7)
Java AAR (no private keys). Requires Gradle export, ENABLED editor plugin and custom Android build template.
Build: `gradle -p client/android_plugin :plugin:assembleDebug :plugin:assembleRelease`.
CI copies `plugin/build/outputs/aar/plugin-debug.aar` and `plugin-release.aar`
to `client/addons/lunex_installer/bin/{debug,release}/LunexInstaller-*.aar`.
Supports PackageInstaller session, user confirmation when Android requires it; FileProvider fallback.
Unknown-apps permission is user-controlled; on Android 12+ USER_ACTION_NOT_REQUIRED is only
honored under Android eligibility and installer-of-record conditions.
Not verified on a physical Android device yet.

Uses the Godot Android template existing FileProvider (authority applicationId.fileprovider) to avoid Android manifest merger conflicts.
