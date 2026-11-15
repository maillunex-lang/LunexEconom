# LunexEconom V2 · подпись, обновления и ресурсные пакеты

Статус: реализация V2-01b в ветке `v2/release`. **Никакого production-развёртывания на VPS и настоящих секретов в GitHub не выполнялось.** Часть C только по прямой команде владельца «выполняй часть C».

## 1. Публичный адрес и маршруты

Android: единственная настройка `client/config/public_base.gd`, по умолчанию `https://rikagro.ru/lunexeconom`. Для доверенной сборки можно переопределить `ProjectSettings`-параметр `lunex/public_base_url`. Веб: единственная настройка `web/config.js`. Все пути сайта относительные (`./styles.css`, `./download/lunex.apk`), не начинаются с `/`. Проверка: `python3 tools/check_website.py`. Не устанавливать cookies на общий домен `rikagro.ru`. Токен авторизации Android хранится в зашифрованном локальном хранилище Android Keystore (AES-GCM) после регистрации/входа.

| URL относительно base | Доставка |
| --- | --- |
| `update.json` и `update.json.sig` | Статические манифест и detached RSA-подпись; `Cache-Control: no-store` |
| `content.json` и `content.json.sig` | Статические манифест и подпись; `Cache-Control: no-store` |
| `download/lunex.apk` | Подписанный APK, поддержка HTTP Range/206 и byte ranges |
| `packs/<name>-<version>.pck` | Неизменяемые проверяемые пакеты; `Cache-Control: public,max-age=31536000,immutable` |
| `api/` | Только прокси к игровому API; не использовать static; запретить кеш токенов |

**План для nginx, будущая часть C, НЕ применять здесь.** В конфигурации общего HTTPS-хоста нужно обслужить отдельными location `/lunexeconom/api/` (reverse proxy игровому сервису), `/lunexeconom/download/` (локальный каталог APK), `/lunexeconom/packs/` (иммутабельные PCK), `/lunexeconom/update.json`, `/lunexeconom/update.json.sig`, `/lunexeconom/content.json`, `/lunexeconom/content.json.sig` (статика с revalidation/no-store) и `/lunexeconom/` (лендинг). **Не создавать** параллельных корневых `/download/` или `/packs/`; это относительные пути внутри `/lunexeconom/`. Провести `nginx -t`, проверить отсутствие конфликтов с остальным содержимым `rikagro.ru`, затем отдельное согласованное развёртывание.

Манифесты содержат **полные HTTPS URL**, которые клиент принимает только в рамках настроенного базового адреса. Перенаправления HTTP отключены, URL с другой схемой, хостом, пользовательскими данными, query/fragment и traversal отклоняются.

## 2. Создание постоянного APK-ключа: ТОЛЬКО ВЛАДЕЛЕЦ

**Действия ниже выполняет владелец на доверенном устройстве, не на VPS и не в ChatGPT.** Для нового пакетного идентификатора `org.lunex.bashkiria.v2` нужен один неизменный ключ.

```sh
# Пароли вводятся интерактивно, не в командах и не в истории shell.
keytool -genkeypair -v \
  -keystore lunexeconom-release.p12 \
  -storetype PKCS12 \
  -alias lunexeconom-release \
  -keyalg RSA -keysize 4096 \
  -validity 10000 \
  -dname "CN=LunexEconom Android Release"
```

`10000` дней примерно 27 лет. Не использовать debug-ключ, не менять идентификатор пакета. Для текущего Godot 4.7 пароль keystore и пароль ключа должны быть **одинаковыми**. Альтернативу EC поддерживает Android keystore/toolchain, но для этого проекта рекомендован RSA-4096 ради предсказуемой совместимости.

Сделать **две резервные копии вне GitHub и VPS**, в двух независимых зашифрованных хранилищах/офлайн-носителях. Отдельно хранить надёжно записанный пароль и alias, проверить восстановление обоих архивов. **Потеря приватного ключа может навсегда запретить обновление уже установленных APK**, если нет отдельного механизма ротации подписи в соответствующей среде Android.

Скопировать keystore в base64 и добавить через GitHub → Settings → Secrets and variables → Actions → environment `android-signing` (с обязательным одобрением владельца). Секреты: `ANDROID_KEYSTORE_BASE64`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD`. Не отправлять пароль/base64 ключа в ChatGPT, git, issue, PR, логи, VPS.

```sh
base64 -w0 lunexeconom-release.p12 > lunexeconom-release.base64
# Это СЕКРЕТ: копировать только в GitHub Secrets, затем убрать временный файл.
# Публичный отпечаток, для фиксации в ops/release_cert_sha256.txt:
keytool -exportcert -rfc -keystore lunexeconom-release.p12 -alias lunexeconom-release \
  | openssl x509 -noout -fingerprint -sha256
```

В `ops/release_cert_sha256.txt` заменить комментарий **публичным** SHA-256 отпечатком сертификата (32 байта, hex); не копировать приватный ключ. `tools/verify_apk_cert.py` отклоняет отсутствие файла, чужую подпись или несколько сертификатов. При тестовом режиме в CI отпечаток вычисляется от одноразового тестового сертификата; выпуск такого APK в production запрещён.

## 3. Отдельный ключ манифестов

**Владелец отдельно** на доверенном офлайн-устройстве создаёт приватный RSA-4096 ключ, который **не совпадает** с ключом Android APK:

```sh
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:4096 -out lunex-manifest-private.pem
openssl pkey -in lunex-manifest-private.pem -pubout -out lunex-manifest-public.pem
```

Приватный ключ только у владельца + две независимые резервные копии. Публичную часть положить в `client/config/update_public.pem` и зафиксировать в проекте для следующей подписанной сборки. Без неё клиент **не принимает ни update.json, ни content.json** (fail closed).

Отдельные `update.json.sig` и `content.json.sig` это base64 RSA PKCS#1 v1.5/SHA-256 над **точными байтами** канонического JSON (`sort_keys`, compact UTF-8, завершающий newline). Скрипт:

```sh
python3 tools/make_update_manifest.py build/lunex.apk --version v2.0.1 \
  --min-code 1 --notes "Обновление игры" --output build/update.json
python3 tools/sign_update_manifest.py build/update.json \
  --private-key /offline/lunex-manifest-private.pem \
  --public-key /offline/lunex-manifest-public.pem
python3 tools/sign_update_manifest.py build/packs/content.json \
  --private-key /offline/lunex-manifest-private.pem \
  --public-key /offline/lunex-manifest-public.pem
```

**Никогда не передавать приватный ключ** в CI/VPS. Подпись только владельцем локально. Каждый manifest и `.sig` публикуются атомарно парой после проверки обоих. При ошибке подписи, SHA, размера или скачивания игра удаляет повреждённый файл или сохраняет неполную `.part` для докачки; неподписанное обновление не предлагает.

## 4. Создание релиза и CI

`.github/workflows/android-release.yml` выполняется вручную (и для тегов `v*`). Test-режим CI: создаёт **одноразовый RSA-ключ** на runner, экспортирует релизные APK/AAB, проверяет `apksigner verify --print-certs`, отпечаток, версию, единственный `arm64-v8a`, `jarsigner -verify` для AAB, бюджет APK и публикует GitHub Actions **артефакт с предупреждением TEST-NOT-FOR-RELEASE**. Тестовый APK не является производственным релизом.

Для настоящего релиза после слияния в `main`: владелец фиксирует открытый отпечаток и публичный ключ манифестов, создаёт GitHub environment `android-signing` с required reviewers, добавляет четыре секрета, затем запускает workflow с `pipeline_test=false`. `tools/release_version.py` преобразует строгий тег `vMAJOR.MINOR.PATCH` в Android `versionCode = major*1000000 + minor*1000 + patch` и `versionName` без `v`. Следующая публикация должна иметь более высокий номер; не использовать теги вне схемы, проверять установленные версии. Debug APK подписывается **отладочным** ключом отдельного `android-build.yml` и не публикуется как релиз.

Отдельный `.github/workflows/android-publish.yml` запускает **только владелец вручную**, `environment: production` с обязательным одобрением. Требует успешный кандидат с **производственным** ключом того же SHA, заново проверяет подпись и размер, создаёт GitHub Release. **CI не имеет SSH-ключа VPS и никогда автоматически не копирует файлы на VPS.** Следующая фаза C, только после команды владельца, делает ручную публикацию GitHub Release APK, подписанных `update.json(.sig)`, `content.json(.sig)`, архивных пакетов и тестирует HTTPS Range/206.

## 5. Поведение приложения

`client/update/manifest_client.gd`: при старте, каждый час, по кнопке «Проверить обновление». При проверенном RSA-манифесте: версия выше текущей → кнопка «Скачать»; `min_version_code` выше установленной → блокирующее окно до успешного обновления. `resumable_download.gd`: последовательные Range-запросы до 512 КиБ, сохранение `.part`, проверка Content-Range, полного размера и SHA-256, автоматическая повторная попытка с паузами 1/2/4/8 сек. Можно включить «Только Wi-Fi», настройка хранится в `user://update_settings.cfg`.

`client/android_plugin/` исходники Android v2 плагина, `client/addons/lunex_installer/` Godot export-plugin. Сборка АAR выполняется CI и подключается при Gradle экспорте. `PackageInstaller` предлагает обновление системному установщику. Если неизвестные приложения запрещены, пользователь сам разрешает установку и повторяет нажатие. `FileProvider` резервный путь, без публичного `file://`. **Android не гарантирует установку APK полностью без действий пользователя.** `USER_ACTION_NOT_REQUIRED` на Android 12+ допустим только при выполнении условий platform/installer-of-record; система вправе потребовать подтверждение.

Android Keystore AES-GCM сохраняет токен авторизации в приложении, не в cookie/открытый домен. `user://`, настройки и токен сохраняются при установке поверх **той же package ID и того же сертификата**. При смене debug → release сертификат отличается: иногда требуется удалить тестовую сборку, **что может удалить данные**. Это не является безопасным обновлением.

## 6. Пакеты ресурсов и оптимизация

`tools/build_packs.py` собирает `client/content/<name>/...` в версионированные `<name>-<version>.pck`, выбирает ресурсные форматы PNG/WebP/JPG/GLB/OGG/WAV/MP3, без скриптов, .tscn, сторонних ссылок и symlinks. Упорядоченные одинаковые входные файлы формируют одинаковый SHA-256 (тест повторной сборки), отдельный `content.json` подписывается офлайн. `core_*` требуются сразу; остальные загружаются после 5 секунд без взаимодействия. Лимит кеша 500 МиБ; проверка размера, SHA-256, атомарный rename, очистка старых версий; `ProjectSettings.load_resource_pack` позволяет подключить готовый пакет без перезапуска. При недоступности пакета базовый клиент продолжает работать со встроенной графикой и заглушками; `pack_ready` сообщает остальным модулям о новой графике.

```sh
python3 tools/build_packs.py --source client/content --output build/packs \
  --version 2.0.1 --godot /path/to/Godot_v4.7.2-stable_linux.x86_64
```

Размер: цель **не более 30 МиБ** на APK `arm64-v8a`. Godot 4.7.2 Android release шаблон (ВСЕ архитектуры) содержит ~104.8 MB; из них ARM64 `libgodot_android.so` сжат ~22.9 MiB. Это **размер шаблона, а не готового APK**. Фактический размер debug и release после сборки записать ниже. Проверка `tools/check_apk_size.py` проваливает CI при превышении `30*1024*1024` байт. При необходимости использовать урезанный экспортный шаблон и анализ native libs, не обходить бюджет без решения владельца.

| Измерение | Размер |
| --- | --- |
| Стандартный Godot Android release template со всеми ABI | 104 803 333 байта (измерено на VPS; не APK проекта) |
| APK V2 до оптимизации (debug, main CI 43715238203) | 56 955 696 байт, SHA256 8c5e73e2c0ed7adf74dfc21a6166c9d5acce595fcef8a3d0da20bb7a83972668 |
| APK проекта после arm64/внешних пакетов | ожидается измерение CI |
| Целевой максимум | 31 457 280 байт (30 MiB) |

## 7. Проверки, отмена и ограничения

```sh
python3 -m unittest discover -s tools/tests -v
python3 tools/check_website.py
godot --headless --path client --editor --quit
godot --headless --path client -s tests/smoke.gd
godot --headless --path client -s tests/release_smoke.gd
```

Godot-ресурсный smoke запускается из `tools/tests/test_packs.py`: дважды собирает тестовый `.pck`, проверяет идентичность и делает динамическое подключение/чтение текстуры без перезапуска.
Дополнительная интеграционная проверка `tools/tests/test_network.py` запускает поддельный локальный HTTPS-сервер с одноразовыми тестовыми TLS/RSA ключами, проверяет подпись манифеста, отклонение изменённого содержимого, обязательное обновление, HTTP Range с обрывом и повтором, неверный SHA-256, скачивание и подключение PCK. Это тестовая сеть 127.0.0.1, не production и не новый сервер игры.

Дополнительно до приёмки на реальном Android: вручную проверить установку в системном UI, изменение разрешения неизвестных источников, Wi-Fi-only, переход с ошибочной подписи и SHA, докачку после обрыва, отсутствие потери авторизации, запуск в горизонтальном режиме с safe area. Серверное развертывание остаётся за отдельной частью C.

**Откат:** никогда не подменять подписанный опубликованный APK старым с меньшим versionCode: Android отклонит downgrade. Для отката логики пересобрать старый код под **новым более высоким** номером и подписать тем же APK-ключом. Для отката графики вернуть предыдущий проверенный `content.json` с новой подписью и сохранёнными immutable пакетами. Если потерян ключ подписания манифеста, старое приложение не начнёт доверять новому ключу без нового APK с обновлённым публичным ключом.
