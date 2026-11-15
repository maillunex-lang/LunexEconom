# Предложение 12. Бренд и реклама (полная спецификация)

**Цель:** смоделировать бренд (0–100) компании и товара, рост от рекламных расходов, затухание, каналы, медиакомпании как бизнес. Влияние на спрос (07) только с M3.

Все расчёты по INTEGER_MATH.md. ad_factor только умножение на промилле. До M3 ad_factor_‰ = 1000 (утверждено).

## Сущности и данные

### brands
- id
- owner_company_id
- target_type: company / product / store
- target_id
- value: целое 0–100
- last_ad_day: целое

### ad_campaigns
- id
- company_id
- channel: newspaper / radio / tv / internet
- budget: целые ₽
- reach_‰: целое
- days_total
- days_done
- status: active / done

### media_companies
- enterprise_id (связь с 04)
- channel_type
- daily_capacity_‰: целое

Новое здание медиакомпании: **новое здание, добавить в каталог**. Предложение полей: build_cost=250000, build_days=45, jobs=8, zones=центр/жилая.

## Правила и формулы

### Рост бренда (ступени)
Таблица из INTEGER_MATH.md:
| budget_мес ₽ | ad_factor_‰ |
|--------------|-------------|
| 0–999      | 1000        |
| 1000–4999  | 1050        |
| 5000–19999 | 1100        |
| 20000+      | 1150        |

delta_brand = (daily_spend * reach_‰) // 100000
brand = min(100, brand + delta_brand)

**Пример 1. Реклама хлеба**
- daily_spend = 500 ₽, reach_‰ = 600
- delta_brand = (500 * 600) // 100000 = 3
- brand был 40 → стал 43
Арифметика проверена дважды.

### Затухание
Если нет активной кампании в день и brand > 20:
brand = brand - 1

### Влияние на спрос (07)
До M3: ad_factor_‰ = 1000
С M3: demand = (demand * ad_factor_‰) // 1000
Никакого деления на ad_factor.

### Влияние на рейтинг (06)
rating_bonus = (brand * brand_weight) // 100
brand_weight из products.json (25 для хлеба)

### Каналы
- newspaper: reach_‰ = 400, price_per_day = 200 ₽
- radio: reach_‰ = 600, price_per_day = 500 ₽
- tv: reach_‰ = 900, price_per_day = 2000 ₽
- internet: reach_‰ = 700, price_per_day = 800 ₽

### Конкуренция брендов
Доля внимания = (brand_i * brand_i) // sum(brand_j^2)
Доля в промилле, применяется к делению спроса района.

## Алгоритмы тиков (псевдокод)

**Суточный:**
```
for campaign in active:
    if company.cash >= campaign.daily_price:
        post ledger company -price, media +price
        apply delta_brand
        campaign.days_done += 1
    else:
        pause campaign
apply_decay_to_brands_without_ads()
```

**Месячный:**
```
update_ad_factor_table_from_monthly_spend()
report_media_revenue()
```

## Проводки ledger

- Реклама: advertiser -spend, media_company +spend. request_id = ad:<campaign>:<day>
- Если нет медиакомпании: advertiser -spend, system:treasury +spend (**используем существующий счёт**)

Идемпотентно, сумма 0, счета не в минус. При нехватке денег кампания на паузе.

## API

- GET /brands → список брендов
- POST /ads/campaign {channel, budget_total, days, request_id}
- GET /media/channels → доступные каналы и цены
- Ошибки: 402 недостаточно средств, 400 неверный канал

## Что показывает клиент

Экран «Реклама»: текущий бренд товаров, активные кампании, доход медиакомпаний. Пустое: «Нет активных кампаний».

## Приёмка (10 сценариев)

1. Реклама 500 ₽/day reach 600 → delta_brand = 3
2. Бренд 40 → 43
3. Без рекламы 5 дней → brand 40 → 35 (если >20)
4. До M3 ad_factor_‰ = 1000, спрос не меняется
5. С M3 budget 10000/mes → ad_factor_‰ = 1100
6. Рейтинг хлеба + (brand * 25) // 100
7. Два бренда 60 и 40 → доли 69 % и 31 %
8. Нехватка денег → кампания на паузе
9. Медиакомпания получает выручку от рекламы
10. Все проводки сумма 0

## Зависимости

06, 07, 04, INTEGER_MATH, DECISIONS_APPROVED.

## Открытые вопросы (продолжение)

D-75. Минимальный бюджет кампании? Рекомендация: 1000 ₽. Последствие: доступно. Срочность: до M3.
D-76. Медиакомпании в M4? Рекомендация: да. Последствие: новый бизнес. Срочность: до M4.

Согласовано с модулями: 04, 06, 07, INTEGER_MATH, DECISIONS_APPROVED.
