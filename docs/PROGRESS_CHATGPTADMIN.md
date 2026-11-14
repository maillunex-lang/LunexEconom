# ChatGPTAdmin · World Studio + LivePatch

Base: main a9bb74cffb532107d5932e09bb81fc5433e32c34. Isolated branch ChatGPTAdmin.

## Implemented in initial prototype
- Separate stdlib Python service and SQLite catalog (never connects to game DB).
- Responsive Russian web UI with bearer-token protected asset management, prompt metadata and immutable release snapshots.
- PNG/WebP content-addressed blobs and public read-only revision manifest, SHA-256 and size metadata.
- Explicit publication and audit history; no executable mods.
- Godot Android content downloader module (opt-in; not wired into game startup) with SHA-256 and size verification and local atomic file writes.

## Deliberately NOT implemented or deployed
- No production nginx routes, service or database changes.
- No real God Mode city placement or economy/time editing yet: needs authoritative game-server API, permissions and audit.
- No signed manifests, automatic background startup, resource hot-swapping in running world or device tests.
- No release to main, no PR. Claude must review and merge only on owner request.

## Iteration 2 · Draft world editor
- Added isolated city draft catalog with editable population, tax rates, simulated month duration and growth rate. Values have explicit validation, never reach live game DB.
- Added municipal-only building placement (school, hospital, park), footprint collision checks, ownership 'city', removal, audit and export as review-only JSON.
- Added simple web grid editor with click-to-place and panning, plus illustrative demographic preview. It is NOT the authoritative isometric game map or full economic simulation.
- Added authenticated API routes and integration tests. No deployment or main merge.
- Before real God Mode: introduce game-server RBAC, preview of real occupied cells, financial ledger integration, migrations, staged approval and idempotent authoritative commands.

## Iteration 3 · Read-only world collision preview
- Added fixed-upstream, authenticated chunk preview for the existing game-server /chunk contract; bounded coordinates, response sizes, request timeout and filtered cell records.
- Added preview-only conflict checks against municipal draft footprints, with web button and two isolated stub-server tests.
- Preview never writes to game world or financial ledgers; concurrent server changes can invalidate the result. Live placement requires a future server-authoritative transaction and RBAC.
- No production deployment, nginx changes or Android patch rollout.

## Iteration 4 · Opt-in Android visual patch bridge
- Added `client/patch_visuals.gd` cache-only image resolver with allowlisted building kinds, SHA-256 recheck, image decoding and 2048px dimension ceiling.
- The existing isometric chunk renderer can display downloaded building PNG/WebP textures instead of procedural placeholders, falling back safely when no patch is active. Ground anchor and ownership badge are preserved.
- Patch activation triggers redraw of existing chunks, not a world-wide rebuild. No automatic network downloads, no autoload, no change to production APK or server.
- Fixed preexisting GDScript parser issues in `livepatch.gd` (typed Variant and HashingContext SHA-256).
- Headless Godot 4.7.2 `patch_visuals_smoke.gd` and `chunk_renderer_smoke.gd` passed; 12 Python studio tests passed. Device testing, signed manifests and rollout/rollback policy still required before enabling automatic patch checks.

## Iteration 5 · Manual release rollback and staged Android manifests
- Admin release history and authenticated rollback endpoint reissue an immutable historical asset snapshot with a new increasing revision. No destructive overwrite of past releases.
- Publishing now locks the catalog snapshot before reading, and enforces the Android 300-asset limit.
- Admin web UI lists releases and asks for confirmation before rollback.
- Godot downloader skips older/equal revisions, preserves a previous verified manifest when installing a new one, and offers manual restore_previous() after verifying cached asset hashes. No auto-download on startup.
- Python studio: 13 tests passed; Godot patch visuals smoke passed.
- Security blocker: manifests are not yet asymmetrically signed or verified by Android; DO NOT expose automatic update activation to production clients. APK device test and proper admin auth still pending.
