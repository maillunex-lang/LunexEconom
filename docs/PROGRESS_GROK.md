# Журнал Grok (ветка GrokFirst)

## 2026-11-14 — контракты между игроками

Прямые сделки на мёд, нефть и товары мимо общего рынка. Суть из `docs/GROK_BRIEF.md` §6 не менялась, подтверждение владельца не ждал. Дизайн: [CONTRACTS.md](CONTRACTS.md).

Исполнение в `production.step_month` **до** очистки рынка: свой завод поставщика резервирует сырьё, остаток уходит покупателям в порядке `id` контракта, завод покупателя тратит поставку как своё сырьё. Деньги — после рыночных проводок месяца, прямой проводкой игрок→игрок (`kind=contract` и `kind=contract_penalty`). Неоплата — `trade_debts` и пропуск месяца по общим правилам банкротства. НДС и налог на прибыль с оборота контракта **не** берутся (иначе проводка шла бы через `system:market`). Пошлина расторжения = `penalty × qty` за один месяц, не за весь остаток срока. Продажа здания контракт не отменяет.

Пределы (только в `economy.py`): цена 50–200 % базовой, количество 1…10 000, срок 1…24 месяца, штраф 0…цены, не больше 6 открытых предложений и 6 активных контрактов (с обеих сторон). Нельзя с собой, с NPC и с городом.

### Новые файлы

- `server/contracts.py` — предложение, принятие, отмена, `plan_deliveries` / `deliver`, `settle`, `on_bankruptcy`, `view`.
- `server/test_contracts.py` — 17 тестов (арифметика, права, идемпотентность, лимиты, поставка, резерв своего завода, недопоставка, долг, банкротство, HTTP, симуляция с налогами и NPC).
- `docs/CONTRACTS.md` — модель, API, ошибки, клиент.
- `client/contracts_panel.gd` — кнопка «Контракты» и панель доски.
- `client/tests/contracts_panel_smoke.gd` — headless: панель скрыта, кнопка только в «Экономике», закрытие, скрытые кнопки не получают касание.

### Хуки в чужих файлах

- `server/economy.py` — константы `CONTRACT_*`, четыре таблицы в `SCHEMA` (`trade_offers`, `trade_contracts`, `trade_deliveries`, `trade_debts`), блок `contracts` в `terms()`. Ответы `/wallet` и `/market` не менялись.
- `server/postgres_db.py` — те же четыре таблицы в конце `SCHEMA`.
- `server/production.py` — `deliver()` до очистки продукта; `settle()` после процентов по кредиту и до `liquidate()`; `on_bankruptcy()` в конце `liquidate()`. Импорт локальный.
- `server/game_server.py` — `GET /contracts`, `POST /contracts/offer|accept|cancel` в `ECONOMY_POST`, обёртки команд. На PostgreSQL те же четыре функции перевязаны на `postgres_world`.
- `server/postgres_world.py` — те же обёртки с `pg_advisory_xact_lock` и `%s`.
- `server/test_postgres_economy.py` — один тест поставки (зона ChatGPT; иначе CI PostgreSQL его не увидит, `postgres-check.yml` не трогал).
- `.github/workflows/server-check.yml` — `test_contracts` в строке `unittest` (так требует бриф).
- `client/world_screen.gd` — загрузка панели, видимость кнопки только в «Экономике», скрытие при других разделах и каталоге, панель в `is_world_ui_point` и `_hit_ui_button`.

### Команды и результаты

SQLite, 2026-11-14, Python 3.10:

```
cd server && python -W ignore -m unittest discover -p 'test_*.py'
Ran 307 tests in 12.611s
OK (skipped=25)
```

25 пропущенных — модули PostgreSQL: в этом прогоне `LUNEX_DB_ENGINE` не задан. `test_contracts` (17) входит в 307 и зелёный.

```
cd ops && python -m unittest discover -p 'test_*.py'
Ran 28 tests in 0.015s
OK
```

Тест штампа версии напечатал `stamped versionCode=200 versionName=0.3.200` и не оставил грязных файлов.

PostgreSQL, одноразовая БД `lunex_ci` на `127.0.0.1:5433`, не боевая. Движок — **PostgreSQL 15.18** (пакеты Debian), не 16: в песочнице glibc 2.36, бинарник PostgreSQL 16 требует `GLIBC_2.38`, `apt` и официальные deb PG16 недоступны. Пароль только в окружении процесса, в репозиторий не записан.

```
cd server
export LUNEX_DB_ENGINE=postgres LUNEX_PG_HOST=127.0.0.1 LUNEX_PG_PORT=5433 \
  LUNEX_PG_DB=lunex_ci LUNEX_PG_USER=lunex_ci LUNEX_PG_PASSWORD=<локальный одноразовый>
python -c "import postgres_db; postgres_db.init()"
python -W ignore -m unittest test_postgres_integration test_postgres_world_ci test_postgres_economy
Ran 25 tests in 5.079s
OK
```

В том числе `test_player_contract_delivers_off_market_and_keeps_the_ledger_closed`: 20 мёда × 200 ₽, поставка (20, 0, 4000, 0), предложение рынка 80, спрос = потребительский, проводка покупателя −4000, статус `completed`, журнал сходится.

Клиент, Godot 4.7.2 headless (`ed1daf0bf`):

```
godot --headless --path client --import
```

Импорт завершился без `SCRIPT ERROR` (код 0). Полная проверка скрипта — загрузкой сцены. Первый прогон `client/tests/contracts_panel_smoke.gd` поймал parse error: `:=` не вывел тип у `get_parent()` и `get_viewport_rect().size`. Типы заданы явно. Повтор:

```
godot --headless --path client --script res://tests/contracts_panel_smoke.gd
CONTRACTS_PANEL_PASS hidden/economy-only/open/close/touch
```

Код 0, `SCRIPT ERROR` нет. На устройстве не запускалось.

Симуляция (`test_a_modest_contract_does_not_break_the_market_or_the_npcs`): налоги включены, ферма и завод игроков, контракт 10 мёда × 180 ₽ на 4 месяца, 6 вызовов `npc_tick`. Журнал сходится, все сохранённые цены внутри `MIN_PRICE_K`…`MAX_PRICE_K`, поставок ≥ 4 и объём > 0, зданий NPC > 0, контракт `completed`.

`origin/main` за время работы ушёл вперёд на два документа (`551acef` бриф ChatGPT, `4d68737` бриф Grok2). Перед отчётом ветка перебазирована на `origin/main`. В `main` не пушил, pull request не создавал.

### Не проверено

- Настоящий PostgreSQL 16. Локально 15.18; workflow `postgres-check.yml` по-прежнему гоняет `test_postgres_economy` на образе postgres:16, но этот CI на ветке я не запускал.
- Android-устройство, два игрока, FPS.
- Боевой сервер, VPS, секреты — не трогал.

### Риски

- Оборот контракта не входит в НДС и налог на прибыль. Журнал сходится, город с этой выручки ничего не получает.
- Пошлина отмены — один месяц `penalty × qty`. При `penalty = 0` расторжение бесплатное.
- Покупатель без зданий становится «пустой» компанией только если товар реально пришёл, и лишнее сразу продаёт на рынок.
- Компания-оболочка и перепродажа в том же месяце не облагаются налогом на прибыль с контрактной маржи.
- Расхождение PG 15.18 и CI PG 16 возможно, хотя SQL общий и тест паритета зелёный на 15.18.
