# Админка A1

Админка доступна отдельным маршрутом `/admin/*` и не является частью игрового `/api/`. В браузере используется статическая панель `web/admin/`; API адрес задаётся в `web/admin/config.js`.

## Роли

| Роль | Права |
|---|---|
| `viewer` | просмотр обзора, игроков и аудита |
| `support` | просмотр, блокировка игроков и компенсации в пределах `support_compensation_limit` |
| `admin` | права support плюс настройки, флаги, ревизии и откат |
| `owner` | все права, включая выдачу ролей и смену собственного пароля |

Вход выполняется логином/почтой и паролем не короче 14 символов. Сессия хранится только хэшем токена, действует 60 минут и продлевается активностью максимум до 8 часов. Неудачные входы ограничиваются по IP и идентификатору. Второй фактор не используется по решению владельца. Аварийный `X-Admin-Token` сохраняется только для loopback и пишет в аудит actor `admin:loopback`.

## Маршруты A1

`POST /admin/login`, `POST /admin/logout`, `POST /admin/password`, `GET /admin/overview`, `GET /admin/players?q=`, `GET /admin/players/{id}`, `POST /admin/players/{id}/block|unblock|compensate`, `POST /admin/sessions/revoke`, `GET|POST /admin/settings`, `GET /admin/flags`, `GET /admin/revisions`, `POST /admin/revisions/rollback`, `GET /admin/audit`, `POST /admin/roles`.

Компенсация всегда идёт через ledger, требует целую ненулевую сумму, причину, ссылку на обращение и идемпотентный `request_id`. Повтор с тем же request_id не создаёт новую проводку; баланс игрока не может уйти в минус.

## Первый owner и откат

Первого владельца создаёт операторской командой на сервере: `python -m server.platform.accounts_admin grant <логин> owner`. Команда не входит в веб API. Откат настройки выполняется через `POST /admin/revisions/rollback` с номером ревизии; создаётся новая ревизия, история не перезаписывается.

Рекомендуется ограничить отдельный nginx маршрут `/admin/` HTTPS и allow-list адресов. Сама панель не публикуется этим этапом.
