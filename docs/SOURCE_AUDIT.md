# Инвентаризация исходников V2: первичный проход

> Дата: 2026-11-17. Проверены пути, наличие исходников и тестовых файлов. **Наличие тестового файла не означает успешный тест.**

## Таблица механизмов

| Механика | Исходники | Найденные тесты | Фактическая категория |
|---|---|---|---|
| Платформа и авторизация | `server/platform/` | `server/tests/test_platform_v201.py, test_security_refresh.py` | Серверный код; интеграция не перепроверена |
| Денежный журнал | `server/ledger/` | `server/tests/test_security_ledger.py` | Серверный код; интеграция не перепроверена |
| Часы и тики | `server/clock/` | `server/tests/test_platform_v201.py` | Серверный код; интеграция не перепроверена |
| Каталог товаров и рецептов | `server/catalog/, server/data/` | `server/tests/test_catalog_v2.py, test_catalog_chains_materials.py` | Серверный код; интеграция не перепроверена |
| Генерация мира и карта | `server/world/, client/world/` | `server/tests/test_world_generator.py, test_world_core.py, test_world_postgres.py` | Сервер и Godot-клиент; интеграция не перепроверена |
| Предприятия | `server/enterprises/, client/enterprises/` | `server/tests/test_enterprises_unit.py, test_enterprises_postgres.py` | Сервер и Godot-клиент; интеграция не перепроверена |
| Поставки | `server/supply/` | `server/tests/test_supply_math.py, test_supply_postgres.py` | Серверный код; интеграция не перепроверена |
| Рынок | `server/market/` | `server/tests/test_integration.py` | Серверный код; интеграция не перепроверена |
| Розница | `server/retail/` | `server/tests/test_retail_unit.py, test_retail_postgres.py` | Серверный код; интеграция не перепроверена |
| Режимы продаж | `server/sales/, tools/sim/sales/` | `server/tests/test_sales_math.py, tools/tests/test_sales_sim.py` | Серверный код; 7 тестов автономного симулятора прошли |
| AI-компании | `tools/sim/ai_engine/` | `tools/tests/test_ai_engine_sim.py` | Прототип симулятора, не подтверждён как серверная механика |
| Глубокие цепочки | `tools/sim/chains_deep/` | `tools/tests/test_deep_chains_sim.py` | Прототип симулятора |
| Кредиты | `tools/sim/credit/` | `tools/tests/test_credit_sim.py` | Прототип симулятора |
| Исследования | `tools/sim/rnd/` | `tools/tests/test_rnd_sim.py` | Прототип симулятора |
| Персонал | `tools/sim/staff/` | `tools/tests/test_staff_sim.py` | Прототип симулятора |
| Слои спроса | `tools/sim/demand_layers/` | `tools/tests/test_demand_sim.py` | Прототип симулятора |
| Объекты и управление | `tools/sim/objects/` | `tools/tests/test_objects_sim.py` | Прототип симулятора |
| Сценарии экономики | `tools/sim/engine.py, tools/sim/scenarios/` | `tools/tests/test_sim_invariants.py, test_sim_m2.py` | Эталонный симулятор; отдельно от игрового сервера |
| Android UI и карта | `client/screens/, client/ui/, client/world/` | `client/tests/` | Godot-код; Android smoke-тесты не запускались |
| Портал задач | `portal/` | `portal/tests/` | Отдельное приложение; не часть игрового ядра |

## Результаты расширенного прогона

- `python3 -m unittest discover -s tools/tests -p "test_*.py" -q`: **256 тестов, OK**, 2026-11-17. Проверка выполнялась в рабочем каталоге репозитория системным Python; не затрагивала боевую БД.
- `python3 -m unittest discover -s tools/tests -p "test_*sim.py" -q`: **63 теста, OK**. Эти 63 теста входят в полный прогон 256 и не суммируются с ним.
- Это подтверждает тесты инструментов и симуляторов, **но не готовность всех серверных модулей или Android-клиента**.

## Что запускалось

- `python3 -m unittest discover -s tools/tests -p 'test_sales_sim.py' -q`: **7 тестов, OK**.
- `python3 -m unittest server.tests.test_registry server.tests.test_sales_math server.tests.test_supply_math server.tests.test_world_core server.tests.test_world_generator server.tests.test_enterprises_unit server.tests.test_retail_unit -q`: **7 ошибок импорта**, причина: в системном Python отсутствует `psycopg`. Эти ошибки не классифицируются как дефекты механик.
- Godot smoke-тесты, PostgreSQL-интеграционные тесты, полная сборка Android и все остальные симуляторы в этом проходе не запускались.

## Как использовать

1. Выбери модуль в таблице, открой его исходники и тесты.
2. Проверь реальные API, импорты, настройки и границы данных.
3. Выполни тесты в **изолированном окружении** со всеми зависимостями, без подключения к боевой БД.
4. Для Godot отдельно проверь сцены, ресурсы, Android-совместимость и права на ассеты.
5. Перед переносом в новую игру составь минимальный список файлов и заменяемых связей.

## Не путать

- `tools/sim/*` часто является **эталонной моделью**, а не подключённым серверным модулем.
- `docs/gdd/*` фиксирует дизайн и намерения; статус реализации проверяется кодом.
- Наличие Python/GDScript и тестовых файлов **не гарантирует** готовности к повторному использованию.

## Следующая проверка

Полный прогон `tools/tests/` выполнен. Серверные тесты требуют отдельного окружения с `psycopg`; Android/Godot smoke-тесты не выполнялись по упрощённому процессу приёмки. Достаточно зелёной CI для документационного PR. Никаких правок боевого сервера для этого не требуется.
