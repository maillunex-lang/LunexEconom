# Предложение: данные ИИ-игроков (AI_PLAYERS_DATA.md)

**Статус:** draft. Числа `balance: draft`. Целые числа. Ветка `v2/ai-players-design`.

## Структура данных

Все в `tools/sim/data/ai_proposed/`:

- `archetypes.json` — 8+ архетипов с параметрами.
- `personas.json` — 12–16 персонажей.
- `reply_templates.json` — ключи шаблонов (полные тексты в docs/content).
- `limits.json` — глобальные лимиты.

## Архетипы (пример структуры)

Каждый:
```json
{
  "id": "cautious_saver",
  "name_ru": "Осторожный накопитель",
  "risk_permille": 200,
  "patience_days": 90,
  "reinvest_permille": 300,
  "price_aggression_permille": 100,
  "debt_threshold_permille": 200,
  "competitor_reaction_permille": 300,
  "preferred_chains": ["grain_flour_bread", "dairy"],
  "preferred_cities": ["ufa", "sterlitamak"]
}
```

## Персонажи

Связаны с архетипом. Оси характера 0–1000. Биография на русском, башкирский контекст.

## Шаблоны реплик

Ключи вида `deal_success_cautious`, `contract_offer_aggressive`. Плейсхолдеры только: {company}, {city}, {goods}, {price_rub}, {days}.

## Лимиты (draft)

- max_actions_per_ai_per_day: 5
- max_total_actions_per_tick: 500
- max_lm_calls_per_day: 20
- max_lm_cost_game_rub_per_day: 50
- memory_max_bytes: 4096
- dump_below_cost_max_days: 7
- market_buy_share_max_permille: 400

## Проверка

tools/validate_ai_proposal.py должен проходить на этих данных.
