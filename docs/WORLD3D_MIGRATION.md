# World3D 2.5D migration: isolated stage 1

Status: prototype, **not** active in the Android main scene. Keep existing Node2D and server economy unchanged.

- `client/world3d/grid_projection.gd`: server integer x/y maps to 3D x/z at 2 metres per cell, negative chunk coordinates use floor division.
- `client/world3d/world3d.tscn`: standalone orthographic Camera3D, flat matte terrain in 12×12-cell chunks, 5×5 chunk window, tap-selection and one-finger pan / two-finger pinch.
- `client/tests/world3d_projection_smoke.gd`: projection and scene startup smoke test.
- No procedural buildings or simulated ownership: `apply_server_cells` is an intentionally unimplemented integration contract.
- Existing production UI, chunk event subscriptions, building models, roads, server sync, device gesture tests, Android performance and APK are **not** migrated yet.

## Next safe integration
1. Extract server snapshot/event stream into a renderer-neutral data adapter; do not change server APIs.
2. Introduce a read-only GLB registry with one building instance per object ID and footprint-aware placement.
3. Implement incremental per-chunk updates, roads and selection ray tests including HUD touch exclusion.
4. Add a development-only switch to render 2D or 3D; no production toggle until real-device QA.
5. Profile Compatibility vs Mobile on actual Android devices, then decide renderer and model budgets.

## Stage 2: read-only server visualization adapter

- `server_visual_adapter.gd` groups server cells by authoritative object ID and tracks road cells.
- `visual_factory.gd` draws inexpensive placeholder meshes for the existing server kinds; these are not the final GLB asset library.
- `world3d.gd` exposes `apply_chunk_snapshot`, `apply_server_event` and `apply_server_cells`. Rebuilds an object mesh if its footprint or kind changes.
- `tests/world3d_server_sync_smoke.gd` tests snapshot, grouping, roads and removal.
- **Not yet connected to production networking or live Android UI**. No change to PostgreSQL, active service or published APK.