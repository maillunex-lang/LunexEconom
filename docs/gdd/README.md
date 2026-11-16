# GDD (спецификация игры) V2

Пишет директор проекта (Claude). Исполнители ChatGPT реализуют по модулям и критериям приёмки из этих документов. Изменения в GDD вносит только директор по решению владельца.

| Документ | Модуль | Веха |
|---|---|---|
| [00_OVERVIEW.md](00_OVERVIEW.md) | обзор, время, порядок тика, вехи | — |
| [01_PLATFORM.md](01_PLATFORM.md) | платформа: аккаунты, учёт денег, часы и тик, настройки, админка | M1 |
| [02_WORLD.md](02_WORLD.md) | мир: города, карта, зоны, земля | M1 |
| [03_CATALOG.md](03_CATALOG.md) | каталог данных | M1 |
| [04_ENTERPRISES.md](04_ENTERPRISES.md) | предприятия и производство | M1 |
| [05_SUPPLY_MARKET.md](05_SUPPLY_MARKET.md) | поставки и рынок | M1 |
| [06_RETAIL.md](06_RETAIL.md) | розница | M1 |
| [17_ADMIN.md](17_ADMIN.md) | админка: панель управления игрой | M2–M3 |
| [18_CHAINS.md](18_CHAINS.md) | производственные цепочки | M2 |
| [19_CONTENT_PACKS.md](19_CONTENT_PACKS.md) | паки контента | M3 |
| [20_MONETIZATION.md](20_MONETIZATION.md) | монетизация (вариант A) | Beta |
| [21_AI_PLAYERS.md](21_AI_PLAYERS.md), [35_AI_ENGINE.md](35_AI_ENGINE.md) | ИИ-игроки: архетипы и движок решений | M2 |
| [22_MAP3D.md](22_MAP3D.md) | 3D-карта и события в реальном времени | M2–Beta |
| [23_REALESTATE.md](23_REALESTATE.md), [24_CITY_OBJECTS.md](24_CITY_OBJECTS.md), [25_RETAIL_REACH.md](25_RETAIL_REACH.md) | недвижимость, городские объекты, охват магазинов | M2 |
| [26_UI.md](26_UI.md), [30_UI_CAPLAB.md](30_UI_CAPLAB.md) | интерфейс клиента и экраны управления бизнесом | M2–M3 |
| [27_DEMAND.md](27_DEMAND.md) | слои населения и спрос | M2 |
| [28_SALES_MODES.md](28_SALES_MODES.md) | режимы продажи продукции | M2 |
| [29_DEEP_CHAINS.md](29_DEEP_CHAINS.md) | глубокие цепочки: рецепты, тара, побочные продукты | M3 |
| [31_OBJECT_MANAGEMENT.md](31_OBJECT_MANAGEMENT.md) | износ, улучшения, месторождения, автоматизация, отчёты | M2–M3 |
| [32_RND.md](32_RND.md), [33_STAFF.md](33_STAFF.md) | исследования и персонал | M3 |
| [34_CREDIT_TAX.md](34_CREDIT_TAX.md) | кредиты, налоги, отчётность | M2 |
| [36_BALANCE_BENCH.md](36_BALANCE_BENCH.md) | стенд баланса и методика пересмотра цен | M3 |
| [37_BRAND_ADS.md](37_BRAND_ADS.md), [38_STOCK_MARKET.md](38_STOCK_MARKET.md), [39_FOREIGN_TRADE.md](39_FOREIGN_TRADE.md), [40_WORLD_EVENTS.md](40_WORLD_EVENTS.md), [41_SCENARIOS.md](41_SCENARIOS.md) | бренд и реклама, биржа, внешняя торговля, события мира, сценарии | M3–Beta |
| [42_RELIABILITY.md](42_RELIABILITY.md) | нагрузка и надёжность | Beta |
| [43_LOGISTICS.md](43_LOGISTICS.md), [44_SERVICES.md](44_SERVICES.md) | логистика, услуги на месте | M3 |
| 07–16 | ранние предложения в [`../proposals/`](../proposals/) (основа для перечисленных выше) | — |

План работ и исполнителей: [../WORK_PLAN.md](../WORK_PLAN.md), [../PLAN_V2_CAPLAB.md](../PLAN_V2_CAPLAB.md).

Связанные документы: [../spec/](../spec/) (продукт, время, ядро экономики), [../CAPLAB_PARITY.md](../CAPLAB_PARITY.md) (объём беты).

## Утверждённые решения

- [DECISIONS_APPROVED.md](DECISIONS_APPROVED.md): решения владельца, обязательные для заданий (приоритет над `docs/proposals/`).
