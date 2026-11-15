# ChatGPT8: визуальный контроль GLB (15 ноября 2026)

## Реально выполнено
- Godot 4.7.2 / Xvfb с OpenGL Mesa llvmpipe: создан PNG `factory` 960×540 с vertex-color материалами через `BuildingModels.make`, подтверждено визуально, что геометрия видна.
- Создан PNG `tractor_2x2` 960×540; визуально виден, но силуэт слишком схематичен (кабина/колёса слабо различимы). Художественную приёмку трактора **не проходил**.
- `client/qa/capture_model.gd` теперь принимает `LUNEX_QA_KIND`, `LUNEX_QA_WIDTH`, `LUNEX_QA_HEIGHT`, `LUNEX_QA_SCREENSHOT` и использует тот же загрузчик GLB, что и клиент.
- Workflow `.github/workflows/godot-visual-smoke.yml` теперь сохраняет **6 отдельных PNG** (factory, truck, tractor, construction_foundation, construction_frame, road_corner) в GitHub Actions artifacts, с fail-on-missing PNG.
- Godot runtime smoke ранее успешно проверил 7 GLB, а не только наличие файлов.

## Что ещё требуется
- Подтверждение выполнения GitHub Actions (локальные скриншоты factory и tractor не доказывают запуск CI).
- Отдельный арт-проход всех 60 GLB; транспорт доработать и анимировать.
- Снимки настоящего Android UI, а не только изолированной сцены.
- PostgreSQL multi-client load: ранее зафиксированы 80 rate-limited 429 из 200 операций при одном IP. Следующий тест должен соблюдать rate limit и не отключать защиту.
