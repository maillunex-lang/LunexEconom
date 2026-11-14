# Foundation 0.1

Game: **Башкирия: Мёд и Нефть**. Repository: `maillunex-lang/LunexEconom`.

## Confirmed product constraints
- Android only; landscape, touch and safe-area aware.
- 2D isometric 45°; 20 economic regions in final game, one region for first playable alpha.
- Authoritative 24/7 MMO economy, 1 real day = 1 game month.
- NPC economy without LLM; financial transactions must be server-side.
- PostgreSQL with transaction journal is the approved target persistence layer.

## Current implementation
- Godot foundation scene with title and a development server health check.
- Python standard-library HTTP server on **loopback only**.
- Session creation is a temporary development stub: it is **not authentication**.
- /world exposes metadata only, with 0 active regions.
- Unit tests for API behavior and input validation.

## Not yet implemented
- PostgreSQL schema/migrations, financial ledger, auth, world generator, multiplayer synchronization, real NPC, gameplay, APK signing, production deployment.
- Do not expose the development server publicly or use session IDs for real accounts.

## Run tests
`cd server && python3 -m unittest -v test_app.py`

## Run locally
`cd server && python3 app.py`
Godot project is in `client/`. Server defaults to `127.0.0.1:18761`.

## Safety
Do not reuse production DB credentials, modify running services, or deploy on the existing HTTPS host without a separate review. No other project is a dependency.