# ChatGPT8: runtime GLB QA and merged-main acceptance (2026-11-15)

## Confirmed
- Branch ChatGPT8 merged fresh main commit `7b7831f` using merge commit `292ca532`, after isolated worktree tests.
- Combined codebase: 542 server tests (55 skipped), 20 tool tests (1 skipped), 38 ops tests, 38 admin studio tests, all passed.
- 60 GLBs validated, Godot 4.7.2 import exit 0.
- Godot build menu smoke `BUILD_MENU_SMOKE_PASS`.
- New `client/tests/asset_runtime_smoke.gd` checks seven actual model loader paths and instantiation, including truck, tractor, foundation, frame, corner road, grain field and oil well. Local Godot result: `ASSET_RUNTIME_SMOKE_PASS count=7`.
- The Godot GitHub Actions workflow now includes build menu and runtime asset smoke jobs.

## Still not accepted
- Actual GitHub Actions run status not observed; no claim of green CI.
- Transport motion and construction stage transitions are not wired into the world.
- Android UI screenshot and complete art review of all 60 models remain.
- PostgreSQL 200-operation experiment hit 120/min/IP protection: 120 accepted, 80 rejected with 429. A passing multi-client PostgreSQL stress run is still required.
- Full end-to-end `regions.overview` benchmark remains; the 2.19x figure is only price-query microbenchmark.
