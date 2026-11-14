# Журнал Grok1two — 2026-11-14

Ветка от `origin/main` `a9bb74c`. В `main` не сливалось. Пункты 4–6 брифа (новые отрасли, НИИ, экономические события) и пункт 7 (вклады) не делались.

## 1. Личные траты владельца

Доля **0,90** положительной прибыли после налогов уходит `player → system:market` (`owner_spend`), если месяц оплачен и на счёте больше резерва в **3 месяца** зарплат, сырья и обслуживания. Город не тратит. Таблица `eco_owner_spend`. Константы `OWNER_SPEND_*` в `economy.py`. Описание — `docs/OWNER_SPENDING.md`. В «Экономике» прогноз и строка «личные траты» в итоге месяца.

К 72-му месяцу одних NPC `system:market` −24,98 млн → **−18,06 млн**, деньги NPC 11,8 млн → **1,31 млн** (резерв, не мёртвый запас). Игрок `rot00` в `bots_72`: 16 зданий и 730 тыс. ₽. Остаток рынка — содержание, стройка и бюджет города, не невыплаченная прибыль. Подбор доли: 0,70/2 мес. оставлял пачку банкротств в `expand_48`, 1,00/4 мес. режет запас сильнее, чем нужно.

## 2. Лимит кредита новичка

Полный лимит по-прежнему 50 % залога. Новая компания получает 12 %. Остаток открывается произведением стажа / 12 мес. и средней выручки 3 месяцев / 20 000 ₽. Нужны оба. Экран показывает `limit_reason`. Описание — `docs/LOANS.md`.

`expand_48`: `mass_default` исчез. `credit_60`: флаг остался (месяц 4, три компании). Заводы куплены на стартовый миллион, не в кредит; списание было ~282 тыс. ₽ на компанию, стало 0. Клонов лимит не разводит. Тесты `test_bank.py` обновлены: старые сценарии зовут `mature()`, добавлена проверка «только стаж» и «только выручка».

## 3. Розница

Здание `shop` 2×2, 160 000 ₽, 5 мест, зал 100, наценка 30 %. Нет магазинов — жители платят рынку как раньше. Есть — маржа в выручке магазина, НДС 22 % как у товаров. NPC строит магазин, только если спрос не покрыт и окупаемость ≤ 14 мес. (в `npc_72` магазины появляются). Стратегия бота `shop` в симуляторе, сценарий `shop_36`, флагов нет. Клиент: пункт каталога, карточка, простая заготовка спрайта. Дизайн — `docs/RETAIL.md`.

## Общие файлы (только добавления)

- `server/game_server.py` — `shop` в `KINDS`, поле `retail` в `GET /market`
- `server/postgres_world.py` — то же
- `server/postgres_db.py` — таблица `eco_owner_spend`
- `server/production.py` — вызов `retail.apply` и `owner_spend.settle`, поля прогноза
- `client/world_screen.gd` — магазин в каталоге, строки трат, лимита и розницы
- `client/world.gd` — размер и тип `shop`
- `client/chunk_renderer.gd` — простая заготовка спрайта (зона ChatGPT; пункт 3 брифа просит читаемую форму)
- `.github/workflows/server-check.yml` — `test_owner_spend test_retail` в список
- `tools/balance_sim.py` — стратегия `shop` и сценарий `shop_36`
- `server/test_economy.py`, `test_settlement.py`, `test_tax.py`, `test_bank.py`, `test_postgres_economy.py` — под новое поведение

Новые файлы: `server/owner_spend.py`, `server/retail.py`, `server/test_owner_spend.py`, `server/test_retail.py`, `client/tests/retail_smoke.gd`, `docs/OWNER_SPENDING.md`, `docs/LOANS.md`, `docs/RETAIL.md`.

## Проверки

До (чистый `origin/main`, worktree `/tmp/lunex-main`):

`cd tools && python balance_sim.py --suite --out-dir /tmp/before --report /tmp/before/r.md`

инварианты 0; флаги: npc_72 0, bots_72 0, expand_48 `mass_default` месяц 6, credit_60 `mass_default` месяц 6. Рынок: −24,98 / −39,42 / −26,18 / −26,87 млн.

После:

`cd tools && python balance_sim.py --suite --out-dir /tmp/after-final --report /tmp/after-final/r.md`

инварианты 0; флаги: npc_72 0, bots_72 0, expand_48 **0**, credit_60 `mass_default` месяц 4, shop_36 0. Рынок: −18,06 / −27,39 / −19,24 / −15,53 / −10,14 млн. Длина месяца 86400 = 60 = 600. Шаг на 1000 зданий 17 мс.

`cd server && python -W ignore -m unittest discover -p 'test_*.py'` — **336 tests, OK, skipped 30** (повтор после переименования городского теста; PostgreSQL-тесты пропускаются: движка в песочнице нет).

`cd ops && python -m unittest discover -p 'test_*.py'` — **28 tests, OK**.

`cd tools && python -W ignore -m unittest discover -p 'test_*.py'` — **11 tests, OK**.

Godot 4.7.2.stable `--headless --path client --import` — без `SCRIPT ERROR`.

Смоуки (`timeout 25 godot --headless --path client --quit-after 8 --script …`, 2026-11-14):

Прошли: `chunk_renderer_smoke.gd` (`CHUNK_RENDERER_SMOKE_PASS`), `contracts_panel_smoke.gd`, `retail_smoke.gd` (`RETAIL_SMOKE_PASS`), `scroll_panels_smoke.gd`, `stats_panels_smoke.gd`, `updater_smoke.gd`, `world_027_integration.gd`, `world_027_smoke.gd`, `world_smoke.gd`.

Не прошли (те же `SCRIPT ERROR` на чистом `origin/main` `a9bb74c`, правка экономики их не создала): `ui_main_menu.gd`, `ui_v1_gestures.gd`, `ui_v1_input.gd`, `ui_v1_layout.gd`, `ui_v1_smoke.gd`, `ui_v1_touch_flow.gd` ищут `BottomNavigation` / `BuildCatalog` / `SectionPanel` прямым ребёнком `WorldScreen`, а узлы лежат в `UIOverlay`. `world_027_gui_click.gd`, `world_027_touch_e2e.gd`, `world_027_touch_fix.gd` ищут уже снятый `ConstructionToolbar`. Без `--quit-after` эти скрипты не вызывают `quit()` и висят. Не чинил: это не зона экономики и не регрессия пункта 3.


## Не проверено

- **PostgreSQL.** В песочнице нельзя сменить uid (`setgroups` / `chown` запрещены), `initdb` не стартует от root, apt тоже не может поднять службу. Боевую базу не открывал. Тесты `test_postgres_economy.py` (траты, магазин и НДС, лимит новичка) написаны и пропускаются без `LUNEX_DB_ENGINE=postgres` и `LUNEX_PG_DB=lunex_ci`. Их нужно прогнать на одноразовой `lunex_ci`.
- Android-устройство, боевой VPS, нагрузка.
- Пункты брифа 4–7.

## Риски

Остаток `system:market` всё ещё порядка −15…−27 млн ₽: это стоки содержания, стройки и городского бюджета. Доля 0,90 их не возвращает. `credit_60` по-прежнему с `mass_default`. Спрайт магазина в `chunk_renderer.gd` может конфликтовать с веткой ChatGPT — правка аддитивная, один `match`.
