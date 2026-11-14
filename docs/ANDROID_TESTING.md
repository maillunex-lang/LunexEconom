# Тестирование APK на собственном Android

## Сборка
GitHub Actions: https://github.com/maillunex-lang/LunexEconom/actions

Workflow **Android APK build for manual device testing** запускается при изменениях Android-клиента или вручную. Он собирает debug APK, проверяет архив, ABI и подпись, публикует artifact **android-debug-apk** с APK и SHA256SUMS. Эмулятор отключён, чтобы не задерживать сборки.

## Как скачать
1. Открыть GitHub Actions, выбрать успешный запуск **Android APK build for manual device testing**.
2. В разделе Artifacts скачать **android-debug-apk** (ZIP, для скачивания может потребоваться вход в GitHub).
3. Распаковать ZIP на Android, установить `Bashkiria-Honey-Oil-debug.apk` (разрешить установку из выбранного источника при необходимости).
4. Проверить старт, горизонтальную ориентацию, отступы экрана, управление, сеть, выход и повторный запуск.
5. Сообщить ошибки и прислать скриншоты; отметить модель телефона и версию Android.

## Релиз
Для публичного GitHub prerelease нужен отчёт о реальной проверке по `docs/device-tests/README.md` с SHA-256 **того же APK**, что скачан из Actions. До отчёта сборка остаётся тестовым artifact, а не опубликованным релизом. APK подписан debug-ключом, постоянная release-подпись ещё не настроена.

Firebase Test Lab остаётся отключённым; никаких платных тестов не запускается.
