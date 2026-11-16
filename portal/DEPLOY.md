# CreatePortal: развёртывание на VPS (rikagro.ru/createportal)

Только по прямой команде владельца, через исполнителя VPS. Секреты (пароль владельца, токен GitHub) в чат не присылаются: пароль владелец вводит сам на сервере, токен кладёт в файл сам.

## Состав
Один процесс Python 3.12 (только стандартная библиотека), SQLite, слушает 127.0.0.1:18790. Наружу через nginx по HTTPS на `/createportal/`. Данные: `/var/lib/createportal/portal.sqlite` (права 0700, пользователь `createportal`).

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
