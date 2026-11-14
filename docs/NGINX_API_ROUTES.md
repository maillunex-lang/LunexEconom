# Маршруты API в nginx на VPS (обязательно после каждого нового endpoint)

**Проблема 14.11.2026.** Боевой nginx (`https://rikagro.ru/lunexeconom/api/`) пропускал к игровому серверу только часть адресов
(`/health`, `/world`, `/auth/*`, `/events`, `/chunk`, `/build`). Все более новые (`/wallet`, `/market`, `/city*`, `/sell`, `/loan`, `/contracts*`,
`/leaderboard`, `/feed`) получали **404 от самого nginx** и до сервера не доходили. Поэтому в игре «Город» висел на «Загрузка данных города…»,
«События» писали «Ошибка сети», «Контракты» — «Не удалось открыть доску». Серверный код и тесты тут ни при чём: сервер эти адреса обслуживает.
Автообновление (`ops/update_server.py`) меняет только Python-код и **не** трогает nginx — конфиг nginx правится вручную.

## Статус: исправлено 14.11.2026
Файл `/etc/nginx/sites-available/rikagro-game` (резервная копия `/home/gamedev/backups/nginx/rikagro-game.20261114T171519Z.bak`): девять отдельных `location = ...`
и блокирующий `location ^~ /lunexeconom/api/ { return 404; }` заменены одним правилом:
```nginx
location ^~ /lunexeconom/api/ {
    client_max_body_size 4k;
    proxy_pass http://127.0.0.1:18767/;      # завершающий «/» обязателен: /lunexeconom/api/city -> /city
    proxy_set_header Authorization $http_authorization;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_connect_timeout 3s;
    proxy_read_timeout 10s;
    add_header Cache-Control "no-store" always;
}
```
Проверено снаружи (из независимой сети): `health`, `world`, `market`, `city` — 200; `events`, `wallet`, `contracts`, `leaderboard`, `feed` и POST `sell`, `loan`, `city/taxes`,
`contracts/offer` — 401 JSON. Новые endpoint-ы теперь проходят автоматически. Версия сервера в `/health` пока пустая (`commit: null`); развёрнутый SHA лежит в
`/var/lib/lunexeconom-server-update/deployed-sha` на VPS. На VPS `lunexeconom-game` работает на `17394a4`.

Исторический раздел ниже описывает исходную проблему.

## Что сделать на VPS (root)
1. Найти текущую настройку и запомнить, как проксируется `events`/`chunk`:
   ```bash
   grep -rn "lunexeconom" /etc/nginx/sites-enabled/ /etc/nginx/conf.d/ 2>/dev/null
   ```
2. **Простой и рекомендуемый вариант:** заменить список разрешённых адресов одним префиксом с теми же строками `proxy_pass`/`proxy_set_header`,
   что стоят у существующего `events`/`chunk` (сервер сам отвечает 404 на неизвестные адреса и 401 без токена, поэтому белый список в nginx не нужен):
   ```nginx
   location /lunexeconom/api/ {
       # те же proxy_pass (на 127.0.0.1:18767), proxy_set_header, таймауты и лимиты, что у текущего location events/chunk
   }
   ```
   Если нужен именно белый список, разрешить все адреса (точное совпадение, без завершающего слэша):
   ```
   GET : health world events chunk wallet market city contracts leaderboard feed auth/me
   POST: auth/register auth/login auth/logout build sell loan city/taxes city/build city/candidacy city/vote
         contracts/offer contracts/accept contracts/cancel
   ```
3. Проверить конфиг и перезагрузить **только** nginx, не трогая другие сайты:
   ```bash
   nginx -t && systemctl reload nginx
   ```
4. Проверить снаружи: ни один адрес не должен отвечать **404 с HTML от nginx** (правильно: 401 `{"error": "unauthorized"}` или 200 JSON):
   ```bash
   for p in health world events wallet market city contracts leaderboard feed sell loan; do
     printf "%-12s " $p; curl -s -o /dev/null -w "%{http_code}\n" https://rikagro.ru/lunexeconom/api/$p
   done
   ```
   Ожидается: `health 200`, `world 200`, `events/wallet/market/city/contracts/leaderboard/feed 401`, `sell/loan 404 или 405` (это POST-адреса; главное —
   ответ JSON от сервера, а не HTML nginx).

## Правило на будущее
Добавляя endpoint в `server/game_server.py`, проверять его снаружи командой из п. 4 и дописывать адрес сюда.
