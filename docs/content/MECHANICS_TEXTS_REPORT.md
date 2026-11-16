# Отчёт: тексты для новых механик (V2-G-TEXT2)

Ветка: v2/mechanics-texts (от main)

## Добавлено

- errors.ru.md: +14 строк в таблицу ошибок (коды дорог, топлива, материалов, участков)
- achievements.ru.md: +12 достижений
- loading_tips.ru.md: +15 подсказок
- Этот файл (новый)

## Коды ошибок и источники

- road_unreachable, no_road_access, insufficient_funds (с ценой дороги) - из docs/enterprises.md (раздел Автоматическая дорога)
- fuel_unaffordable, fuel_missing - из docs/supply.md (V2-FUEL1)
- materials_missing, materials_wait - из docs/enterprises.md (CAT1. Сток стройматериалов)
- request_id_conflict - из идемпотентности в enterprises.md и supply.md
- parcel_not_owned, outside_parcel, occupied, water, invalid_zone, road_overlap - из логики размещения в enterprises.md, docs/gdd/23_REALESTATE.md и world (проверено, не дублируют существующие)

Все коды взяты из документов, не выдуманы.

## Оставил на потом

- Тексты для аренды ТЦ и помещений (пока в GDD, не в коде) - только базовые достижения first_mall/first_tenant
- Подробные подсказки по известности и конкурентам (есть базовые)
- notifications.ru.md и ui_strings.ru.md не трогал, как просили
- Более длинные описания достижений, если понадобятся

## Проверка

Длины текстов ошибок ≤60, подсказок ≤100, tips ≤120. ID достижений уникальны (проверено против существующих). Существующие строки не менялись. Запрещённых слов и реальных брендов нет. Башкирский колорит лёгкий (Урал, Белая, мёд в контексте).

SHA коммитов: e31fb5151b7ab5cab7596ea75840b0a108bede8b (errors), 376152be24c53d224c2e5391ac549eeaef71a1d4 (ach), 80b38f98cf179e3c3305ddee4c808f9bb8ff5acd (tips)
