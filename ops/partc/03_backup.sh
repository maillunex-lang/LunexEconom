#!/usr/bin/env bash
# Часть C, шаг 3: РЕЗЕРВНАЯ КОПИЯ V1 перед любыми изменениями. Старые данные не меняет и не удаляет.
# Создаёт новый каталог /root/lunex-partc-backup-<время> (права 0700) и кладёт туда копии. Секретные .env-файлы НЕ копируются.
# Запуск на VPS:  sudo bash 03_backup.sh > backup-report.txt
set -euo pipefail
DEST="/root/lunex-partc-backup-$(date -u +%Y%m%d-%H%M%S)"
V1_DIR=/home/gamedev/projects
DB_CONTAINER=lunexeconom-postgres
umask 077
mkdir -p "$DEST"; echo "backup dir: $DEST"
echo "--- free disk (need several GB):"; df -h /root | tail -1

echo "--- 1. PostgreSQL V1 (container $DB_CONTAINER), custom-format dumps"
docker inspect "$DB_CONTAINER" >/dev/null
DBS=$(docker exec "$DB_CONTAINER" sh -c 'psql -U "$POSTGRES_USER" -d postgres -Atc "select datname from pg_database where not datistemplate"')
for db in $DBS; do
  f="$DEST/pg-$db.dump"
  docker exec "$DB_CONTAINER" sh -c "pg_dump -U \"\$POSTGRES_USER\" -Fc \"$db\"" > "$f"
  n=$(docker exec -i "$DB_CONTAINER" pg_restore -l < "$f" | wc -l)
  echo "db=$db size=$(du -h "$f" | cut -f1) restore-list-entries=$n"
  [ "$n" -gt 5 ] || { echo "FAIL: dump of $db looks empty"; exit 1; }
done
docker exec "$DB_CONTAINER" sh -c 'pg_dumpall -U "$POSTGRES_USER" --globals-only' > "$DEST/pg-globals.sql"

echo "--- 2. V1 server and runtime code (without .venv)"
tar -C "$V1_DIR" --exclude=.venv --exclude=__pycache__ -czf "$DEST/v1-projects.tgz" LunexEconom-server LunexEconom-runtime 2>/dev/null || tar -C "$V1_DIR" --exclude=.venv --exclude=__pycache__ -czf "$DEST/v1-projects.tgz" LunexEconom-server
echo "--- 3. nginx configuration"
tar -C /etc -czf "$DEST/nginx-etc.tgz" nginx
echo "--- 4. systemd units and updaters (no env files)"
mkdir -p "$DEST/systemd"; cp -a /etc/systemd/system/lunexeconom-* "$DEST/systemd/" 2>/dev/null || true
tar -czf "$DEST/opt-updaters.tgz" -C /opt lunexeconom-deploy lunexeconom-main-sync 2>/dev/null || true
tar -czf "$DEST/updater-state.tgz" -C /var/lib lunexeconom-server-update lunexeconom-deploy 2>/dev/null || true
echo "--- 5. static site root of /lunexeconom/"
tar -czf "$DEST/webroot-lunexeconom.tgz" -C /var/www/rikagro-game lunexeconom 2>/dev/null || true

echo "--- checksums and sizes"
( cd "$DEST" && sha256sum * 2>/dev/null | tee SHA256SUMS && du -sh . )
echo "--- state of services (unchanged)"
systemctl is-active lunexeconom-game nginx 2>/dev/null || true
echo "NOTE: .env files in /etc/lunexeconom/* were NOT copied; keep them as they are."
echo "DONE. Keep $DEST until V2 is accepted. Do not paste dump files anywhere."
