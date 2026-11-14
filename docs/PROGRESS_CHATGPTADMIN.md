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
