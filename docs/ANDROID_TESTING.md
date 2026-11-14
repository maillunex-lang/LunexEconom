# Android Emulator и Firebase Test Lab

## GitHub Actions: бесплатный для VPS CI-эмулятор
Файл `.github/workflows/android-build.yml` собирает APK для ARM64 и x86_64. После успешного экспорта job `emulator-smoke` на GitHub-hosted runner:
1. запускает Android 35 x86_64 (Pixel 6);
2. устанавливает APK и запускает пакет `ru.lunex.bashkiriahoneyoil`;
3. проверяет процесс и активность;
4. сохраняет `emulator-results/launch.png`, `logcat.txt`, `activities.txt`, `window.txt` и результаты в GitHub artifact `android-emulator-diagnostics`.

Сценарий: `ops/emulator-smoke.sh`. Тест запускается автоматически после изменений клиента и вручную через GitHub Actions.

**Ограничения:** Smoke-тест не подтверждает корректность геймплея, визуальное качество, жесты pinch/drag, сетевую игру и работу на физическом ARM64-телефоне. На GitHub-hosted runners могут действовать лимиты минут/платформы. В отчётах нельзя ставить PASS физическому устройству по результатам эмулятора.

## Firebase Test Lab: подготовлен, но заблокирован
Файл `.github/workflows/firebase-test-lab.yml` содержит отключённый job (`if: false`).
**Никакие тесты Firebase не запускаются, Google Cloud billing не подключается, ключи не создаются.**

Для будущего подключения нужны:
- собственный Google Cloud/Firebase проект и явное согласование лимитов расходов;
- защищённая федеративная авторизация GitHub OIDC / Workload Identity Federation без JSON-ключа в публичном репозитории;
- выбранные реальные устройства и лимиты количества тестов;
- отдельный Android Game Loop / instrumentation сценарий для Godot;
- публикация скриншотов, логов и результатов в artifacts GitHub Actions.

Не включать workflow, пока пользователь отдельно не разрешит платные облачные тесты и не установит бюджетные ограничения.

## Условия GitHub Release
Проверенный эмуляторный тест является предварительным quality gate, но **не заменяет** отчёт о тестировании на физическом Android, требуемый текущим `android-release.yml`. До проверки подписи релизным ключом публикуются только тестовые debug prerelease.

## Проверка результатов
Открыть https://github.com/maillunex-lang/LunexEconom/actions и выбрать `Android APK build and emulator smoke`. Проверить оба job и скачать artifact `android-emulator-diagnostics`. Если job не запустился, нельзя считать тест пройденным.
