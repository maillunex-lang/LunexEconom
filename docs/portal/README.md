# GDD портала CreatePortal

Портал проектов: помогает владельцу создавать проекты, вести их по этапам, выдавать задания исполнителям (ИИ), принимать работу и хранить архив. Работает как личная «диспетчерская» для любого количества проектов (игра, сайт, приложение).

**Статус документов:** проект директора (2026-11-16), версия **v1 реализована в коде** (`portal/`), остальное проектируется здесь и ждёт утверждения владельца. Для каждой функции указан статус: **[v1]** сделано, **[v2]** ближайшая, **[v3]** позже.

| Документ | О чём |
|---|---|
| [00_OVERVIEW.md](00_OVERVIEW.md) | видение, пользователи, принципы, версии |
| [01_ACCOUNTS_SECURITY.md](01_ACCOUNTS_SECURITY.md) | вход, сессии, роли, безопасность |
| [02_PROJECTS_PLAN.md](02_PROJECTS_PLAN.md) | проекты, схема плана `work_plan.json`, линии, шаги, проверки |
| [03_BOARD_GTD.md](03_BOARD_GTD.md) | доска GTD, статусы, переходы, идеи, события |
| [04_PROMPTS_WIZARD.md](04_PROMPTS_WIZARD.md) | генерация промптов, мастер нового проекта, протокол для ИИ |
| [05_INTEGRATIONS.md](05_INTEGRATIONS.md) | GitHub (синхронизация, PR, CI, вебхуки), уведомления |
| [06_REPORTS_REVIEW.md](06_REPORTS_REVIEW.md) | отчёты исполнителей, приёмка, чек-листы, метрики |
| [07_UI_UX.md](07_UI_UX.md) | дизайн-система, экраны, подсказки, доступность |
| [08_DATA_API.md](08_DATA_API.md) | данные и маршруты API |
| [09_OPS_DEPLOY.md](09_OPS_DEPLOY.md) | развёртывание на VPS, резервные копии, мониторинг, обновления |
| [10_ROADMAP_ACCEPTANCE.md](10_ROADMAP_ACCEPTANCE.md) | версии, критерии приёмки, риски |
| [11_MOBILE_PWA.md](11_MOBILE_PWA.md) | управление со смартфона: PWA, APK, мобильный интерфейс |
| [DECISIONS.md](DECISIONS.md) | решения и вопросы владельцу |
| [mockups/](mockups/) | макеты экранов v2 (SVG) |

**План работ портала (активный):** [WORK_PLAN.md](WORK_PLAN.md), источник [work_plan.json](work_plan.json); команды `python tools/work_plan.py --plan docs/portal/work_plan.json next|prompt <id>|check|render`.

Код: [`portal/`](../../portal/), тесты `python -m unittest portal.tests.test_portal`, развёртывание: [`portal/DEPLOY.md`](../../portal/DEPLOY.md).
