# Журнал Grok2two

Дата: 14.11.2026. Ветка `Grok2two` от `main` `a9bb74c`. В `main` не пушилось, pull request не создавался.

## Что сделано

Пункты брифа 1–10 (ядро 1–4, затем биржа, модерация, графики, достижения, рейтинг, симулятор).

1. **Альянсы.** Создание (имя 3–24, взнос `CREATE_FEE` = 50 000 ₽), поиск, заявки и приглашения, вход, выход, исключение, передача лидерства. Роли `leader` / `member`, не больше 8 человек, один альянс на игрока. Казна — счёт `alliance:<id>` через `economy.post`. Вывод только лидером. Роспуск делит казну поровну, остаток — лидеру. Имя после роспуска остаётся занятым (нормализация NFKC, без нулевой ширины, `casefold`).
2. **Проекты.** Лидер объявляет ферму, шахту, завод или склад. Стоимость — `roads.plan_access` и `economy.build_cost`, не копия правил карты. Вклады на `project:<id>`. При полной сумме здание ставит `soc_build.place` внутри уже открытой транзакции (отдельный `game_server.build` на PostgreSQL взял бы второй advisory lock и встал). Владелец здания — служебный `alliance:<id>`, кошелёк компании заранее нулевой, стартовый капитал не начисляется. Прибыль после налога месяца делится по `soc_shares`; округление и доля ушедшего — в казну; повтор месяца режется `soc_payouts`. Отмена до старта возвращает вклады. Клетка до оплаты не бронируется.
3. **Сообщения.** `POST /soc/message`, `GET /soc/inbox?after=`. До 300 символов, без `<` и `>`, 12 в минуту, последние 50 на диалог, чёрный список, в ответе только публичное имя. Клиент — `Label`.
4. **Клиент.** «Альянс», «Сообщения», «Звания» в «Меню»; «Биржа» и «Графики» в «Экономике». Окна через `panel_rect`, «Закрыть» вне прокрутки, тело в `ScrollContainer`, скрытая панель не берёт касание.
5. **Симулятор.** В `tools/balance_sim.py` добавлена стратегия `contract` и сценарий `contracts_24`. `docs/BALANCE_REPORT.md` не переписывался.
6. **Биржа.** `exchange.match_book` — чистая функция (цена, затем seq, затем id; без самосделки; частичное исполнение). Резерв товара у продажи и денег у покупки, комиссия 1% (0 при номинале < 100 ₽) в `player:city`. Продукты из `economy.MARKET`, коридор цены как у контрактов.
7. **Графики.** Только чтение `market_prices` и `population`. Ломаная в `client/price_chart.gd`, без библиотек.
8. **Достижения.** Без денег. Проверка при `GET /soc/achievements`, идемпотентно. Коды живут в `social.py`, не в `server/achievements.py`: отдельный модуль зациклил бы импорт с диспетчером. Таблица `soc_achievements` и адрес — как в брифе.
9. **Модерация.** Жалобы в `soc_reports` (5/час), аудит казны, лимиты в памяти процесса (40 действий/мин, 120/мин на IP), фильтр имён и текста, негативные тесты.
10. **Рейтинг альянсов.** `GET /soc/alliance-ranking?by=capital|activity|members`. `server/stats.py` не менялся. Служебная компания `alliance:<id>` может попасть в общий рейтинг компаний: `_is_company` такое имя пропускает.

Правила и таблица API — [ALLIANCES.md](ALLIANCES.md). `docs/ROADMAP.md` не отмечался: это общий файл, этап 0.8 закроет слияние.

## Общие файлы (только добавления)

- `server/game_server.py` — `import social`, схема, `_social_tick` после `npc_tick`, `soc_post` / `soc_get`, разбор `/soc/...`; на PostgreSQL функции подменяются на `postgres_world`.
- `server/postgres_world.py` — `soc_post` / `soc_get` под `pg_advisory_xact_lock(20261114)`; чтение графиков, стакана, списка, рейтинга и входящих — `READ ONLY`.
- `server/postgres_db.py` — `social.ensure` после схемы.
- `client/world_screen.gd` — кнопки, пять панелей, маршрутизатор касаний.
- `.github/workflows/server-check.yml` — `test_social test_exchange test_charts`.
- `.github/workflows/postgres-check.yml` — `test_postgres_social`.
- `tools/balance_sim.py` — стратегия `contract`.

Новые файлы: `server/social.py`, `server/soc_build.py`, `server/exchange.py`, `server/charts.py`, тесты `test_social.py`, `test_exchange.py`, `test_charts.py`, `test_postgres_social.py`, панели и смоуки клиента, `docs/ALLIANCES.md`.

## Проверки 14.11.2026

SQLite (боевая БД не использовалась):

```text
cd server && python -W ignore -m unittest discover -p 'test_*.py'
Ran 354 tests in 15.114s
OK (skipped=31)
```

Пропуски — postgres-тесты при движке SQLite.

```text
cd ops && python -m unittest discover -p 'test_*.py'
Ran 28 tests in 0.015s
OK

cd tools && python -W ignore -m unittest discover -p 'test_*.py'
Ran 11 tests in 4.141s
OK
```

PostgreSQL 16.16, одноразовая база `lunex_ci` на `127.0.0.1:15440`, пользователь `lunex`, пустой пароль (файл боевого пароля не читался):

```text
cd server && LUNEX_DB_ENGINE=postgres LUNEX_PG_HOST=127.0.0.1 LUNEX_PG_PORT=15440 \
  LUNEX_PG_DB=lunex_ci LUNEX_PG_USER=lunex LUNEX_PG_PASSWORD= \
  python -W ignore -m unittest test_postgres_social test_postgres_integration \
  test_postgres_world_ci test_postgres_economy test_postgres_stats
Ran 31 tests in 4.946s
OK
```

В `test_postgres_social` есть гонки: двойной вывод (201 и 402), двойной вход (201 и 409), проект и роспуск, частичное исполнение биржи, графики, достижения, рейтинг. Журнал в тестах сходится в 0.

Симулятор (отчёт баланса не перегенерировался):

```text
python tools/balance_sim.py --months 24 --seed 11 --strategies contract,contract --build-cap 4
months=24 digest=fcf32c9247166c84 invariants=0 flags=0 buildings=13 pop=214 honey=239 oil=1872 goods=2784 wallet_sum=0
```

`invariants=0` — список сломанных инвариантов пуст. Полный `--suite` не гонялся.

Godot 4.7.2:

```text
godot --headless --path client --import
```

Код 0. `SCRIPT ERROR` / `Parse Error` нет (есть постороннее `ERROR: Malformed message!` отладчика).

Смоуки зоны, код 0, в журнале нет `SCRIPT ERROR`:

- `alliance_panel_smoke.gd` — `ALLIANCE_PANEL_SMOKE_PASS`
- `messages_panel_smoke.gd` — `MESSAGES_PANEL_SMOKE_PASS`
- `exchange_panel_smoke.gd` — `EXCHANGE_PANEL_SMOKE_PASS`
- `charts_panel_smoke.gd` — `CHARTS_PANEL_SMOKE_PASS`
- `achievements_panel_smoke.gd` — `ACHIEVEMENTS_PANEL_SMOKE_PASS`
- `contracts_panel_smoke.gd`, `scroll_panels_smoke.gd`, `stats_panels_smoke.gd` — PASS

По пути починен разбор `client/price_chart.gd`: у координаты `y` не выводился тип (`values[i]` был Variant), из-за этого `charts_panel.gd` не создавался и каждый мир писал `SCRIPT ERROR`. Тип задан явно. Входящие в смоуке сообщений — 60 строк с минимальной высотой, иначе на viewport 1280×720 короткий список умещался без прокрутки.

Ещё зелёные, не из этой зоны: `chunk_renderer_smoke`, `updater_smoke`, `world_smoke`, `world_027_smoke`, `world_027_integration`.

## Что не проверено

- Реальный телефон и касания пальцем.
- Нагрузка и несколько процессов (лимиты частоты — память одного процесса, после рестарта пустые).
- Боевой VPS, боевая PostgreSQL и выкладка. Порт 15439 не открывался.
- Полный `--suite` симулятора и `docs/BALANCE_REPORT.md`.
- Старые смоуки `ui_main_menu`, `ui_v1_gestures`, `ui_v1_input`, `ui_v1_layout`, `ui_v1_smoke`, `ui_v1_touch_flow` ищут `BottomNavigation` / `BuildCatalog` прямым ребёнком корня. На `main` (`a9bb74c`) они уже дети `UIOverlay` (`world_screen.gd`, `_setup_build_toolbar`). `world_027_gui_click`, `world_027_touch_e2e`, `world_027_touch_fix` ищут `ConstructionToolbar`, которого в этой сцене нет. Ошибка не зовёт `quit()`, процесс обрывался по таймауту 50 с (код 124). Это не регрессия социальных панелей; файлы чужой зоны не менялись.

## Риски

- Участок проекта не держится до оплаты: если клетка занята в момент старта, деньги остаются на проекте до отмены.
- Имя распущенного альянса нельзя занять снова.
- Компания `alliance:<id>` может быть видна в рейтинге компаний.
- Дивиденд — прибыль минус налог этого месяца, не чаще одного раза; если кассы не хватает, платится только то, что есть.
- Жалобы только записываются, человек их не разбирает.
