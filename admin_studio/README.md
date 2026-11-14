# Lunex World Studio · LivePatch MVP

**Status:** integrated into `main` but **not deployed anywhere** (no systemd unit, no nginx route). Full guide, security model and operating procedure: [`docs/ADMIN.md`](../docs/ADMIN.md). The studio never writes to the game database: game moderation goes through the game server's loopback-only `/admin/*` API (`server/admin_api.py`).

Run in a disposable environment:

```sh
cd admin_studio
export LUNEX_ADMIN_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
export LUNEX_STUDIO_DATA=/tmp/lunex-studio-test
python3 server.py
```

Open http://127.0.0.1:18991 locally via SSH tunnel. Never expose this HTTP port to the Internet; production requires TLS reverse proxy, restricted access, rate limits, CSRF/origin protections and preferably a proper admin identity provider with MFA. The bearer token is held in browser memory only and is not persisted.

Public GET /patch/manifest.json and /patch/blobs/<sha256>.<png|webp>; admin-only GET /api/assets, /api/audit; admin-only POST /api/assets and /api/publish. Upload is allowlisted to PNG/WebP and 8 MB. This prototype validates file headers and hashes, not full image decoding. The Android client must verify SHA-256 and size before activating; see client/livepatch.gd. Manifest trust depends on HTTPS and an authenticated origin; signed manifests are required before public rollout.

Release publication snapshots a catalog of image hashes. No arbitrary scripts, PCK, GDScript or executable mods. A patch changes image data only, not gameplay rules. UI prompt field is metadata, not an automatic paid image generator.

Planned: game-server-owned economy and municipal building commands, authorization/RBAC, world editor, preview/staging, signed manifests, automatic rollback, Android physical device test, background download limits, content delivery CDN and release channel separation.

### Draft world editor (iteration 2)
Admin endpoints: GET/POST /api/cities, GET /api/cities/{id}, POST /api/buildings, POST /api/buildings/remove, POST /api/forecast and POST /api/export-city. Drafts persist in the studio's separate SQLite database. All modifications are inert until an explicitly designed authoritative game-server command flow is implemented. Only municipal school/hospital/park objects are supported; no player-owned plots can be changed. Forecast is illustrative population arithmetic only.

### Read-only upstream preview (iteration 3)
Set LUNEX_WORLD_PREVIEW_UPSTREAM to the trusted, operator-controlled game server origin (default http://127.0.0.1:18767). Authenticated GET /api/preview/chunk?cx=0&cy=0 and POST /api/preview/check with city_id,cx,cy fetch a live /chunk snapshot and flag draft conflicts. This is a best-effort preview, not a placement authorization. Never allow user-defined upstream URLs. In production, use an internal network with explicit network ACLs and no exposure of private game APIs.

### Release history and rollback (iteration 5)
Admin GET /api/releases lists the 100 latest immutable releases. POST /api/rollback-release with JSON {"revision":1} republishes that historical snapshot as a new revision, after checking that the referenced blobs still exist. No assets or historical records are deleted. Clients never downgrade automatically. Client `restore_previous()` is a manual emergency rollback of the cached manifest after verifying its referenced blobs.

**Hardening added at integration:** header-only image size limits (server and client), RSA-SHA256 signed releases verified in the client against a key shipped in the APK (private key stays offline; `sign_release.py`), sign-in throttling and read timeouts, audit with client address, real JSON number handling in the Android validator. **Still do not enable production auto-updates:** the transport is HTTPS but the manifest lacks an application-level Ed25519 signature verified against a pinned public key in the APK. A maliciously altered manifest could otherwise direct content replacement. Require signing, trusted-key distribution, staged channels and on-device tests before activation.
