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

## Обновление APK через manifest.json (раунд 2)

- Публикация `android-release.yml` принимает только артефакт `lunexeconom-signed-release-candidate`, проверяет SHA-256 из отчёта испытаний и подпись APK; выпускает APK и `build_info.json` в GitHub Release.
- `ops/deploy.py` читает метаданные версии из `build_info.json` в GitHub Release, проверяет скачанный APK, кладёт его в `/var/www/rikagro-game/lunexeconom/versions/` и атомарно обновляет `updates/manifest.json` (schema 1, version_code, version_name, url, sha256, size). Debug-APK в манифест не попадает. Откат version_code и замена файла при прежнем коде запрещены.
- Если релиз/метаданные недоступны или проверка не прошла, прежний манифест сохраняется. Внимание: до проверки реального подписанного релиза публикацию нельзя считать испытанной.

### Ручная переустановка deploy.py на VPS (только после отдельного разрешения владельца)

**В этой ветке на VPS ничего не устанавливается.** После успешного CI и слияния, когда владелец разрешит обновление, администратор выполняет вручную:

1. Сверяет `main` с проверенным SHA, сохраняет резервную копию `/opt/lunexeconom-deploy/deploy.py` и текущего `updates/manifest.json` (если существует).
2. Копирует **именно проверенный** `ops/deploy.py` из репозитория в `/opt/lunexeconom-deploy/deploy.py` через временный файл с атомарной заменой; не изменяет systemd unit/timer, nginx или сервер игры.
3. Выполняет `python3 -m py_compile /opt/lunexeconom-deploy/deploy.py`, затем разово запускает `systemctl start lunexeconom-deploy.service` в согласованное время.
4. Проверяет `journalctl -u lunexeconom-deploy.service -n 50 --no-pager`, `https://rikagro.ru/lunexeconom/updates/manifest.json` и совпадение SHA-256 опубликованного APK. Если подписанного релиза ещё нет, старый манифест должен сохраниться.
5. При ошибке возвращает резервную копию скрипта и манифеста; перезапуск игрового сервера не требуется.

**Важно:** обновление кода в GitHub само по себе не переустанавливает локальную копию `/opt/lunexeconom-deploy/deploy.py`.
