# Аудит V2-A4: оркестратор выпуска альфы

Дата: 2026-11-16. Область: GitHub Actions, публичные отпечатки, скрипты выпуска, тестовые фикстуры. Секретные значения не считывались и не менялись; VPS production и V1 не затронуты.

## Архитектура выпуска

- `.github/workflows/android-alpha-release.yml` управляет одним запуском: preflight → reusable Android release candidate → подписанный manifest → полная публикация.
- GitHub Release появляется только после успешной подписи и проверки пары `update.json` / `update.json.sig`. Первое состояние Release при загрузке assets: **Draft** с явной отметкой о неполном выпуске. Публичное состояние **not draft, not prerelease** выставляется только при наличии всех пяти files и повторной проверке их метаданных. Ошибка при загрузке оставляет скрытый Draft, который нельзя принимать за готовый.
- Владелец запускает `workflow_dispatch` на `main` с `version=0.1.N`, русскими `notes` 1..300 символов, необязательным `min_version_code` (по умолчанию код предыдущего опубликованного альфа-релиза). Входные `candidate_run_id` и `version_tag` больше не нужны: APK и манифест передаются между jobs как артефакты одного run.
- Структурный тест `pipeline_test=true` использует `ci-test` и отдельные одноразовые ключи без публикации в GitHub Releases и без доступа к производственным environments. Push на рабочую ветку оркестратора инициирует такой же тестовый конвейер. Отладочный `android-build.yml` не входит в выпуск.
- Старый ручной `android-publish.yml` отказывает для тегов `v0.1.N`; ручной `android-manifest.yml` остаётся отдельным legacy инструментом, но не вызывается новой цепочкой. На VPS ничего автоматически не отправляется.

## Обязательные контрольные точки

| Контроль | Реализация |
| --- | --- |
| Одна альфа за раз | `concurrency`, `cancel-in-progress: false` |
| Только `main` для настоящего выпуска | проверка источника и main SHA в preflight/publish; Environment branch policies настраиваются отдельно |
| Версия | `0.1.N`, `versionCode=1000+N`; сравнение опубликованных релизов и существующих alpha-тегов |
| Минимальная версия | previous published alpha code, либо 1 при первой альфе; override в диапазоне |
| APK certificate | `apksigner verify`, pinned SHA256 `ops/release_cert_sha256.txt` |
| Android package | `org.lunex.bashkiria.v2`, совпадение versionName/versionCode, единственная ABI arm64-v8a |
| Размер | `tools/check_apk_size.py`, не больше 99 MiB |
| APK/AAB | SHA256SUMS проверяется и повторно сверяется; `jarsigner -verify` для AAB |
| Манифест | canonical JSON, SHA256 и size APK, HTTPS URL нужной версии, RSA signature по `client/config/update_public.pem`, minimum code |
| Утечка ключей | `MANIFEST_SIGNING_KEY` только в environment секрете на шаге подписи; PEM 0600, trap удаления; Android keystore удаляется в конце candidate job |
| Права | по умолчанию `contents: read`, запись в Releases только у publish job; `id-token` отсутствует |

## Окружения и остающиеся предпосылки

`android-signing`, `manifest-signing`, `production` должны быть **без Required reviewers**, с разрешённой deployment branch **только `main`**. Их настройки делает **отдельный серверный скрипт**, не эта ветка. Пока правила окружений не проверены владельцем, нельзя обещать полностью безостановочный запуск. Обязательна защита изменений `main` и CI workflow от несанкционированного пуша.

Актуальные публичные отпечатки из утверждённого V2-A1:
- Android release certificate SHA256: `9C:B4:27:81:91:73:3D:08:32:A4:A5:B6:41:95:83:D3:12:4C:64:12:B6:7D:F8:48:14:B6:A1:9F:5C:9A:7E:A4` (не изменён).
- RSA manifest public DER SHA256: `280770e34e420e87bc44c7d8018efd2127690027afc290c020cec9c9d37d97dd` (не изменён).

В старом аудите от 2026-11-15 были устаревшие утверждения о ручном одобрении и локальной подписи; актуальная схема описана здесь и в `docs/release.md`.

## Границы испытаний

Криптографические unit-тесты используют **одноразовые тестовые ключи**, а тесты метаданных используют искусственные APK/AAB байты с ожидаемыми хешами. Это не заменяет настоящие `apksigner`, `aapt`, Android экспорт Godot и GitHub Actions `pipeline_test`. Перед приёмкой нужны CI на итоговом SHA: `server-check`, `client-check`, `website-check`, тестовый запуск Android alpha release; сертификаты и production environment без чтения секретов проверить отдельно.

Тестовый и боевой Release в рамках V2-A4 **не публиковались**. Реальная подпись через GitHub Secret и работа автообновления на телефоне должны быть проверены позднее на разрешённом выпуске. Отмена боевого релиза выполняется новой более высокой версией; ранее опубликованные Release не удаляются.