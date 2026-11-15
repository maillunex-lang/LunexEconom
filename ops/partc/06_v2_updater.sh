#!/usr/bin/env bash
# Часть C, шаг 6: ОТДЕЛЬНЫЙ автообновитель V2 + проверка V2 через публичный адрес.
# Обновитель V2 следит за GitHub main, выкладывает ТОЛЬКО в /opt/lunexeconom-v2 и перезапускает ТОЛЬКО lunexeconom-v2.service,
# и только если на ТОЧНО этом коммите зелёный server-check. При сбое health откатывает. V1 он не знает и не трогает.
# Пробный запуск:  sudo DRY_RUN=1 bash 06_v2_updater.sh
# Боевой запуск:   sudo bash 06_v2_updater.sh > step6-report.txt 2>&1
set -euo pipefail
DRY="${DRY_RUN:-0}"
say() { echo "[step6] $*"; }
[ "$(id -u)" = 0 ] || { echo "run as root (sudo)"; exit 1; }
APP=/opt/lunexeconom-v2; STATE=/var/lib/lunexeconom-v2-update

say "pre-checks"
[ "$(curl -s -m 8 -o /dev/null -w '%{http_code}' http://127.0.0.1:18777/health)" = 200 ] || { echo "V2 is not healthy, stop"; exit 1; }
[ -f "$APP/ops/update_server.py" ] || { echo "$APP/ops/update_server.py missing (step 4 not done?)"; exit 1; }
if systemctl is-active --quiet lunexeconom-server-update.timer; then echo "OLD V1 updater timer is still active, stop it first: systemctl stop lunexeconom-server-update.timer"; exit 1; fi
[ -e /etc/systemd/system/lunexeconom-v2-update.service ] && { echo "lunexeconom-v2-update.service already exists"; exit 1; }
say "V1 health: $(curl -s -m 8 -o /dev/null -w '%{http_code}' http://127.0.0.1:18767/health)"
if [ "$DRY" = 1 ]; then say "DRY RUN: would install lunexeconom-v2-update.service/.timer (every 5 min) and run it once"; exit 0; fi

cat > /etc/systemd/system/lunexeconom-v2-update.service <<UNIT
[Unit]
Description=LunexEconom V2 server auto-update from GitHub main (CI-gated, with rollback)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=root
Group=root
Environment=LUNEX_REPO=maillunex-lang/LunexEconom
Environment=LUNEX_SERVER_DIR=$APP/server
Environment=LUNEX_UPDATE_STATE=$STATE
Environment=LUNEX_SERVICES=lunexeconom-v2.service
Environment=LUNEX_HEALTH_URL=http://127.0.0.1:18777/health
Environment=LUNEX_SERVER_USER=gamedev
ExecStart=/usr/bin/flock -n /run/lock/lunexeconom-v2-update.lock /usr/bin/python3 $APP/ops/update_server.py
TimeoutStartSec=240
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=$APP $STATE /run/lock
UNIT
cat > /etc/systemd/system/lunexeconom-v2-update.timer <<UNIT
[Unit]
Description=Check GitHub main for validated LunexEconom V2 server updates

[Timer]
OnBootSec=4min
OnUnitActiveSec=5min
RandomizedDelaySec=20s
Persistent=true
Unit=lunexeconom-v2-update.service

[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
say "running the V2 updater once (it deploys only if main has a green server-check)"
systemctl start lunexeconom-v2-update.service || true
journalctl -u lunexeconom-v2-update.service -n 15 --no-pager -o cat | sed -E 's#(postgres(ql)?://[^:/@ ]+:)[^@ ]+@#\1***@#g'
systemctl enable --now lunexeconom-v2-update.timer
say "timer: $(systemctl is-active lunexeconom-v2-update.timer) | V2 service: $(systemctl is-active lunexeconom-v2.service)"
say "V2 health after: $(curl -s -m 8 http://127.0.0.1:18777/health | head -c 300)"
say "V1 health after: $(curl -s -m 8 -o /dev/null -w '%{http_code}' http://127.0.0.1:18767/health)"

say "read-only smoke through the public route"
H="--resolve rikagro.ru:443:127.0.0.1"; B=https://rikagro.ru/lunexeconom/v2/api
for path in /health /catalog /world/cities; do printf '%s -> ' "$path"; curl -sk $H -m 10 -o /dev/null -w '%{http_code} %{content_type}\n' "$B$path" || true; done
ET=$(curl -sk $H -m 10 -D - -o /dev/null "$B/catalog" | tr -d '\r' | awk -F': ' 'tolower($1)=="etag"{print $2}')
[ -n "$ET" ] && printf 'catalog with If-None-Match -> ' && curl -sk $H -m 10 -o /dev/null -w '%{http_code}\n' -H "If-None-Match: $ET" "$B/catalog"
printf 'cities count -> '; curl -sk $H -m 10 "$B/world/cities" | python3 -c 'import json,sys; d=json.load(sys.stdin); c=d.get("cities",d) if isinstance(d,dict) else d; print(len(c))' 2>&1 | tail -1

cat <<'NOTE'

[step6] DONE. Notes:
 - The updater file /opt/lunexeconom-v2/ops/update_server.py is NOT updated automatically; copy it manually when it changes in main.
 - If server/requirements.txt changes, the new packages are NOT installed automatically: run
     sudo -u gamedev /opt/lunexeconom-v2/venv/bin/pip install -r /opt/lunexeconom-v2/server/requirements.txt
   (a deploy with missing packages fails the health check and is rolled back).
 - Remove this step: systemctl disable --now lunexeconom-v2-update.timer; rm /etc/systemd/system/lunexeconom-v2-update.*; systemctl daemon-reload
NOTE
