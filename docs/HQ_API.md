# HQ API v1, серверный контракт ChatGPT11

Источник: `docs/HQ_SCREEN.md`. Клиент ChatGPT10 должен использовать **`server/hq_sample.json`** как офлайн-заглушку до объединения веток. API работает только с подтверждённой серверной сессией (`Authorization: Bearer ...`). Никогда не доверять имени владельца из запроса.

## `GET /hq`

HTTP 200: JSON с `version:1`, `server_time` (Unix seconds), `clock`, `company`, `money`, `enterprises`, `projects`, `finance`, `city`, `market`, `contracts`, `exchange`, `alerts`, `dev`. Нормативный пример, пригодный для тестовой загрузки, ниже. Дополнительные поля: `inventory`, `consolidated`, `profit_allocation`. Неназванные необязательные поля клиент игнорирует. Все деньги **целые игровые рубли**, не копейки и не строковые суммы. `rating` может быть `null`; `forecast_next_month` вычисляется существующим `production.forecast` (оценка при продаже всей продукции и покупке всех входных товаров) или остаётся `null`, если данных нет. Ошибка авторизации: 401 `{"error":"unauthorized"}`.

```json
{
  "version": 1, "server_time": 1800000000,
  "clock": {"month_index": 0, "year": 2027, "month": 1, "day": 1, "seconds_to_next_month": 86400},
  "company": {"owner": "demo", "name": "demo", "rating": null, "founded_month": 0},
  "money": {"cash": 0, "income_month": 0, "expenses_month": 0, "profit_month": 0, "forecast_next_month": null},
  "enterprises": [], "projects": [],
  "finance": {"loans": [], "arrears": 0, "taxes_due": 0, "next_payments": [], "credit_available": 0},
  "city": {"id": "ufa", "name": "Уфа", "population": 0, "rating": null, "budget": 0, "mayor": ""},
  "market": [], "contracts": {"active": 0, "open": 0}, "exchange": {"open_orders": 0},
  "alerts": [], "dev": false,
  "inventory": {}, "consolidated": {"assets": 0, "debts": {"loans": 0, "arrears": 0, "taxes": 0}, "subsidiaries": 0},
  "profit_allocation": "estimated_by_reference_cost"
}
```

Файл `server/hq_sample.json` сгенерирован на изолированной пустой SQLite-базе и сравнивается по полям/типам контрактным тестом `server/test_hq_api.py`. На реальных данных элементы `enterprises[]` содержат `id`, `kind`, `name`, `city`, `x`, `y`, `w`, `h`, `status`, `construction_stage`, `profit_month`, `jobs`, `staffing`, `stock`, `alerts`. Каждое оповещение: `level` (`info`, `warning`, `critical`), `code`, `text`, `object_id`, `x`, `y`.

**Важная граница точности.** Действующая экономика хранит `company_reports` и `inventory` **на уровне владельца**, а не здания. Поэтому прибыль предприятия в HQ приблизительно распределяется по доле оценочной стоимости здания, обозначена `profit_allocation=estimated_by_reference_cost`. Склад `enterprises[].stock` пока пуст: правдивый итог владельца находится в `inventory` верхнего уровня. История `/enterprise` обозначена `accounting_scope=company`. Не выдавать их за точную раздельную бухгалтерию. Рейтинг компании и прогноз оставляются `null` при отсутствии подтверждённых значений.

Максимальный HTTP JSON: 64 КиБ (=65 536 байт UTF-8). Срез списка предприятий до 180, рынка до 20, оповещений до 40; при переполнении срезаем до 60/30/20, иначе 413 `hq_too_large`. Кэш в памяти процесса на 4 секунды, ключ авторизованного владельца + движок + БД, сбрасывается при изменении настроек. Клиент обновляет не чаще 15 секунд и прекращает опрос в фоне согласно `HQ_SCREEN.md`.

## Смежные маршруты

- `GET /enterprise?id=<building_id>`: подробности своего объекта (рецепт, настройки цены, общий склад и история компании). 403 чужой объект, 404 отсутствует.
- `POST /enterprise/settings`: JSON `{ "id":"<building_id>","name":"Мельница","price_rule":"market|manual|reference","price":123,"min_stock":{"grain":100},"buy_limit":10000,"auto_managers":{"finance":{"enabled":false}} }`. Поля могут подаваться частично. `buy_limit` в целых рублях; параметры хранятся безопасно, но **до подключения производственной логики ещё не изменяют клиринговую цену и автозакупки**.
- `GET /finance/overview`: `cash`, `profit_month`, `reports`, `assets`, `net_assets`, `debts`, `payments`, `forecast_next_month`, `subsidiaries`. Внутренние переводы дочерних счетов не считаются прибылью.

Новые маршруты не требуют действий со стороны клиента карты; `game_server.py` только подключает маршрутизатор.

## Производительность и приёмка

Воспроизводимый замер: `cd server && python hq_benchmark.py`. На VPS Lunex, Python 3.14 внутри существующего проектного venv, **изолированная SQLite** с 20 географическими городами и 200 владельцами, по одному предприятию: 200 последовательных некэшированных `GET /hq`-вычислений за один открытый коннект. p50 **0.752 мс**, p95 **0.875 мс**, максимум **1.525 мс**; размер ответа максимум **1 041 байт**. Это замер сериализации/SQL самого обработчика, **не сетевой HTTP-бенчмарк и не нагрузка 200 одновременных пользователей**. Нужна отдельная нагрузка на PostgreSQL после объединения, пока одновременные запросы не измерялись.

SQLite: `test_hq_api.py`, `test_holding.py`, `test_auto_managers.py`, `test_alerts.py`, `test_terrain_parity.py`, `test_devtools_ex14.py`; PostgreSQL: `test_postgres_hq.py`, запускается исключительно при `LUNEX_DB_ENGINE=postgres` и `LUNEX_PG_DB=lunex_ci`. Блок недоделок: пять неактивированных стратегий менеджеров и полноценная финансовая автоматизация, операционная бухгалтерия дочерних компаний, почасовая бухгалтерия, рейтинг компании и более точный прогноз, событие завершения строительства в текущем HQ.