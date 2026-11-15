# ChatGPT8: итог текущего проверочного прогона (15.11.2026)

## Подтверждено
- Ветка `ChatGPT8`, никаких изменений `main` и работающих служб.
- Blender 5.0.1 сгенерировал 55 GLB, `tools/validate_models.py`: 55 PASS, 0 FAIL, 0 missing catalog IDs.
- 4 старых GLB `factory.glb`, `farm.glb`, `mine.glb`, `oil_well.glb` исправлены.
- 27 моделей городского каталога сделаны как **универсальные процедурные заглушки**, не индивидуальные художественные модели.
- `tools`: 20 тестов, 1 skipped, 0 failures.
- `ops`: 38 тестов, 0 failures.
- `admin_studio`: 38 тестов, 0 failures.
- `server`: 531 тест, 55 skipped, 0 failures. После изменения `regions.overview` все 531 тест повторно пройдены.
- `regions.overview`: запросы цен по активным регионам заменены на одну пакетную выборку; **ускорение не измерено** и требует benchmark до/после.
- 200 владельцев в локальной временной SQLite через Python-обработчики: ошибок 0, баланс кошельков 0, нарушения проводок 0. Не HTTP.
- `balance_sim.py --suite`: 8 сценариев, инварианты 0; см. `docs/CHATGPT8_BALANCE_SUITE.md`.
- Studio read-only tabs «Товары» и «Месторождения»: серверный GET relay на loopback с авторизацией, bounds и ограничением ответа, локальные 38 тестов студии прошли. Live upstream не проверен.
- `ops/health_monitor.py`: read-only loopback check, 4 теста. Не включён в scheduler.

## Не завершено / не подтверждено
- Полный художественный набор (транспорт, этапы стройки, индивидуальные здания).
- HTTP нагрузка 200 пользователей и реальные проверки `/catalog/goods`, `/deposits`, `no_deposit`, `deposit_busy`.
- Отдельная PostgreSQL `lunex_ci`, конкурентные тесты биржи, проверка резервной копии и восстановления.
- Профилирование до/после `regions.overview`.
- Xvfb Godot скриншоты и Android import: `/usr/local/bin/godot` является сломанной ссылкой на отсутствующую 4.8-beta3.
- GitHub Actions CI не подтверждён.

**Решение: не сливать в main до завершения и устранения блокеров.**
