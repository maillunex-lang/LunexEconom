# CreatePortal: развёртывание на VPS (rikagro.ru/createportal)

Только по прямой команде владельца, через исполнителя VPS. Секреты (пароль владельца, токен GitHub) в чат не присылаются: пароль владелец вводит сам на сервере, токен кладёт в файл сам.

## Состав
Один процесс Python 3.12 (только стандартная библиотека), SQLite, слушает 127.0.0.1:18790. Наружу через nginx по HTTPS на `/createportal/`. Данные: `/var/lib/createportal/portal.sqlite` (права 0700, пользователь `createportal`).

## Быстрая установка (одна команда)
На VPS от root: скачать `portal/deploy/install.sh` из репозитория и выполнить `sudo bash install.sh`. Скрипт сам создаёт пользователя, копирует код, ставит сервис и ежедневные копии, проверяет `/health`, один раз спросит пароль владельца (ввод скрыт) и сохранит предыдущую версию для отката. Повторный запуск = обновление (перед ним делается копия базы). Остаётся только шаг 6 (nginx). Ниже те же шаги вручную.

## Шаги
1. Пользователь без входа: `useradd --system --home /opt/createportal --shell /usr/sbin/nologin createportal`.
2. Код: клонировать репозиторий maillunex-lang/LunexEconom (ветка main) во временную папку, скопировать в `/opt/createportal` каталог `portal/` и файл `tools/work_plan.py` с пакетами `tools/__init__.py`: структура `/opt/createportal/portal/...` и `/opt/createportal/tools/work_plan.py`. Права: владелец root, чтение для createportal.
3. Данные: `install -d -m 0700 -o createportal -g createportal /var/lib/createportal`.
4. systemd: скопировать `portal/deploy/createportal.service` в `/etc/systemd/system/`, `systemctl daemon-reload`, `systemctl enable --now createportal`.
5. Пароль владельца: владелец сам запускает `sudo -u createportal PORTAL_DB=/var/lib/createportal/portal.sqlite python3 -m portal.manage set-password owner` и вводит пароль (не короче 14 символов) на сервере.
6. nginx: вставить `portal/deploy/nginx-createportal.conf` в server rikagro.ru, `nginx -t`, `systemctl reload nginx`.
7. Проверка: `curl -s https://rikagro.ru/createportal/health` отвечает `{"ok": true}`; в браузере вход, создание тестового проекта, удаление не требуется (можно оставить).
8. Резервная копия: ежедневно `sqlite3 /var/lib/createportal/portal.sqlite ".backup /var/backups/createportal/portal-$(date +%F).sqlite"`, хранить 14 дней; раз в неделю проверка восстановления на временной копии.
9. Откат: `systemctl stop createportal`, вернуть предыдущую папку `/opt/createportal.prev` и базу из резервной копии, `systemctl start createportal`.
10. Необязательно (синхронизация с GitHub): владелец создаёт токен GitHub только на чтение содержимого репозитория (fine-grained), кладёт в `/etc/createportal/github_token` (права 0600, владелец createportal), раскомментирует строку `PORTAL_GITHUB_TOKEN_FILE` в unit-файле, `systemctl restart createportal`.

## Обновление
Скопировать новый `portal/` и `tools/work_plan.py` из main в `/opt/createportal` (сначала сохранить `/opt/createportal.prev`), перезапустить сервис, проверить `/health`. Миграции схемы выполняются сами при старте (`CREATE TABLE IF NOT EXISTS`), данные не теряются.

## Безопасность (что уже сделано в коде)
Вход один владелец, пароль scrypt, лимит 8 попыток за 15 минут на IP и nginx limit_req; сессия 12 часов, cookie HttpOnly, Secure, SameSite=Strict, Path=/createportal; CSRF-токен на всех изменяющих запросах; CSP с nonce, запрет фреймов; размер запроса до 1 МБ; ни пароли, ни токены не логируются и не хранятся в репозитории.

## A1: безопасность и аудит (флаг выключен по умолчанию)

Перед включением на реальном портале: резервная копия SQLite **вместе с проверкой восстановления**, затем деплой из принятого директором main, затем миграции и тест `/health`. Никакие изменения в продакшене не выполняются при разработке A1.

**По умолчанию включено** (решение директора); `PORTAL_SECURITY_V2=0` отключает. Функции: `POST /api/password` (`current_password`, `new_password`), `POST /api/sessions/revoke` (`current_password`), `GET /api/audit` и часовую блокировку после 20 неудач по IP. Все новые операции под сессией; POST требуют `X-CSRF-Token`. При смене пароля передавайте новый `csrf` из ответа для следующих запросов; при отзыве всех сеансов потребуется новый вход. Аудит содержит не более 200 записей без секретов. Если переменная не задана, функции v2 выключены. `schema_versions` и индексы создаются при открытии SQLite независимо от флага, без удаления старых данных.

Внимание: IP-ограничитель использует `REMOTE_ADDR` (не доверяет клиентскому `X-Real-IP`). За nginx он может видеть только loopback. Для полноценного IP-лимита нужен доверенный reverse-proxy адаптер, отдельная проверенная настройка при развёртывании, либо лимиты на самом nginx. Уведомление владельца по событию `login.locked` будет подключено позже, когда согласован безопасный канал. TOTP не входит в A1.

## A2: GitHub webhook (только после отдельного разрешения на развёртывание)

Добавьте `PORTAL_WEBHOOK_ENABLED=1` и `PORTAL_WEBHOOK_SECRET_FILE=/etc/createportal/github_webhook_secret` в сервис, **после** создания секретного файла владельцем с правами 0600 и резервного копирования БД. Подпишите GitHub webhook `application/json`, URL `https://rikagro.ru/createportal/hook/github`, события push, pull_request, check_suite, workflow_run. Используйте конфигурацию `portal/deploy/nginx-createportal.conf` с лимитом 1 МБ. Новые таблицы появляются через последовательную миграцию 3 при первом запуске с флагом. Без флага вебхук и связанные API выключены. Не помещайте секрет в переменную окружения, репозиторий, базу или журнал. Директора предупредить: без `required_checks` автоприёмка оценивает только уже полученные проверки, а GitHub может доставлять события не по порядку. Для строгой гарантии перечислите обязательные проверки в настройках проекта.


## A5: флаги и фоновый обработчик

При запуске `python3 -m portal.serve` включён `PORTAL_FEATURES=webhook,reports,notifications,ops`.
Для отключения используйте `PORTAL_FEATURES=` либо отдельные `PORTAL_WEBHOOK_ENABLED=0`,
`PORTAL_REPORTS_ENABLED=0`, `PORTAL_NOTIFICATIONS_ENABLED=0`, `PORTAL_OPS_ENABLED=0`.
При прямом вызове `create_app` все новые функции по умолчанию выключены.

Токены: `PORTAL_GITHUB_TOKEN_FILE`, `PORTAL_WEBHOOK_SECRET_FILE`,
`PORTAL_MAX_TOKEN_FILE`, `PORTAL_TELEGRAM_TOKEN_FILE`. Только внешние файлы 0600,
доступные пользователю createportal. Каталог копий: `PORTAL_BACKUP_DIR`
(по умолчанию `/var/backups/createportal`), права доступа настроить для createportal.

Встроенный фоновый поток раз в 60 секунд обрабатывает уведомления, ожидающую приёмку,
привязки мессенджеров и опрос GitHub. Дополнительный cron для уведомлений не нужен.
Синхронизация GitHub на проекте: `POST /api/projects/{slug}/sync-settings` с
`{"sync_mode":"webhook|polling|both","poll_minutes":5|10|30}`.
Статус: `GET /api/projects/{slug}/sync-status`.
GitHub API используется только для чтения; без доступного полного списка check-runs
автоприёмка блокируется. Для GitHub webhook нужен действующий секрет HMAC.

Резервное копирование: `portal/deploy/backup.sh` (sqlite backup API, проверка
целостности, 14 последних). `portal/deploy/update.sh` вызывает проверенный install.sh,
сохраняющий `/opt/createportal.prev` и копию базы. Откат кода и восстановление БД
выполнять отдельно при остановленном сервисе; восстановление через
`portal.backup.core.restore_backup` только в новый файл. Не запускать deploy
без прямого разрешения владельца.

`GET /share?title=...&text=...&url=...` создаёт только черновик, не изменяет БД.
Сохранение идеи требует входа и POST с CSRF. Экспорт и импорт проектов,
удаление с подтверждением slug, граф, поиск, версия и сводка доступны через
авторизованный API.

Для существующей установки проверьте systemd override: при ProtectSystem=strict
нужно разрешить ReadWritePaths=/var/lib/createportal /var/backups/createportal.
Новый unit в portal/deploy/createportal.service уже содержит оба каталога;
install.sh не перезаписывает ранее изменённый unit. Перезагрузку systemd
выполняйте только при отдельном разрешении на развёртывание.
