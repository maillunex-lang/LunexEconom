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
