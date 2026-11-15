# LunexEconom V2 · Платформа 2.1 (задание V2-01)

Документ относится к рабочей ветке `v2/platform`. **Не запускать на производственном V1**. Единственная БД V2: PostgreSQL 16. Точка входа сохраняется: `python -m server.game_server`, адаптер совместимости `server/auth.py` не удалён. Пакеты изолированы через `Registry`.

## 1. HTTP, пул и эксплуатация

Python 3.12+, Waitress (многопоточный WSGI) и `psycopg_pool`. По умолчанию HTTP слушает **только `127.0.0.1:18777`**, до 32 потоков Waitress, пул PostgreSQL от 2 до 20 соединений. Максимальное тело HTTP 64 КиБ, `statement_timeout=7s`, `lock_timeout=5s`, таймаут ожидания пула 10s, ожидание канала 20s. Параметры окружения: `LUNEX_DATABASE_URL`, `LUNEX_PORT`, `LUNEX_THREADS`, `LUNEX_POOL_MIN`, `LUNEX_POOL_MAX`, `LUNEX_TICK_INTERVAL`, `LUNEX_VERSION`, `LUNEX_SHA`, `LUNEX_ADMIN_TOKEN`, `LUNEX_FLAG_*`. Логи Python без раскрытия входных паролей и токенов.

`GET /health` возвращает `ok`, `database`, `version`, `sha`, `pool: {size, available, waiting}`, `tick` (последний индекс, миллисекунды, ошибка/время завершения). Ошибки БД не раскрывают SQL и секреты клиенту. Автообновлятор V2 `ops/update_server.py` сохраняет дерево `.py`, `.sql`, `.json`, `requirements.txt`; для локальной админ-панели дополнительно упаковывает безопасный статический `server/platform/admin_ui.html`. Проверка CI SHA, бэкап и откат сохранены. **Настройка/запуск обновления и сервисов на VPS не входят в V2-01.**

Для отдельной тестовой БД:

```bash
python -m pip install -r server/requirements.txt
LUNEX_DATABASE_URL=postgresql://USER:PASSWORD@127.0.0.1:PORT/V2_TEST_DB python -m server.game_server
```

Не вставляйте настоящие пароли в историю команд или в репозиторий. В тестах переменная `LUNEX_TEST_DATABASE_URL` должна указывать **только на изолированный тестовый PostgreSQL**.

## 2. Аккаунты, роли и безопасность

Регистрация: `POST /auth/register`:

```json
{"username":"player_001","email":"player@example.com","password":"example_Strong_2026"}
```

Имя ASCII `[A-Za-z0-9_]`, 3–24 символа (без `:`); обязательный корректно оформленный email (до 254 символов, нижний регистр и уникальность), пароль 10–256 символов. Хранение: scrypt с индивидуальной солью. Публичная регистрация всегда даёт роль `player`, никогда `developer` или `admin`.

`POST /auth/login` с `username` или `email` и `password` возвращает `access_token` (30 минут), `refresh_token` (30 дней), `expires_in:1800`, роль и ID. Для совместимости поле `token` совпадает с access-токеном. Доступ проверяется заголовком `Authorization: Bearer ACCESS_TOKEN`.

`POST /auth/refresh`:

```json
{"refresh_token":"REFRESH_TOKEN"}
```

Возвращает новую пару, предыдущая сразу отзывается в транзакции с блокировкой строки, повторное использование запрещено. `POST /auth/logout` с авторизованным заголовком или refresh-токеном отзывает сессию. `GET /auth/me` и `GET /me` возвращают профиль. Заблокированные аккаунты не авторизуются; при блокировке текущие сессии отзываются. По логину и регистрации действует PostgreSQL-ограничение по идентификатору и IP (окно 15 минут, 8 входов / 10 регистраций); `429` означает срабатывание защиты.

Если перед сервером стоит собственный nginx, для лимитов по реальному адресу можно явно включить `LUNEX_TRUST_PROXY_REAL_IP=1` **только после настройки nginx на перезапись** `X-Real-IP` из доверенного `$remote_addr`. Никогда не доверять пользовательскому `X-Forwarded-For` как источнику IP.

CLI ролей (все операции пишут аудит):

```bash
python -m server.platform.accounts_admin list player_001
python -m server.platform.accounts_admin grant player_001 developer
python -m server.platform.accounts_admin grant player_001 admin
python -m server.platform.accounts_admin revoke player_001
```

Оператор выполняет CLI только в защищённой среде с `LUNEX_DATABASE_URL`; назначения роли через публичный API нет.

## 3. Двойная бухгалтерия

Счета: `player:<имя>`, `company:<id>`, `city:<id>`, `system:treasury`, `system:market`, `system:bank`, `system:upkeep`, `system:escrow`. Системные счета созданы миграцией, могут уходить в минус; пользовательские, городские и корпоративные счета не могут. Целые игровые рубли `bigint`, никакого float. `server.ledger.api.post(conn, request_id, entries)` принимает от 2 до 128 строк `(account_id, integer_delta)`, требует `sum(delta)=0`, фиксирует уникальный `request_id`; повтор с теми же строками возвращает исходный ID без второго списания. Блокировка счетов идёт в стабильном порядке `id` под `FOR UPDATE`. `transfer()` остаётся доступной обёрткой.

При регистрации счёт игрока получает **300 000 игровых ₽** из `system:treasury` ровно одной транзакцией `initial-capital:<account_id>`; сумма балансов всей системы остаётся нулевой. `reconcile(conn)` возвращает флаги и количество расхождений по балансу счёта, строкам и общей сумме.

`GET /ledger/balance` требует access-токен, возвращает `{account_id,balance,currency:"RUB",unit:"game_ruble"}`. `GET /ledger/history?page=1&limit=25` требует токен; `limit` 1–100, упорядочено по убыванию ID проводки.

## 4. Игровые часы и тики

ADR-001: **48 реальных минут = игровой день**, 30 дней = игровой месяц (24 реальных часа). Первый запуск нового V2 мира создаёт эпоху в ближайшие 09:00 по Уфе (Asia/Yekaterinburg, UTC+5). Сохранённая эпоха не переписывается при перезапуске. `GET /clock` возвращает `year`, `month`, `month_index`, `day`, `day_index`, `seconds_until_month`, `next_boundary_ufa`, `seconds_until_start`, `tick`.

`registry.tick('daily'|'monthly', name, handler, order=100)` сортирует обработчики по `(order,name)`. На **каждый день отдельная транзакция** и `pg_try_advisory_xact_lock`, безопасная между процессами. Суточные обработчики, затем в день `day_index % 30 == 0` месячные обработчики. Результат записывается атомарно в `game_ticks(day_index, started_at, finished_at, duration_ms, handlers, error, completed)` и совместимую `tick_receipts`. При исключении откатываются действия только текущего дня, сохраняется диагностическая запись, следующий запуск повторяет день. Обработанные дни не повторяются. Один проход обрабатывает максимум 5 пропущенных дней; фоновый поток повторяет до устранения отставания, по умолчанию через 5 секунд. Тик длиннее 2 секунд оставляет `WARNING` в журнале.

## 5. Настройки и подписанный конфиг

Флаги объявляются через `registry.flag(name,default,min_value=None,max_value=None)`. Приоритет: **код → `LUNEX_FLAG_*` (JSON) → база**. Тип строго совпадает с типом значения по умолчанию; для чисел доступны границы. Изменение настройкой админки создаёт `runtime_revisions` и запись `audit`; `apply_at=now` действует сразу при следующем запросе, `apply_at=next_month` только с нового игрового месяца. Откат создаёт **новую** ревизию, история не перезаписывается. Старые значения `runtime_config` V2-00 читаются как слой совместимости.

Публичный `GET /config` до первой подписи возвращает `503 config_not_signed`; после публикации `{schema:1,revision,payload_b64,signature}`. `payload_b64` содержит **канонический JSON** (`sort_keys`, компактные разделители, UTF-8). RSA PKCS#1 v1.5 SHA-256 подпись делается **только операторским инструментом**:

```bash
python tools/sign_config.py --private-key /secure/config-private.pem --payload docs/config_example.json
```

Закрытый ключ не должен попадать в Git, логи, APK и ответы API. Пример разработки: в `client/security/config_public.pem` помещён **тестовый публичный ключ**; сопряжённый закрытый ключ создан отдельно в домашнем каталоге `gamedev` с правами `0600`. **Перед промышленным выпуском ключи необходимо заменить собственным комплектом владельца, обновить публичный ключ в клиенте и собрать новый APK.** Godot клиент проверяет SHA-256 и RSA `Crypto.verify()` по закреплённому PEM; неподписанные и откатные ревизии отвергает. Новые версии приложения публикуются только через APK, не через загрузку исполняемого кода.

## 6. Присутствие и админка

`presence`: отметка активности авторизованного пользователя не чаще 30 секунд; `presence_daily_peak` хранит максимальный онлайн за текущие сутки. `/admin/overview`: версия/SHA, uptime, БД, состояние пула/последнего тика, онлайн, пик, число игроков, ошибки тиков. `/admin/flags`, `GET/POST /admin/settings`, `/admin/revisions`, `POST /admin/revisions/rollback`, `/admin/audit`, `POST /admin/accounts/block`.

**Защита:** сервер принимает `/admin/*` только с адреса loopback, при локальном `Host` и `X-Admin-Token` из `LUNEX_ADMIN_TOKEN` (не короче 24 символов). Неправильный токен, публичный Host, forwarded-заголовки или внешний клиент → HTTP 403. API изменяет данные только после проверки; пишет аудит. Нельзя публиковать путь `/admin` в nginx.

Статическая панель доступна локально по `http://127.0.0.1:18777/operator-ui` через SSH-туннель; страница содержит только клиентский HTML/JS. Токен вводится вручную и хранится только в памяти вкладки, без localStorage. Сам HTML тоже выдаётся только на loopback и локальный Host.

## 7. Android

Godot 4.7, только горизонтальная ориентация, safe area, Forest Glass. Регистрация требует email. Refresh-токен хранится в закрытом для приложения `user://platform_session.cfg`, access-токен только в оперативной памяти; при запуске и после HTTP 401 клиент обновляет токены, при выходе стирает локальный токен и отзывает серверный. Штаб-квартира получает `/ledger/balance` и `/clock`. Кнопка «Проверить обновление» запрашивает `/config`, сверяет RSA/ревизию и отображает доступную подписанную версию. Для промышленной защиты устройства рекомендована последующая интеграция с Android Keystore. Клиент **не** скачивает и не выполняет произвольный код.

## 8. Тесты и честные ограничения

```bash
LUNEX_TEST_DATABASE_URL=postgresql://... LUNEX_DATABASE_URL=postgresql://... \
  python -m unittest discover -s server/tests -v
python -m unittest discover -s ops -p 'test_*.py' -v
LUNEX_TEST_DATABASE_URL=postgresql://... LUNEX_DATABASE_URL=postgresql://... \
  python -m server.tests.load_test
# Запуск клиента: Godot 4.7 --headless --path client -s tests/smoke.gd
```

Интеграционные проверки охватывают авторизацию/ротацию/блокировку/роли/лимиты, сверку, 10 000 проводок, блокировку конкурентных списаний, 3 дня догонки/откат/повтор, флаги/ревизии/подпись, loopback и админ-токен, фоновый поток, реальный Waitress под 100 одновременных запросов обоих маршрутов. Все тестовые БД отделены от производственной.

**Ограничения этой задачи:** нет развёртывания части C, нет миграции V1 и данных, нет production-ключей, нет готового механизма удалённой подгрузки подписанных PCK/GLB-контент-патчей. Проверка подписанной конфигурации и версии реализована; механизм патчей станет отдельным этапом при наличии точного формата и доверенного манифеста.
