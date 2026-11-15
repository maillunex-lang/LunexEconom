# ChatGPT8: проверка HTTP и PostgreSQL (15.11.2026)

## Реально выполнено на VPS, только в изоляции
1. `tools/http_isolated_probe.py`: одноразовый HTTP сервер на 127.0.0.1 с временной SQLite. 200 запросов, 16 рабочих потоков, **200/200 HTTP 200, 0 ошибок**, p50 **5.12 мс**, p95 **72.11 мс**. Проверены /health, /catalog/goods, /deposits. **Это 200 запросов при максимуме 16 одновременных работников, не 200 одновременных подключений и не 200 аутентифицированных игроков**.
2. Изолированный Docker `lunex-chatgpt8-pg-ci` (PostgreSQL 16), база `lunex_ci`, только loopback порт 15499, без production volume. Миграции **001–004** применены.
3. `tools/postgres_ci_concurrency.py`: два одновременных запроса продажи одного запаса (10 honey). Коды **201 и 409**, остаток склада **0**, резерв заявки **10**, незакрытых проводок **0**. Транзакционная advisory lock сработала. Тест не доказывает отсутствие всех возможных race conditions.
4. Backup/restore drill: `pg_dump -Fc` тестовой базы, SHA256 `509a6fea9d757ae92767e122f5919937ef9f4d133d901d789ae056e5174b6f5a`, `pg_restore` в `lunex_ci_restore`, SELECT COUNT(*) FROM soc_orders вернул **1**. Это проверка тестовой базы, не production.
5. Контейнер тестового PostgreSQL **удалён после проверок**. Рабочий `lunexeconom-postgres` и другие контейнеры не менялись.
6. `tools/validate_models.py`: **55/55 PASS**, missing 0. `tools` unit tests: 20, 1 skipped, 0 failures.

## Ещё не закрыто
- Нагрузка 200 *одновременно авторизованных* HTTP игроков с транзакциями; отдельные HTTP кейсы oil_well/no_deposit/deposit_busy.
- Сценарий конкурентных покупок/продаж PostgreSQL с большим количеством участников.
- Benchmark regions.overview до/после с отчётом p50/p95 и EXPLAIN.
- Godot Xvfb screenshot (импорт уже успешен).
- Уникальные модели транспорта, этапы строительства и художественная приемка городских заглушек.
- Удалённый CI workflow не подтверждён.

Не сливать в main до завершения полного объёма.
