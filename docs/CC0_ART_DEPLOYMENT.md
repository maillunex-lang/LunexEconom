> **Устарело (15.11.2026):** 2D-спрайты больше не используются клиентом — мир перешёл на 3D ([WORLD3D.md](WORLD3D.md)). Загрузчик `asset_downloader.gd` и `remote_art_catalog.gd` удалены из клиента.

# Каталог графики Kenney CC0: установленная тестовая библиотека

Дата: 2026-11-15. Источник: Kenney, **Isometric City** (`cityTiles_*.png`), https://kenney.nl/assets/isometric-tiles-city. Лицензия: **CC0 1.0**, оригинальная `License.txt` в ZIP, проверена на VPS.

## Архитектура

- Исходный ZIP (не игровой релиз): `/home/gamedev/assets-research/lunexeconom-cc0/isometricCity.zip`.
- Оптимизированные PNG: `/var/www/rikagro-game/lunexeconom/assets/art-catalog/defaults/<sha256>.png`.
- Каталог режимов: `.../art-catalog/catalog.json`, публичный манифест: `https://rikagro.ru/lunexeconom/assets/art-catalog/manifest.json`.
- Android Godot: `client/remote_art_catalog.gd`, HTTPS, SHA-256, `user://catalog_art/`, динамический выбор изображения в `client/chunk_renderer.gd`.
- World Studio: каталог объектов, просмотр стандартной и своей картинки, PNG override и откат к стандартной.

## Соответствие исходных тайлов

| Группа | art_id → индекс cityTiles |
|---|---|
| Жильё | housing.small→014; housing.panel_a→082; housing.panel_b→083; housing.apartment→103; housing.stalinka→106 |
| Магазины | retail.grocery→045; supermarket→048; hypermarket→050; bakery→055; produce→060; clothing→066; electronics→070; pharmacy→071 |
| Производство | industry.farm→032; livestock→038; grain_silo→024; mine→089; oil_well→092; quarry→098; factory→109; warehouse→113; logistics→118; research→121 |
| Социальные | municipal.school→073; hospital→030; park→020 |

**26 привязанных спрайтов из 55 типов каталога**. Прочие типы остаются с процедурным fallback до подбора подходящих изображений. Набор Kenney является **стилизованным низкополигональным прототипом**: не выдавать его за уникальную высокодетализированную графику башкирских зданий. Названия категорий обозначают назначение в игре, а не достоверную архитектурную идентичность исходных тайлов. Дороги пока процедурные.

## Проверки

- Тест каталога: default/custom, SHA, HTTP 200 для PNG и манифеста.
- Godot 4.7.2: скрипты компилируются, HTTPS загрузка **26 из 26**, запуск `world.tscn` в headless и создание 25 чанков без ошибок.
- Рендер: один спрайт на объект с известным `object_id` внутри доступных клеток; для объектов без ID сохраняется legacy fallback. Проверка перекрытия между чанками на реальном Android ещё требуется.
- APK: отдельная QA-сборка; не заменять production APK без визуального тестирования.

## Что ещё не закрыто

Оставшиеся 29 типов требуют художественно подходящих изображений; 1×1/2×1 реальные размеры зданий, их опорные точки, прозрачность и перекрытие чанков требуют QA на Android. Экономические механики новых специализаций не включены этим графическим этапом.

## Тестовая Android-сборка

- Отдельная QA APK: https://rikagro.ru/lunexeconom/assets/releases/Bashkiria-Honey-Oil-CC0-remote-QA.apk
- SHA-256: `b3fffd21da8e30cded881cb7e8894115c4f9ad08187768f925b3b2089968e1f9`.
- Godot 4.7.2 Android debug export завершён, `apksigner verify` успешен, HTTPS Range GET возвращает 206. Сборка **не заменяет** текущую production APK и не меняет механизм обновлений.
- Headless world smoke test: 25 чанков и 26 загруженных текстур. Визуальный тест на физическом Android пока не проводился.
- При открытии мира клиент скачивает манифест и PNG на устройство; без связи остаётся процедурный fallback. Наличие кэша проверяется по SHA-256.
