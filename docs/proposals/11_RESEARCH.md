# Предложение 11. Исследования и технологии (полная спецификация)

**Цель:** дать игроку возможность повышать технологический уровень рецептов из каталога, открывать новые рецепты и здания, учитывать устаревание, патенты и лицензии. Все влияет на производство (04) и рейтинг качества (06).

Все расчёты только по `docs/proposals/INTEGER_MATH.md`. Никаких float, логарифмов, 1e6. Счета не уходят в минус.

## Сущности и данные

### tech_levels
- recipe_id: строка (из recipes.json)
- company_id: целое
- level: целое 1–5
- efficiency_‰: целое 500–1500 (база 1000)
- last_research_month: целое (month_index)

Индекс: (company_id, recipe_id) уникальный.

### research_projects
- id: целое
- company_id
- recipe_id
- target_level: целое
- cost: целые ₽
- days_total: целое
- days_done: целое
- status: active / paused / done / cancelled
- request_id: строка

### patents
- id
- owner_company_id
- recipe_id
- expires_month: целое
- license_rate_bp: целое 0–500

### licenses
- patent_id
- licensee_company_id
- monthly_fee_last: целые ₽

Миграции: создать таблицы выше, без изменения существующих.

## Правила и формулы

### Стоимость и длительность проекта
base_cost = 100000 ₽ (для уровня 2, balance: draft)
cost = base_cost * target_level
days_total = (base_days * target_level * 1000) // (researchers_bonus_‰)
base_days = 30
researchers_bonus_‰ = 1000 + (tech_manager_skill - 5) * 30   // из модуля 10, максимум 1120 при навыке 9
days_total минимум 1

**Пример 1. Повышение рецепта хлеба с 1 до 2**
- base_cost = 100000, target_level = 2 → cost = 200000 ₽
- tech_manager_skill = 7 → researchers_bonus_‰ = 1000 + 2*30 = 1060
- days_total = (30 * 2 * 1000) // 1060 = 60000 // 1060 = 56 дней
Арифметика проверена дважды.

### Влияние уровня на качество и себестоимость
quality_bonus_‰ = (level - 1) * 50
final_quality = min(100, base_quality + quality_bonus_‰ // 10)
cost_reduction_‰ = (level - 1) * 20
unit_cost = (base_unit_cost * (1000 - cost_reduction_‰)) // 1000

**Пример 2. Хлеб, base_quality = 70, level = 3**
- quality_bonus_‰ = 2 * 50 = 100
- final_quality = 70 + 100 // 10 = 80
- cost_reduction_‰ = 40
- если base_unit_cost = 40 ₽ → unit_cost = (40 * 960) // 1000 = 38 ₽

### Устаревание
Каждый месяц без активного проекта на этот рецепт:
efficiency_‰ = max(500, efficiency_‰ - 30)
Если efficiency_‰ < 800 и level > 1 → level = level - 1, efficiency_‰ = 1000

### Лицензия
monthly_fee = (production_volume * license_rate_bp) // 10000
production_volume в единицах каталога (piece для хлеба).

## Алгоритмы тиков (псевдокод)

**Суточный тик (projects):**
```
for project in active_projects:
    if company.cash >= 0:  # не уходит в минус
        project.days_done += 1
        if project.days_done >= project.days_total:
            set tech_level = target_level
            efficiency_‰ = 1000
            project.status = done
```

**Месячный шаг:**
```
for recipe in company_tech:
    if no active project this month:
        apply_obsolescence()
for license in active_licenses:
    fee = calculate_fee()
    if licensee.cash >= fee:
        post ledger (licensee -fee, licensor +fee)
        request_id = license:<patent>:<YYYYMM>
    else:
        pause license
```

## Проводки ledger

- Старт проекта: company -cost, system:research +cost (**новый счёт, добавить**). request_id = research:<project_id>:start
- Лицензия: licensee -fee, licensor +fee. request_id = license:<patent_id>:<YYYYMM>
- Отмена проекта (если разрешено): system:research -refund, company +refund. refund = cost * days_done // days_total // 2

Все идемпотентны, сумма 0, счета >= 0. При нехватке денег проект не стартует.

## API

- GET /research/projects → список активных
- POST /research/start {recipe_id, target_level, request_id} → 201 или 402 нехватка средств
- GET /tech/levels → текущие уровни
- POST /patents/license {patent_id, licensee_id} → 201
- Ошибки: 400 неверные параметры, 402 недостаточно средств, 409 уже есть активный проект

## Что показывает клиент

Экран «Исследования»: список проектов с прогресс-баром дней, текущие уровни рецептов, патенты и доход от лицензий. Пустое состояние: «Нет активных проектов».

## Приёмка (10 сценариев)

1. Старт проекта хлеба уровень 2, скилл 7 → cost=200000, days=56
2. Проект завершается → level=2, efficiency=1000
3. Качество хлеба с 70 до 80 при level 3
4. Себестоимость снижается на 40 ‰ при level 3
5. Устаревание: 6 месяцев без проекта → efficiency 820
6. Лицензия 1000 piece * 100 bp // 10000 = 10 ₽
7. Нехватка денег → проект не стартует, счёт не в минус
8. Отмена на 50 % → возврат 50 % * 50 % стоимости
9. Параллельные проекты ограничены навыком управляющего
10. Все проводки сумма 0, идемпотентны

## Зависимости

03 (рецепты), 04 (производство), 06 (рейтинг), 10 (управляющие), INTEGER_MATH, DECISIONS_APPROVED.

## Открытые вопросы (продолжение)

D-73. Максимальный уровень 5 или 10? Рекомендация: 5. Последствие: достаточно для M3. Срочность: до M3.
D-74. Можно ли отменять проект с частичным возвратом? Рекомендация: да. Последствие: меньше риска. Срочность: до M3.

Согласовано с модулями: 03, 04, 06, 10, INTEGER_MATH, DECISIONS_APPROVED.
