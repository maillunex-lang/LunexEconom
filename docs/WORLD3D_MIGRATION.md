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