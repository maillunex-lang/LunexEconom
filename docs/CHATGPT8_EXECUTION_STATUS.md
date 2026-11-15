# ChatGPT8: проверяемый статус работ (2026-11-15)

Ветка: ChatGPT8. В main ничего не сливалось. Рабочая копия на Lunex: `/home/gamedev/projects/LunexEconom-chatgpt8-work`; не является производственным развертыванием.

## Реализовано
- `tools/validate_models.py`: офлайн GLB проверка и advisory список отсутствующих ID `city_catalog.CATALOG` и `game_server.KINDS` с расширениями `goods_catalog.extra_footprints()`.
- `tools/test_validate_models.py`: 5 unit tests, успешно на VPS.
- `.github/workflows/models-check.yml`: workflow создан, его запуск в GitHub ещё не подтверждён.
- `tools/build_models_blender.py`: процедурная генерация 11 дополнительных GLB, включая все 8 новых предприятий; `tools/models_build.json` обновлён.
- `docs/CHATGPT8_BALANCE_SUITE.md`: реальный прогон неизменённого `tools/balance_sim.py --suite` (8 сценариев, включая `agro_18` и `extract_18`).
- 5 прогонов по 72 месяца с seed 3, 7, 11, 20261114, 20261115. Без ботов и при одинаковом начальном состоянии все дали одинаковый digest `068181143fb84f58`, по 0 нарушений и флагов. Это не доказательство независимости от seed для иных стратегий.

## Непройденные проверки
- `validate_models.py` нашёл 4 старых несоответствующих файла: `factory.glb`, `farm.glb`, `mine.glb`, `oil_well.glb` (несколько материалов и отсутствие COLOR_0/NORMAL). Новые 11 моделей проходят валидатор; общий запуск 28 GLB: 4 FAIL.
- Отсутствуют модели 27 ID городского каталога. Отчёт advisory, но задача полного набора моделей не завершена.
- Godot headless импорт, Android визуальная QA, CI GitHub, нагрузочный HTTP тест и PostgreSQL конкурентность не подтверждены.

## Не выполнено
1. Остальные модели каталога, этапы строительства, транспорт/пешеходы и полный импорт.
2. Доработка валидатора до проверки transform и покрытие реального формата.
3. Сводные экономические метрики и сопоставление с коридорами `server/balance_targets.py`.
4. 200 пользователей через HTTP, `/catalog/goods`, `/deposits`, нефтяная скважина и ошибки `no_deposit`/`deposit_busy`, SQLite и отдельная тестовая PostgreSQL `lunex_ci`.
5. PostgreSQL тесты гонок биржи `server/exchange.py`.
6. Профилирование и оптимизация только `regions.overview`.
7. Health monitor, backup план и read-only вкладки «Товары» и «Месторождения».
8. Xvfb Godot скриншоты.

## Границы
`server/zoning.py`, `server/goods_catalog.py`, `server/deposits.py`, `tools/balance_sim.py` не менялись. Производственные БД, службы и VPS деплой не трогались. Изменения в `main` запрещены до отдельного разрешения. Статус: **не готово к слиянию**.
