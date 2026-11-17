# Карта исходников LunexEconom V2

| Подсистема | Исходники | Документы |
|---|---|---|
| Сервер и реестр | `server/game_server.py`, `server/registry.py`, `server/db.py` | `docs/ARCHITECTURE.md` |
| Деньги и транзакции | `server/ledger/` | `docs/platform.md` |
| Игровое время | `server/clock/` | `docs/spec/TIME_MODEL.md` |
| Каталог, товары, рецепты | `server/catalog/`, `server/data/` | `docs/catalog.md` |
| Мир, города, дороги | `server/world/`, `client/world/` | `docs/world.md` |
| Предприятия и производство | `server/enterprises/`, `client/enterprises/` | `docs/enterprises.md` |
| Рынок и поставки | `server/supply/`, `server/market/` | `docs/supply.md` |
| Розница и продажи | `server/retail/`, `server/sales/` | `docs/retail.md` |
| Android-клиент | `client/project.godot`, `client/screens/`, `client/ui/`, `client/theme/` | `docs/gdd/26_UI.md` |
| Изометрическая карта и 3D | `client/world/`, `client/models/` | `docs/gdd/22_MAP3D.md` |
| Авторизация | `server/auth.py`, `server/platform/`, `client/security/` | `docs/security.md` |
| Обновления | `client/update/`, `client/android_plugin/`, `tools/build_packs.py` | `docs/release.md` |
| Симуляторы и баланс | `tools/sim/`, `tools/balance/` | `docs/sim.md` |
| Проверки | `server/tests/`, `client/tests/`, `tools/tests/`, `.github/workflows/` | `docs/AI_RULES.md` |
| Лендинг | `web/` | `docs/web.md` |
| Админка | `web/admin/`, `admin_studio/` | `docs/admin.md` |
| Портал задач (отдельный) | `portal/` | `docs/PORTAL.md` |
| Деплой (отдельный) | `ops/` | `docs/OPERATIONS.md` |

**Зависимости:** серверные модули могут требовать реестр, миграции, PostgreSQL, журнал проводок и часы. Godot-сцены могут зависеть от autoload, `res://` ресурсов, API и тем. Проверяй импорты и тесты до копирования.

**Уровни готовности:** `docs/gdd/` содержит как реализованные, так и только спроектированные механики; `docs/proposals/`, `docs/research/`, `docs/mockups/` содержат эксперименты и макеты. Статус всегда подтверждается исходниками и проверками.
