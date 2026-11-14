# Параллельная разработка: Claude (main) и ChatGPT (ветка)

Дата: 2026-11-14. Базовый коммит для ветки ChatGPT: `a4c015f` (или новее `main`).

## Роли
| Кто | Где работает | Зона ответственности |
|---|---|---|
| **Claude** | `main` | Игровая экономика: NPC-компании-конкуренты, рынок, производство, жители/зарплаты (позже) |
| **ChatGPT** | ветка `chatgpt/accounts-infra` | Аккаунты и безопасность, проверка PostgreSQL на настоящей БД, Android-сборка/обновление |

## Зоны файлов (кто владеет — тот и правит; чужое не трогать без согласования)

**Claude (не трогает ChatGPT):**
- `server/economy.py`, `server/production.py`, `server/clock.py`, `server/roads.py`, новый `server/npc.py`
- `server/test_economy.py`, `test_production.py`, `test_market.py`, `test_settlement.py`, `test_clock.py`, `test_roads.py`, новый `test_npc.py`
- `client/world.gd`, `client/world_screen.gd`, `client/chunk_renderer.gd`, `client/construction_planner.gd`, `client/road_*.gd`, `client/world_sync.gd`
- `docs/PROGRESS.md`, `docs/ROADMAP.md`, `.github/workflows/server-check.yml`

**ChatGPT (не трогает Claude):**
- `server/auth.py`, `server/test_auth.py`, новый `server/email_*.py` (если нужен)
- `client/main.gd`, `client/main.tscn`, `client/game_session.gd`, `client/updater.gd`, `client/tests/updater_smoke.gd`, `client/export_presets.cfg`
- `.github/workflows/android-*.yml`, `firebase-test-lab.yml`, **новый** `.github/workflows/postgres-check.yml`
- `ops/*`, `web/*`, `docs/ANDROID_*.md`, `docs/DEPLOYMENT.md`, `docs/SERVER_DEPLOYMENT.md` (раздел про учётные записи), **новый** `docs/PROGRESS_CHATGPT.md`

**Общие файлы (правим минимально, только добавлением):**
- `server/game_server.py`, `server/postgres_world.py`: ChatGPT — только маршруты `/auth/*` и вызовы в `auth.py`; Claude — всё про `/build`, `/wallet`, `/market`, `/world`. Не переформатировать и не переносить чужой код.
- `server/postgres_db.py` (SCHEMA): новые таблицы **добавлять в конец** своим блоком `CREATE TABLE IF NOT EXISTS ...`.

## Задачи
### Claude (main)
1. NPC-конкуренты: компании `npc:*` строят и торгуют на том же рынке (в `production.py` они обычные владельцы), детерминированные правила, тесты.
2. Отображение конкурентов в UI «Экономика».
3. Далее — жители и зарплаты.

### ChatGPT (ветка)
1. **Аккаунты:** подтверждение email, восстановление пароля, ротация токенов, постоянные (в БД) лимиты попыток, выход со всех устройств. Тесты в `test_auth.py`; экраны в `main.gd`.
2. **PostgreSQL на настоящей БД в CI:** новый workflow `postgres-check.yml` с service container `postgres:16`; прогнать все серверные тесты (`test_roads`, `test_economy`, `test_clock`, `test_settlement`, `test_market`, `test_production`, `test_auth`) с `LUNEX_DB_ENGINE=postgres`. Пока ветки `postgres_world.py`/`economy`/`production` проверены только на SQLite — **важная задача**. Найденные ошибки, относящиеся к PostgreSQL, — минимальными исправлениями в `postgres_world.py`, `postgres_db.py`, `production.py`; в коммите и в `PROGRESS_CHATGPT.md` указать, что исправлено.
3. **Android:** постоянная release-подпись (без секретов в репозитории), надёжность `updater.gd`, проверка совместимости.

## Правила
1. Ветка ChatGPT создаётся от свежего `main`; перед слиянием — `git rebase origin/main`, тесты и CI зелёные.
2. Слияние в `main` — только после сообщения Claude «закончил» (Claude называет итоговый SHA). Слияние в `main` автоматически выкатывает сервер на VPS (CI-gate + откат) — не сливать с красными проверками.
3. Журнал прогресса: Claude — `docs/PROGRESS.md`, ChatGPT — `docs/PROGRESS_CHATGPT.md` (потом объединяем одним коммитом).
4. Не менять баланс экономики (`economy.py`) и формат ответов `/wallet`, `/market`, `/world` без согласования.
5. Не вставлять секреты, токены, пароли в репозиторий.
