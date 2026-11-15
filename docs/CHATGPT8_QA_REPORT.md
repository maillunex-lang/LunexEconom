# ChatGPT8: QA и ограничения (15.11.2026)

## Выполнено в изолированной рабочей копии
- Blender 5.0.1: 55 GLB файлов, 0 ошибок `tools/validate_models.py`, advisory missing 0. Четыре старых GLB `factory`, `farm`, `mine`, `oil_well` пересозданы с одним материалом и цветами вершин.
- 27 новых городских моделей являются **универсальными низкополигональными заглушками**, а не уникальными моделями каждого объекта. Они удовлетворяют формату и размеру участка, но художественная приемка нужна.
- `tools/test_validate_models.py`: 5/5.
- `admin_studio`: 38/38 unit tests после расширения покрытия каталога.
- `server`: 531 tests, 55 skipped, 0 failures.
- `ops`: 34 tests, 0 failures (до добавления health monitor); `ops/test_health_monitor.py`: 4/4.
- `tools/load_probe.py --players 200`: 200 виртуальных владельцев в **изолированной временной SQLite**. `reports/load_200.json`: 0 ошибок, 0 нарушений журнала, 0 суммарный баланс. Это вызовы Python обработчиков, **не HTTP** и не PostgreSQL.
- `tools/balance_sim.py --suite`: 8 сценариев, включая agro_18 и extract_18, 0 нарушений инвариантов. Отчёт в `docs/CHATGPT8_BALANCE_SUITE.md`.
- Студия: новые read-only вкладки «Товары» и «Месторождения», защищённые авторизацией, проксируют только GET на loopback upstream. Живой upstream не проверялся.

## Блокеры для завершения всех восьми задач
1. **Godot/Xvfb:** `/usr/local/bin/godot` указывает на отсутствующий `/opt/game-tools/godot/4.8-beta3/Godot_v4.8-beta3_linux.x86_64`. Godot import/screenshot не запускались. Не подменять согласованную beta стабильной версией без решения владельца.
2. **Нагрузка:** HTTP /catalog/goods, /deposits, build oil_well, no_deposit и deposit_busy; 200-player HTTP и изолированная PostgreSQL `lunex_ci` не выполнены. Производственную базу не использовать.
3. **Биржа:** конкурентные PostgreSQL тесты не выполнены.
4. **regions.overview:** профиль до/после и безопасная оптимизация не выполнены.
5. **Health:** `ops/health_monitor.py` только изолированный loopback read-only smoke; не включён в cron/systemd.
6. **Backups:** перед запуском PostgreSQL тестов создать отдельную базу `lunex_ci` с отдельной ролью; резервные копии с checksum, retention и restore drill исключительно тестового контура. Производственные службы и базы не трогать.
7. **CI:** локальные тесты выполнены, GitHub Actions и Android сборка не подтверждены.

## Режим
Работа только в ChatGPT8. Никаких изменений `server/zoning.py`, `server/goods_catalog.py`, `server/deposits.py`, `tools/balance_sim.py`. Нет разрешения на деплой или merge в main.