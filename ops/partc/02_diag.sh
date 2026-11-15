#!/usr/bin/env bash
# Часть C, шаг 2: ДИАГНОСТИКА автообновлений V1. Только чтение, ничего не меняет.
# Запуск на VPS:  sudo bash 02_diag.sh > diag.txt     Перед отправкой просмотри diag.txt: пароли маскируются.
set -u
mask() { sed -E 's/((PASS(WORD)?|SECRET|TOKEN|KEY|DSN|DATABASE_URL)[A-Za-z0-9_]*[=:] *)[^ ]+/\1***MASKED***/Ig; s#(postgres(ql)?://[^:/@ ]+:)[^@ ]+@#\1***MASKED***@#g'; }
sec() { printf '\n===== %s =====\n' "$1"; }
V1=/home/gamedev/projects/LunexEconom-server
sec "time"; date -u +%FT%TZ
sec "timer schedules"
for t in lunexeconom-server-update lunexeconom-deploy lunexeconom-main-sync lunexeconom-backup; do echo "--- $t.timer"; systemctl cat "$t.timer" 2>/dev/null | grep -E '^(OnCalendar|OnBootSec|OnUnitActiveSec|OnUnitInactiveSec)'; systemctl list-timers "$t.timer" --no-legend 2>/dev/null | head -1; done
sec "journal of updaters, last 24h (tail 60 each)"
for u in lunexeconom-server-update lunexeconom-deploy lunexeconom-main-sync; do echo "--- $u"; journalctl -u "$u" --since "-24h" --no-pager -o short-iso 2>/dev/null | tail -60 | mask; done
sec "game service journal, last 3h (tail 60)"
journalctl -u lunexeconom-game --since "-3h" --no-pager -o short-iso 2>/dev/null | tail -60 | mask
sec "health"
curl -s -m 8 http://127.0.0.1:18767/health | head -c 400; echo
curl -s -m 8 -o /dev/null -w "public api health http=%{http_code}\n" https://rikagro.ru/lunexeconom/api/health
sec "V1 server directory: is it still V1 or already V2 code?"
ls -la --time-style=long-iso "$V1" 2>/dev/null | head -40
for m in registry.py platform clock world catalog enterprises ledger; do [ -e "$V1/$m" ] && echo "V2 marker present: $m" || echo "absent: $m"; done
sec "updater state and backups (names only)"
ls -la --time-style=long-iso /var/lib/lunexeconom-server-update 2>/dev/null | head -30
ls -la --time-style=long-iso /var/lib/lunexeconom-server-update/backups 2>/dev/null | tail -12
for f in /var/lib/lunexeconom-server-update/*.json; do [ -f "$f" ] && { echo "--- $f"; head -c 600 "$f" | mask; echo; }; done
sec "what deploy.py and sync.py do (first 45 lines each)"
for f in /opt/lunexeconom-deploy/deploy.py /opt/lunexeconom-main-sync/sync.py; do echo "--- $f"; head -45 "$f" 2>/dev/null | mask; done
sec "updater instance used by the timer (ExecStart and Environment names only)"
systemctl show lunexeconom-server-update.service -p ExecStart -p Environment -p EnvironmentFiles 2>/dev/null | sed -E 's/=[^ ]*(=)/=\1/' | mask
sec "databases: docker and postgres clusters (read-only)"
(command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}  {{.Image}}  {{.Ports}}' 2>/dev/null) || echo "docker not available"
(command -v pg_lsclusters >/dev/null 2>&1 && pg_lsclusters) || echo "pg_lsclusters not available"
ls /etc/postgresql 2>/dev/null
sec "static site root for /lunexeconom/"
ls -la --time-style=long-iso /var/www/rikagro-game/lunexeconom 2>/dev/null | head -20
grep -n -E "location .*lunexeconom" -A3 /etc/nginx/sites-enabled/* 2>/dev/null | head -40
sec "end"; echo done
