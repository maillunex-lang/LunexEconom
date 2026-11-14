# Lunex World Studio · LivePatch MVP

**Status:** isolated prototype. No production deployment, no nginx configuration, no game database writes.

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
