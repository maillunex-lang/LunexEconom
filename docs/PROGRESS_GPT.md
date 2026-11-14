# PROGRESS_GPT: раунд 3, рейтинг компаний и лента событий

Дата: 2026-11-14. Проект: «Башкирия: Мёд и Нефть», репозиторий `maillunex-lang/LunexEconom`.
Ветка: только `GPTFirst`, создана от `main` `551acef541fd9697f75787b29915be3b9f0641c6`.
PR не создавался. `main`, `GrokFirst`, боевая БД, VPS и другие сервисы не изменялись.

## Выполнено

- `GET /leaderboard?by=networth|income|buildings`, Bearer: 20 лидеров, место своей компании вне топ-20, NPC с меткой `npc`. Чистая стоимость: деньги + оценка зданий по `BUILD_COST` − банковский долг; `income` соответствует выручке последнего отчётного месяца. Имена игроков без e-mail.
- `GET /feed?after=N`, Bearer: персональные события из существующих журналов и таблиц: строительство, продажа, месячная прибыль/убыток, налоги, кредиты, банкротство (включая случаи без платежа), жалование мэра, кандидатура и результаты выборов. При открытии `after=0` возвращаются последние до 50 записей. Ненулевой курсор продолжает отсортированную проекцию событий.
- Общий `server/stats.py` принимает `db` и `ph`, поддерживает SQLite и PostgreSQL без новой таблицы, проводок, `npc_tick()`, `advance()` или изменений состояния мира.
- SQLite использует `sqlite_util.open_db` и `PRAGMA query_only=ON`; PostgreSQL использует `SET TRANSACTION READ ONLY`.
- Панели `client/leaderboard_panel.gd` и `client/feed_panel.gd` выполнены в Forest Glass; минимальная интеграция с `world_screen.gd` через «Меню», не меняющая нижние кнопки, штатный маршрут касаний и safe-area.
- Новые `server/test_stats.py`, `server/test_postgres_stats.py`, офлайн Godot smoke `client/tests/stats_panels_smoke.gd`; `.github/workflows/gptfirst-check.yml` для изолированной проверки ветки.

## Изменённые общие файлы

- `server/game_server.py`: импорт статистики, два read-only вызова, две Bearer GET-маршрутизации и выбор PostgreSQL-обёрток.
- `server/postgres_world.py`: только две новые функции чтения.
- `client/world_screen.gd`: минимальные дополнения создания/раскладки панелей, меню и роутинга касаний.
- `.github/workflows/server-check.yml`: тесты `test_stats test_postgres_stats` добавлены в конец имеющегося списка.

Зона Grok, в том числе `contracts*.py` и контракты между игроками, не затрагивалась. `economy.py`, `production.py`, `bank.py`, `npc.py`, `clock.py`, `roads.py`, `world.gd`, `PROGRESS.md` не менялись.

## Фактически выполненные проверки

GitHub Actions, изолированный runner, запуск `43616813494`:
https://github.com/maillunex-lang/LunexEconom/actions/runs/43616813494

- `cd server && python -W ignore -m unittest discover -p 'test_*.py'`: **299 тестов, OK, 26 пропущено** (PostgreSQL наборы корректно skip в SQLite окружении).
- `cd ops && python -m unittest discover -p 'test_*.py'`: **28 тестов, OK**.
- PostgreSQL 16, только одноразовая `lunex_ci`: `cd server && python -W ignore -m unittest test_postgres_integration test_postgres_world_ci test_postgres_economy test_postgres_stats -v`: **26 тестов, OK**; схема создана с `postgres_db.init()` в CI.
- `godot --headless --path client --import`: **OK**, ошибок разбора скриптов нет.
- `godot --headless --path client --script res://tests/stats_panels_smoke.gd`: `STATS_PANELS_SMOKE_PASS`, **OK**, без обращения к боевому API.
- Тест HTTP API на localhost проверяет 401 без Bearer, успешные GET с проверенной тестовой личностью, 400 для неверного `by` и курсора.

Первый запуск CI `43616393137` нашёл ошибку временной метки в тесте и отсутствие init схемы PostgreSQL; обе ошибки исправлены, последующий полный прогон зелёный.

## Ограничения и риски

- Невозможно утверждать, что интерфейс испытан на физическом Android-устройстве. APK не собирали, реальный сетевой UX не проверяли.
- Тестовая PostgreSQL 16 `lunex_ci` не равна боевой БД; боевые данные не читались.
- Курсор ленты является смещением по детерминированной проекции из имеющихся источников, а не вечным монотонным ID. При появлении задним числом событий смещение может сдвинуться. Для строгой истории без пропусков позже понадобится отдельный событийный журнал или устойчивый композитный курсор.
- Оценка зданий для рейтинга основана на текущей фиксированной цене строительства, не на рыночной цене актива.
- Отчёт не обновляет `docs/PROGRESS.md`: журнал Claude остаётся без изменений.

Окончательный SHA после синхронизации `GPTFirst` со свежим `main` сообщается владельцу по итоговой проверке в этой беседе.
