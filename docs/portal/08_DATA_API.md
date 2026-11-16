# 08. Данные и API

## Таблицы SQLite [v1]
`users(id, username, pw_hash, created)`; `sessions(token_hash, user_id, csrf, expires)`; `attempts(ip, ts)`; `projects(slug, name, repo, description, plan_json, plan_updated, created)`; `task_state(project_slug, pkg_id, status, issued_at, submitted_at, accepted_at, merged, sha, note)`; `ideas(id, project_slug, text, created, done)`; `start_state(project_slug, prompt_id, done, ts)`; `audit(id, ts, action, payload)`.
**[v2]:** `events(id, project_slug, pkg_id, ts, kind, source, payload)`, `pr_links(project_slug, pkg_id, pr_number, branch, sha, state, ci_state, updated)`, `reports(project_slug, pkg_id, text, ts)`, `review_checks(project_slug, pkg_id, item, done, ts)`, `project_settings(project_slug, auto_accept, auto_accept_require_checklist, required_checks)`, `settings(key, value)`, `notify_channels(channel, chat_id, bound_at)` (идентификатор чата владельца, токены не хранятся в базе), `notify_codes(code_hash, channel, expires)`, `notify_log(kind, key, ts, channel, ok)`, `webhook_deliveries(delivery_id, ts)`.
**[v3]:** `users` с ролями, `memberships(user_id, project_slug, role)`, `invites`, `comments`.
Миграции: `CREATE TABLE IF NOT EXISTS` и таблица версий схемы [v2]; данные не теряются при обновлении.

## Маршруты v1 (префикс `/createportal`)
| Метод и путь | Что делает |
|---|---|
| GET `/health` | проверка живости (без входа) |
| GET `/` | страница портала |
| POST `/api/login`, `/api/logout`; GET `/api/me` | вход, выход, текущий пользователь и CSRF |
| GET `/api/protocol` | текст протокола для ИИ |
| GET/POST `/api/projects` | список и создание проекта (ответ содержит два промпта) |
| GET `/api/projects/{slug}` | проект, план с промптами, состояние, идеи, старт |
| GET `/api/projects/{slug}/bootstrap`, `/bootstrap.zip` | промпты и скелет |
| POST `/api/projects/{slug}/plan` | загрузить план (проверка валидатором) |
| POST `/api/projects/{slug}/sync` | получить план из GitHub |
| POST `/api/projects/{slug}/status` | сменить статус задачи |
| POST `/api/projects/{slug}/start` | отметить стартовый промпт |
| POST `/api/projects/{slug}/ideas` | добавить идею или отметить учтённой |

## Маршруты v2
`POST /hook/github` (вебхук), `GET /api/projects/{slug}/events`, `GET/POST /api/projects/{slug}/tasks/{id}/report`, `POST .../tasks/{id}/review` (чек-лист), `GET /api/projects/{slug}/graph`, `GET /api/metrics`, `GET/POST /api/settings`, `GET /api/audit`, `POST /api/backup`, `DELETE /api/projects/{slug}`.

## Коды ответов
200 успех, 201 создано, 400 неверный запрос, 401 нужен вход или неверные данные, 403 нет CSRF или прав, 404 нет объекта, 409 конфликт (занят адрес, зависимости не приняты), 422 план с ошибками (список `details`), 429 лимит попыток, 502 не удалось получить план из GitHub.

## Идемпотентность и согласованность
Смена статуса идемпотентна (повтор того же статуса безопасен); вебхуки защищены от повторов по идентификатору доставки; записи состояния выполняются в одной транзакции SQLite (WAL).
