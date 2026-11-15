# ChatGPT8 PostgreSQL 200 actors: acceptance (2026-11-15)

## Execution
Isolated Docker PostgreSQL 16 on `127.0.0.1:15499`, disposable DB `lunex_ci`; migrations applied before test. Script `tools/postgres_ci_200_trades.py` executes 100 sellers followed by 100 buyers, each actor has a distinct TEST-NET-1 test client IP. Rate limiting is **not disabled**. There are 12 parallel worker threads per phase.

Result:
```json
{"actors":200,"max_workers":12,"status_codes":{"201":200},"matched_qty":100,"inventory_qty":100,"open_sell_qty":0,"unbalanced_ledger":0,"p95_ms":443.05}
```
Assertions passed. Production database was never used. Temporary container was deleted after the test. Server regression repeated: 542 tests, 55 skipped, 0 failures.

## Scope
This is 200 **operations** from 200 simulated actors, with 12 simultaneous worker threads, not 200 concurrent TCP connections. It invokes the PostgreSQL exchange handler, not a full HTTP load generator. The previous same-IP test had 80 HTTP-equivalent 429 due to the correct rate limiter; the new per-actor test passes with protection intact.

The isolated GitHub Actions integration workflow now includes this script, but GitHub Actions execution has **not been confirmed** (commit workflow runs query returned empty).

## Still open
Production-like HTTP throughput under 200 concurrent connections, server-authoritative construction stage scheduling and persistence, vehicle motion, Android APK/device visual acceptance and confirmed cloud CI.
