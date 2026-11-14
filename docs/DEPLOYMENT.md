# Автопубликация сайта и Android APK

## Сайт
- Публичный исходник: `web/`.
- GitHub Actions `website-check.yml` проверяет JavaScript, HTML-маркеры и скрипт деплоя.
- VPS timer каждые ~5 минут проверяет SHA `main`, скачивает сайт **по одному зафиксированному SHA**, валидирует и обновляет только `/var/www/rikagro-game/lunexeconom/`.
- Рабочий сайт сохраняется при ошибках скачивания/валидации. Развёртывание не изменяет конфигурацию nginx и другие проекты.
- ВАЖНО: GitHub Actions checks и VPS timer независимы. Timer проверяет файлы локально, **но пока не проверяет статус успешности GitHub Actions**. Не считайте это строгим CI-gate. Для строгого gate требуется отдельная проверка GitHub Checks API.
- Нет секретов GitHub и нет открытого SSH в GitHub Actions.

## APK
- Только релизы GitHub с APK-asset, размером >=100 КБ, не draft.
- На VPS скачивается APK, сверяется размер, ZIP CRC и наличие AndroidManifest.xml, вычисляется SHA-256.
- Только после проверки обновляется `release.json` с фактической ссылкой на GitHub Releases.
- Сборка APK и проверка подписи пока **не реализованы**. Пустой ручной workflow не публикует APK.
- Не загружать в GitHub Release APK, не проверенный на Android и на соответствие версии.
- При сбое проверки последняя корректная ссылка сохраняется.
- Файл `web/release.json` в репозитории имеет статус unavailable; live release.json управляется сервером.

## VPS
- `/opt/lunexeconom-deploy/deploy.py` (только копия из ops/)
- `/etc/systemd/system/lunexeconom-deploy.service`
- `/etc/systemd/system/lunexeconom-deploy.timer`
- `/var/lib/lunexeconom-deploy/` (состояние и скачанные проверенные APK)
- `systemctl status lunexeconom-deploy.timer`
- `journalctl -u lunexeconom-deploy.service -n 50 --no-pager`

## Откат
Остановить таймер: `systemctl disable --now lunexeconom-deploy.timer`.
Восстановить файлы сайта из заранее сделанного архива и перезапустить таймер после устранения причины. Другие службы не затрагиваются.
