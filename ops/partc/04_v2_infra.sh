#!/usr/bin/env bash
# Часть C, шаг 4: ИНФРАСТРУКТУРА V2 рядом с V1. V1, его база, nginx и таймеры НЕ затрагиваются.
# Создаёт: отдельный контейнер PostgreSQL 16 (127.0.0.1:15459), базу lunex_v2 и роль lunex_v2_app,
# каталог /opt/lunexeconom-v2 с кодом сервера и venv, секреты в /etc/lunexeconom-v2 (не выводятся на экран),
# сервис lunexeconom-v2.service на 127.0.0.1:18777.
# Пробный запуск без изменений:  sudo DRY_RUN=1 bash 04_v2_infra.sh
# Боевой запуск:                 sudo bash 04_v2_infra.sh > step4-report.txt 2>&1
set -euo pipefail
REPO=maillunex-lang/LunexEconom
PORT=18777; PGPORT=15459
APP=/opt/lunexeconom-v2; ENVDIR=/etc/lunexeconom-v2; STATE=/var/lib/lunexeconom-v2-update
PGC=lunexeconom-v2-postgres; VOL=lunexeconom-v2-pgdata; SVC=lunexeconom-v2.service
DRY="${DRY_RUN:-0}"
say() { echo "[step4] $*"; }
run() { if [ "$DRY" = 1 ]; then echo "[dry-run] $*"; else eval "$@"; fi; }

[ "$(id -u)" = 0 ] || { echo "run as root (sudo)"; exit 1; }
say "V1 health before: $(curl -s -m 8 -o /dev/null -w '%{http_code}' http://127.0.0.1:18767/health)"

say "pre-checks (abort on any conflict)"
command -v docker >/dev/null || { echo "docker not found"; exit 1; }
id gamedev >/dev/null || { echo "user gamedev not found"; exit 1; }
python3 -c "import venv, ensurepip" 2>/dev/null || { echo "python3-venv missing: apt install python3-venv"; exit 1; }
for p in $PORT $PGPORT; do ss -ltn | awk '{print $4}' | grep -qE "[:.]$p$" && { echo "port $p already in use"; exit 1; }; done
docker inspect "$PGC" >/dev/null 2>&1 && { echo "container $PGC already exists"; exit 1; }
for d in "$APP" "$ENVDIR" "$STATE"; do [ -e "$d" ] && { echo "$d already exists, refusing to overwrite"; exit 1; }; done
[ -e /etc/systemd/system/$SVC ] && { echo "$SVC already exists"; exit 1; }
say "pre-checks passed"

if [ "$DRY" = 1 ]; then
  say "DRY RUN: would create dirs, a PostgreSQL container $PGC on 127.0.0.1:$PGPORT, role/database, env files, venv, unit $SVC, start it on :$PORT"
  exit 0
fi

umask 027
install -d -m 0750 -o root -g gamedev "$ENVDIR"
install -d -m 0755 -o gamedev -g gamedev "$APP" "$STATE"

say "generating secrets (not printed)"
ADMINPW=$(openssl rand -hex 24); APPPW=$(openssl rand -hex 24); ADMINTOKEN=$(openssl rand -hex 24)
( umask 077; printf 'POSTGRES_USER=lunex_v2_admin\nPOSTGRES_PASSWORD=%s\nPOSTGRES_DB=postgres\n' "$ADMINPW" > "$ENVDIR/pg-admin.env"; chown root:root "$ENVDIR/pg-admin.env" )

say "starting separate PostgreSQL 16 container $PGC"
docker run -d --name "$PGC" --restart unless-stopped -p 127.0.0.1:$PGPORT:5432 -v "$VOL":/var/lib/postgresql/data --env-file "$ENVDIR/pg-admin.env" postgres:16-alpine >/dev/null
for i in $(seq 1 40); do docker exec "$PGC" pg_isready -U lunex_v2_admin -d postgres >/dev/null 2>&1 && break; sleep 2; done
docker exec "$PGC" pg_isready -U lunex_v2_admin -d postgres >/dev/null || { echo "PostgreSQL did not become ready"; exit 1; }

say "creating role lunex_v2_app and database lunex_v2 (V1 databases are in another container)"
docker exec -i "$PGC" psql -U lunex_v2_admin -d postgres -v ON_ERROR_STOP=1 >/dev/null <<SQL
CREATE ROLE lunex_v2_app LOGIN PASSWORD '$APPPW';
CREATE DATABASE lunex_v2 OWNER lunex_v2_app;
REVOKE ALL ON DATABASE lunex_v2 FROM PUBLIC;
SQL

say "downloading V2 server from GitHub main"
SHA=$(curl -fsS -m 20 "https://api.github.com/repos/$REPO/commits/main" | python3 -c 'import json,sys; print(json.load(sys.stdin)["sha"])')
say "main sha: $SHA"
TMP=$(mktemp -d); curl -fsSL -m 120 "https://codeload.github.com/$REPO/tar.gz/$SHA" -o "$TMP/src.tgz"
tar -xzf "$TMP/src.tgz" -C "$TMP"; SRC=$(ls -d "$TMP"/LunexEconom-*)
cp -a "$SRC/server" "$APP/server"; mkdir -p "$APP/ops"; cp -a "$SRC/ops/update_server.py" "$APP/ops/"
chown -R gamedev:gamedev "$APP"; rm -rf "$TMP"

say "creating virtualenv and installing dependencies"
sudo -u gamedev python3 -m venv "$APP/venv"
sudo -u gamedev "$APP/venv/bin/pip" install -q --upgrade pip
sudo -u gamedev "$APP/venv/bin/pip" install -q -r "$APP/server/requirements.txt"
sudo -u gamedev "$APP/venv/bin/python" -c "import psycopg, psycopg_pool, waitress, jsonschema, cryptography; print('dependencies ok')"

say "writing application environment (secrets stay in the file)"
( umask 037; cat > "$ENVDIR/v2.env" <<ENV
LUNEX_DATABASE_URL=postgresql://lunex_v2_app:$APPPW@127.0.0.1:$PGPORT/lunex_v2
LUNEX_PORT=$PORT
LUNEX_ADMIN_TOKEN=$ADMINTOKEN
LUNEX_TRUST_PROXY_REAL_IP=1
LUNEX_VERSION=2.1
LUNEX_SHA=$SHA
ENV
chown root:gamedev "$ENVDIR/v2.env"; chmod 0640 "$ENVDIR/v2.env" )

say "installing systemd unit $SVC"
cat > /etc/systemd/system/$SVC <<UNIT
[Unit]
Description=LunexEconom V2 game server
After=network-online.target docker.service
Wants=network-online.target

[Service]
User=gamedev
Group=gamedev
WorkingDirectory=$APP
EnvironmentFile=$ENVDIR/v2.env
ExecStart=$APP/venv/bin/python -m server.game_server
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now $SVC
for i in $(seq 1 30); do curl -fsS -m 3 http://127.0.0.1:$PORT/health >/dev/null 2>&1 && break; sleep 2; done

say "V2 health (local only):"; curl -fsS -m 8 http://127.0.0.1:$PORT/health || { echo; echo "V2 FAILED to start. Last log lines:"; journalctl -u $SVC -n 30 --no-pager | sed -E 's#(postgres(ql)?://[^:/@ ]+:)[^@ ]+@#\1***@#g'; exit 1; }
echo
say "V1 health after: $(curl -s -m 8 -o /dev/null -w '%{http_code}' http://127.0.0.1:18767/health)"
say "V2 service state: $(systemctl is-active $SVC)"
cat <<'ROLLBACK'

[step4] DONE. V1 was not touched. To REMOVE everything created by this step (only if needed):
  systemctl disable --now lunexeconom-v2.service
  docker rm -f lunexeconom-v2-postgres && docker volume rm lunexeconom-v2-pgdata
  rm -rf /opt/lunexeconom-v2 /etc/lunexeconom-v2 /var/lib/lunexeconom-v2-update /etc/systemd/system/lunexeconom-v2.service && systemctl daemon-reload
ROLLBACK
