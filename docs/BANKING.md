# Банки и финансы (EX-09)

Старый револьверный кредит (`server/bank.py`, таблица `loans`, команды `POST /loan`) не менялся. NPC-банки пишут в `bank_npc_loans`. Пока `BANKS_ENABLED` выключен, `POST /bank/loan`, `/bank/repay` и `/shares/buy` отвечают 409 `banks_disabled` и ничего не проводят. Месяц при выключенных `BANKS_ENABLED`, `INFLATION_ENABLED` и `TAX_EXTRAS_ENABLED` выходит до первой записи.

Все суммы — целые рубли. Одна проводка `economy.post` на перевод, сумма ног 0. Идемпотентность команд — `commands(owner, request_id)`; повтор того же UUID возвращает 200 и прежнее тело, вторая проводка не создаётся. Неуспешный запрос `request_id` не занимает.

## Банки

| id | Название | Политика | Надбавка к базе | LTV | Продукты |
|---|---|---|---:|---:|---|
| `bashkredit` | Башкредит | conservative | +2 п.п. | 0,50 | оборотный, ипотека |
| `agroprombank` | Агропромбанк | agro | −1 п.п. | 0,65 | оборотный, инвестиционный, кредитная линия |
| `uralinvest` | Уралинвест | investment | +4 п.п. | 0,55 | инвестиционный, кредитная линия |

Счёт банка: `system:bank:<id>`. Выдача делает его отрицательным, заёмщика — положительным (так же, как `system:bank` в старом кредите: деньги кредита создаются парой проводок).

Ставка:

```text
ставка = BANK_BASE_RATE_YEAR + надбавка банка + риск + надбавка залога [− 1 п.п. агробанку, если у заёмщика агроздание]
риск = min(0,20, просрочки_компании * BANK_RISK_STEP)
```

Просрочки компании читаются из `company_status.missed` (та же колонка, что у производства), не из таблицы `loans`. Ставка зажимается в **5–40 %** годовых (`BANK_RATE_MIN_YEAR`, `BANK_RATE_MAX_YEAR`) — коридор `loan_rate_year`.

Надбавка залога: недвижимость 0, оборудование +1 п.п., транспорт +1,5 п.п., запасы +3 п.п.

Оценка залога:

- `realty` — стоимость зданий, как `bank.appraisal` (строительная цена);
- `equipment` — `(equipment_level - 1) * EQUIPMENT_COLLATERAL` (40 000 ₽ за уровень сверх первого);
- `transport` — число грузовиков × `TRUCK_PRICE`;
- `inventory` — количество × справочная цена × `INVENTORY_LIQUIDATION_RATE`.

Лимит = оценка × LTV банка. Сумма ниже `LOAN_MIN` или выше лимита не выдаётся.

Срок: оборотный и кредитная линия 12 месяцев, инвестиционный 60, ипотека `MORTGAGE_TERM_MONTHS` (240). Платёж — аннуитет; у кредитной линии платёж равен процентам за месяц (тело гасится отдельно, через `POST /bank/repay`).

### Просрочка

Раз в месяц, идемпотентно по `(loan_id, month_index)`:

- есть деньги — платёж уходит банку, просрочка сбрасывается;
- денег нет — процент капитализируется в тело (без новой эмиссии), `missed` растёт;
- `missed >= BANK_MISSED_WARN` (1) — статус `warning`;
- `missed >= BANK_MISSED_RESTRUCTURE` (2) — один раз статус `restructured`, срок длиннее, платёж пересчитан;
- `missed >= BANK_MISSED_FORECLOSE` (4) — статус `defaulted`. Взыскание — минимум из остатка долга, живых денег заёмщика и `collateral * LIQUIDATION_RATE`. Если денег нет, проводки нет: долг остаётся `defaulted`, журнал не рвётся. Здания при взыскании **не сносятся** (это чужая зона).

Сценарий `credit_boom` (`CREDIT_BOOM=1` вместе с `BANKS_ENABLED`) один раз выдаёт `LOAN_MIN` оборотных Башкредитом первой компании с достаточным залогом. Повторного бума нет (`bank_marks`).

## Доли и дивиденды

`POST /shares/buy`: `{company, shares, price, request_id}`. Покупатель платит компании `shares * price` (`player:<holder>` → `player:<company>`). Компания не получает стартовый капитал от этой проводки. Себе и городу (`city`) купить нельзя.

Раз в месяц, если у компании есть доли и остаток выше `DIVIDEND_MIN_CASH` (100 000): выплачивается `DIVIDEND_PAYOUT_PPM` (100 = 10 %) превышения, пропорционально паям. Идемпотентно по `(company, month_index)`. Нет паёв — месяц банков ничего не платит.

## Инфляция

`server/inflation.py`. Индекс **наблюдаемый**: корзина мёда, нефти и товаров (цена месяца / справочная) и давление денежной массы (кошельки `player:*` плюс `system:residents` против прошлого месяца). Веса `INFLATION_PRICE_WEIGHT` 0,85 и `INFLATION_MONEY_WEIGHT` 0,15. Годовая ставка зажимается в **0–10 %** (`INFLATION_MIN_YEAR`, `INFLATION_MAX_YEAR`), даже если корзина на потолке 2,5×. `INFLATION_SHOCK=1` добавляет 4 п.п. до того же потолка.

Клиринговые цены не переписываются. При выключенном флаге строк нет. Идемпотентность — `inflation_index.month_index`.

## Налоги

Уже живут в реестре и собираются `taxes.py` без изменений: прибыль `DEFAULT_PROFIT_TAX`, НДС `VAT_STANDARD`, имущество `DEFAULT_PROPERTY_TAX`.

Новые, тоже в реестре, **не зашиты** в код ставкой: `LAND_TAX` (0,003 в год от оценки зданий / 12), `PAYROLL_TAX` (0,15 от рабочих мест × `BASE_WAGE`), `SECTOR_FEE` (0,01 от выручки месяца). Проводятся только при `TAX_EXTRAS_ENABLED` (по умолчанию выключен), с компании на `player:city`, не больше живых денег компании, один раз на `(owner, month_index)`. Сводка ставок: `banking.tax_rates()`.

## API

`GET /bank/offers` — публично. Если запрос с `Bearer`, лимиты считаются по залогам этого игрока.

`GET /bank/loans` — только со своим токеном, иначе 401.

`GET /inflation` — публично. Без строк: `rate_year` 0, `index` 1, `enabled` false.

`POST /bank/loan`, `POST /bank/repay`, `POST /shares/buy` — токен, тело JSON, общий замок месяца (`_player_command`).

Пример выдачи:

```json
POST /bank/loan
{"bank": "bashkredit", "product": "working_capital", "collateral": "realty", "amount": 10000, "request_id": "2f1c0e3a-7b14-4d0a-9c11-6a0e5d4c3b21"}
```

```json
201
{"ok": true, "loan_id": "…", "bank": "bashkredit", "product": "working_capital", "amount": 10000, "payment": 898, "rate_year": 0.14, "term_months": 12, "collateral": "realty", "balance": 1010000}
```

`rate_year` 0,14 — база 0,12 плюс 0,02 консервативного банка, залог недвижимость, просрочек нет. `payment` 898 — аннуитет на 12 месяцев. `balance` в примере — стартовый капитал 1 000 000 плюс тело кредита, если кошелёк ещё ничего не тратил; после стройки касса меньше. Повтор того же `request_id` — 200 и то же тело.

Погашение:

```json
POST /bank/repay
{"loan_id": "…", "amount": 10000, "request_id": "…uuid…"}
```

`amount` можно не передавать: спишется размер планового платежа, но не больше остатка и не больше кассы. Не хватает денег — 402 `insufficient_funds`. Чужой или неизвестный кредит — 404 `unknown_loan`.

Доля:

```json
POST /shares/buy
{"company": "acme", "shares": 10, "price": 1000, "request_id": "…uuid…"}
```

Ошибки: `unknown_bank`, `product_not_offered`, `unknown_collateral`, `invalid_amount`, `insufficient_collateral` (в теле есть `limit`), `invalid_request_id`, `invalid_company`, `banks_disabled`.

`GET /inflation` после месяца с флагом:

```json
{"enabled": true, "month": 0, "basket": 1.0, "money_pressure": 0.0, "rate_year": 0.0, "index": 1.0, "circulation": 0, "corridor": [0.0, 0.1]}
```

## Таблицы

`bank_npc_loans`, `bank_npc_charges`, `company_shares`, `dividend_paid`, `bank_marks`, `tax_extra_posted`, `inflation_index`. Функция `banking.ensure` / `inflation.ensure`, вызов из `households.ensure`, а тот — одной строкой из `game_server._prepare` и `postgres_db.init`. В `SCHEMA` не добавлялись.

## Сценарии симулятора

`housing_shortage`, `credit_boom`, `recession`, `inflation_shock` — 12 месяцев, NPC, seed 20261114. Флаги ставятся только на время прогона и снимаются. Инварианты 0, красных флагов нет. `inflation_shock` не трогает кошельки и цены: отпечаток совпадает с прогоном без флагов. Остальные три отпечаток меняют (сдвиг спроса на ±2 %, аренда из зарплат жителей, разовый кредит бума) и журнал при этом сходится.

## Не сделано

- Кабинет банка в клиенте штаба.
- Взыскание не забирает здание и не продаёт его с молотка — только живые деньги в пределах ликвидационной стоимости залога.
- Доп. налоги не вшиты в `taxes.rates()`: мэр по-прежнему крутит прибыль и имущество, земля/ФОТ/сбор включаются отдельным флагом.
- Боевая PostgreSQL не использовалась. Тесты `test_postgres_population` и `test_postgres_banking` пропускаются без `lunex_ci`.
