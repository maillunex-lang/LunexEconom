# PROGRESS_CHATGPT2 · ветка ChatGPTTwo

## 2026-11-14 · Раунд 3, изолированная реализация пунктов 1–12

**Рабочее место:** `/home/gamedev/workspaces/lunexeconom-chatgpttwo` на VPS Lunex. Клонировано отдельно от рабочих проектов; никакие игровые службы, nginx, производственная PostgreSQL или каталоги остальных проектов не изменялись. Ветка только `ChatGPTTwo`, без PR или слияния с `main`. Выполнен `git fetch origin main` и `git rebase origin/main`; после коммита перепроверять свежесть.

**Тестовая база:** отдельный PostgreSQL 16 в одноразовом Docker-контейнере `lunex-ci-chatgpttwo`, база исключительно `lunex_ci`, loopback `127.0.0.1:15547`. Пароль только в отдельном локальном файле с правами владельца, не в журнале и не в Git. Контейнер удалить после финальной верификации.

### 1. Версия сервера в `/health`

- Изменение общего `server/game_server.py`: локальный файл `LUNEX_DEPLOYED_SHA_FILE` (по умолчанию /var/lib/lunexeconom-server-update/deployed-sha), формат 40 hex → первые 12, нет файла/неверен → `null`. Пути не возвращаются наружу.
- Новые `server/test_health_deployed_sha.py` и адаптация существующего `server/test_health_ops.py`. **6 тестов пройдены**.

### 2. Миграции PostgreSQL (BE-004)

- `server/migrate.py`, `server/migrations/001_baseline.sql`, `server/test_postgres_migrations.py`, `docs/MIGRATIONS.md`.
- Версии, имя, timestamp, SHA-256 checksum, блокировка и отказ при несовпадении контрольной суммы. Полный набор старых таблиц распознаётся и маркируется как baseline **без изменения данных**, частичный набор отклоняется; пустая схема создаётся. Новые таблицы соседних веток не удаляются.
- Автомиграция в `game_server.py` только при `LUNEX_AUTO_MIGRATE=1`. Исходный `postgres_db.SCHEMA` и вызовы старого `postgres_db.init()` оставлены.
- **5 тестов PostgreSQL пройдены**; реальный CLI на `lunex_ci`: `python server/migrate.py status` (legacy baseline обнаружен), `up` (версия 001 применена), повторный `up` (`applied_now=[]`), `status` (`pending=[]`). Откат для production только из резервной копии, команд `down` нет.

### 3. Письма SMTP

- `server/ops_email.py`, небольшая интеграция в `server/auth.py`, тесты `server/test_ops_email.py`, `docs/EMAIL.md`.
- SMTP через env, STARTTLS для 587 или SSL для 465, локальный plaintext разрешён исключительно для фиктивного localhost-сервера. При отсутствии настроек прежнее безотправочное поведение. Доставка не блокирует регистрацию; при ошибке не раскрывается наличие учётной записи. Письма только plain text.
- Защита от спама: не более 5 обращений/час на адрес, 20/час на IP и пауза 60 секунд; hashed ключи в `ops_email_throttle`, SQLite и PostgreSQL, включая запросы несуществующих адресов.
- **12 auth-тестов + 6 SMTP/SQLite тестов + PostgreSQL тест лимита** пройдены. Локальный фиктивный SMTP получил письмо; реальный внешний SMTP не проверялся. Коды и SMTP-учётные данные не записывались в репозиторий.

### 4. Онбординг Android

- `client/tutorial.gd`, `client/tests/tutorial_smoke.gd`, аддитивные хуки в `client/world_screen.gd`.
- Четыре этапа: постройка фермы, Экономика, Город, Контракты; «Пропустить», `user://` состояние по SHA-256 имени аккаунта, реальные события и успешное серверное строительство для первого шага; игра не блокируется.
- **`TUTORIAL_SMOKE_PASS`** в Godot 4.7.2: порядок событий, сохранение, пропуск, независимость аккаунтов.

### 5. Внешняя проверка маршрутов

- `ops/check_api_routes.py`, `ops/test_check_api_routes.py`, новый manual `.github/workflows/api-routes-check.yml` и дополнение к `docs/NGINX_API_ROUTES.md`.
- AST извлекает маршруты из `server/game_server.py`, включая GET/POST и economy-POST. Безопасный POST с пустым телом, ожидаем JSON-ошибку и ничего не создаём. HTML-404 nginx фиксируется как ошибка.
- **6 tests OK**. Реальный публичный опрос `https://rikagro.ru/lunexeconom/api` до появления новых географических маршрутов: **30 из 30 PASS, 0 HTML-404**.

### 6–7. Города, регионы и трассы

- `server/geo.py`, только функции без БД. 20 игровых регионов с центрами по городам Башкортостана; Уфа в (0,0), масштаб 3 клетки/км, соседняя сухая клетка при конфликте с водой; до 27 фоновых трасс по суше, остовное дерево + дополнительные соединения, A*. Ни `roads.py`, ни `world.gd`, ни игровые правила строительства не изменены.
- Открытые `GET /geo/regions`, `/geo/cities`, `/geo/routes`, JSON с часовым кешированием. Тест Уфа–Стерлитамак: **124,4 км по прямой**, 27 трасс, все на суше и связны.
- **5 server/test_geo.py пройдены**, включая настоящий localhost HTTP (не продакшн).

### 8–9. Карта и детерминированные города

- `client/regional_map_panel.gd`, `regional_map_canvas.gd`, `city_layout.gd`, аддитивная отрисовка в `chunk_renderer.gd`.
- Экран карты, отдельная карточка города, переход камеры, pan и pinch, безопасная раскладка, кэш через `user://`, сообщение об ошибке сети, дороги и фоновая застройка с LOD. Прежние постройки и дороги рисуются поверх. Удалённые и невидимые чанки не перерисовываются ради фона.
- **`REGIONAL_MAP_SMOKE_PASS`**, включая выбор, масштаб, переход, обновление экрана 846×388, адрес участка; **`CITY_LAYOUT_SMOKE_PASS`**, включая повторяемость и отсутствие наложений на существующие дороги и воду.

### 10–11. Названия и справочное население

- Детеминированные `geo.streets` и `geo.plot_address`, без дублирования названий в городе. В карточку участка добавлен формат «Участок: Уфа, ул. …, x:y», если получены геоданные.
- `geo.population` даёт мягкий справочный рост/спад вне экономики, в API передан месячный коэффициент; клиент рассчитывает оценку для карточки города. Не тронуты `production.py`, `economy.py`, `city.py`.
- Проверены тестами `test_geo` и смоуком карты. Реальные адреса или демографический прогноз не утверждаются.

### 12. Сезоны, FPS

- `client/season_visual.gd`, `client/perf_overlay.gd`, кнопки в меню, локальное сохранение отключённых сезонов.
- Окраска зависит от игрового месяца сервера. FPS-панель показывает FPS, processing ms, активные чанки, видимые города и накопленную стоимость их перерисовки. `docs/device-tests/headless-2026-11-14.md` честно фиксирует ограничение VPS/headless.
- **`SEASON_AND_PERF_SMOKE_PASS`**. Испытания GPU/температуры/реального FPS на Android НЕ проводились.

## Финальный набор тестов по ROUND3.md §6

| Команда / среда | Результат |
|---|---|
| `cd server && python -W ignore -m unittest discover -p 'test_*.py'` без PG env | **342 tests, OK, skipped=32** (PG-dependent) |
| `cd ops && python -m unittest discover -p 'test_*.py'` | **34 tests, OK** |
| `cd tools && python -W ignore -m unittest discover -p 'test_*.py'` | **11 tests, OK** |
| `cd server && python -W ignore -m unittest -v test_postgres_integration test_postgres_world_ci test_postgres_economy test_postgres_stats test_postgres_migrations` на disposable `lunex_ci` | **32 tests, OK** |
| Godot 4.7.2 `--headless --path client --import` | **exit 0, SCRIPT ERROR 0** |
| Все `client/tests/*.gd`, каждый с `timeout 30` | **11 чистых PASS, 10 проблемных** |

### Известная проблема исходного `main`

Девять старых скриптов `ui_v1_*.gd`/ `ui_main_menu.gd`/ `world_027_*touch*.gd` ждут `BottomNavigation`, `BuildCatalog`, `ConstructionToolbar` непосредственно в корне сцены, хотя в `main` панели давно живут внутри `UIOverlay`. В чистой копии `origin/main` `ui_main_menu.gd` воспроизвёл ту же ошибку и таймаут. Эти девять старых сценариев завершаются таймаутом после ERROR; запрещено выдавать их за зелёные. Десятый, `updater_smoke.gd`, выводит `UPDATER_SMOKE_PASS` и exit 0, но Godot завершает процесс с `ERROR: 1 resources still in use at exit`; на чистом `origin/main` поведение **такое же**. Старые тесты и чужие ветки не изменялись, требуется отдельное согласование зоны ответственности.

**Не проверено:** реальный SMTP-провайдер, настоящая Android-карта/касания/safe areas/FPS, развёртывание гео-API на производственном сервере (строго запрещено брифом до слияния владельцем), общая CI на GitHub по новой ветке, full green legacy Godot smokes. Не объявлять релиз завершённым.

**Изменённые общие файлы:** `server/game_server.py`, `client/world_screen.gd`. Дополнен существующий `docs/NGINX_API_ROUTES.md`; остальные изменения в собственной зоне или новые файлы. Общие `postgres_db.py`, `postgres_world.py`, `ROADMAP.md`, `server-check.yml` не изменялись.

**Следующее действие:** сверить CI и результаты после финального коммита, обновить SHA ветки `ChatGPTTwo`, передать Claude на слияние по команде владельца. Боевой деплой не производить из ветки.
