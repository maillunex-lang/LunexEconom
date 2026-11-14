# Параллельная разработка: Claude (main) и ChatGPT (ветка)

## Раунд 2 (с 2026-11-14, база `c104bd4`)

### Роли
| Кто | Где работает | Зона ответственности |
|---|---|---|
| **Claude** | `main` | Игровая экономика: налоги и бюджет города, замкнутый денежный круг (жители тратят зарплату), затем контракты между игроками; экономические панели клиента |
| **ChatGPT** | ветка `chatgpt/release-ops` (от свежего `main`) | Релиз и эксплуатация: публикация подписанного APK, `manifest.json` для обновлений, резервные копии и нагрузка, графика/производительность карты |

### Зоны файлов (владелец правит, чужое не трогает без согласования)

**Claude:**
- `server/economy.py`, `production.py`, `bank.py`, `npc.py`, `clock.py`, `roads.py`, новые `server/tax*.py`, `server/contracts*.py`
- тесты экономики: `server/test_economy.py`, `test_production.py`, `test_market.py`, `test_settlement.py`, `test_labor.py`, `test_bankruptcy.py`, `test_sell.py`, `test_bank.py`, `test_npc.py`, `test_clock.py`, `test_roads.py`, новые `test_tax*.py`, `test_contracts*.py`
- `client/world.gd`, `client/world_screen.gd`, `client/construction_planner.gd`, `client/road_*.gd`, `client/world_sync.gd`
- `docs/PROGRESS.md`, `docs/ROADMAP.md`, `.github/workflows/server-check.yml`

**ChatGPT:**
- `.github/workflows/android-*.yml`, `firebase-test-lab.yml`, `postgres-check.yml`, **новые** workflow-файлы
- `ops/*` (кроме `ops/update_server.py` и его теста — они уже в `main`, менять только по согласованию), `web/*`
- `client/chunk_renderer.gd` (отрисовка карты, спрайты зданий, анимации, LOD), новые `client/art/*`, `client/updater.gd`, `client/main.gd`, `client/main.tscn`, `client/game_session.gd`, `client/export_presets.cfg`, `client/tests/*`
- `server/auth.py`, `server/test_auth.py`, `server/test_postgres_*.py`
- `docs/ANDROID_*.md`, `docs/DEPLOYMENT.md`, `docs/SERVER_DEPLOYMENT.md`, `docs/device-tests/*`, **новый** `docs/PROGRESS_CHATGPT.md`

**Общие файлы — только добавление, без переформатирования чужого:**
- `server/game_server.py`, `server/postgres_world.py`: Claude — экономические маршруты (`ECONOMY_POST`, `/market`, `/wallet`, `/sell`, `/loan`, новые); ChatGPT — маршруты `/auth/*` и служебные (`/health`, `/metrics`), если понадобятся.
- `server/postgres_db.py` (SCHEMA): новые таблицы — каждый своим блоком, не трогая чужие строки.
- `client/world.gd`: принадлежит Claude. ChatGPT, если нужен хук для отрисовки, делает минимальную аддитивную правку и сообщает в `PROGRESS_CHATGPT.md`.

### Задачи
**Claude**
1. Налоги и бюджет города: налог на прибыль и имущество, бюджет в `system:*`, расходы города (содержание дорог/служб), вывод в «Экономике».
2. Замкнутый денежный круг: жители тратят доходы реальными деньгами (покупают продукцию), а не из бездонного счёта рынка.
3. Далее — контракты между игроками.
4. (сделано) Мэр и выборы: `server/city.py`, API `/city`, `/city/taxes`, `/city/build`, `/city/candidacy`, `/city/vote`; вкладка «Город» в клиенте.

**ChatGPT**
1. **Релиз:** `android-release.yml` публикует **подписанный** APK (а не debug-артефакт); обновление `updates/manifest.json` на VPS (`ops/deploy.py` + тесты, ручной шаг переустановки скрипта на VPS описать в `docs/DEPLOYMENT.md`), чтобы кнопка «Обновить» видела новые сборки; шаблон отчёта об испытании на устройстве.
2. **Эксплуатация:** скрипт проверки восстановления из резервной копии PostgreSQL (на отдельной временной БД), простой нагрузочный тест API (локально/CI, не по боевому серверу), расширенный `/health` (версия коммита, состояние БД) без изменения формата существующих ответов.
3. **Карта:** улучшение отрисовки в `chunk_renderer.gd` (читаемые спрайты ферм/шахт/заводов/складов, дорожные перекрёстки, цвета владельцев NPC/игрока — владелец доступен как `server_cells[cell].owner`), измерение FPS и оптимизация перерисовки.

### Правила
1. Ветка создаётся от свежего `main`; перед слиянием — `git rebase origin/main`, все тесты и CI зелёные (в том числе `postgres-check`).
2. Слияние в `main` — только после сообщения Claude «закончил» с итоговым SHA. Слияние выкатывает сервер на VPS автоматически (CI-gate + откат).
3. Журнал: Claude — `docs/PROGRESS.md`, ChatGPT — `docs/PROGRESS_CHATGPT.md` (объединяем после слияния одним коммитом).
4. Баланс экономики (`economy.py`) и форматы `/wallet`, `/market`, `/world`, `/sell`, `/loan` без согласования не менять.
5. Не вставлять секреты, токены, пароли в репозиторий; боевой сервер и VPS не трогать без отдельного решения владельца.
6. Любое новое SQLite-соединение — только через `server/sqlite_util.py` (`open_db`), иначе вернутся предупреждения `unclosed database`.

## Раунд 1 (завершён, слит PR №2, merge `229c896`)
Claude: NPC-конкуренты, жители и зарплаты, банкротство, продажа зданий, банк и кредиты. ChatGPT: аккаунты (email, восстановление пароля, ротация токенов), PostgreSQL в CI, подготовка подписи Android. Итоговая проверка совместимости — `docs/PROGRESS.md`, запись «Проверка совместимости после слияния PR #2».
