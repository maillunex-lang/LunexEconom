#!/usr/bin/env bash
# Часть C, шаг 7: заменить файл автообновителя V2 на сервере версией из репозитория (main).
# 1) делает копию текущего файла; 2) скачивает версию из GitHub main и проверяет синтаксис;
# 3) добавляет systemd-разрешение записи в /etc/lunexeconom-v2 (нужно, чтобы обновитель менял только строку LUNEX_SHA);
# 4) заменяет файл атомарно и один раз запускает обновитель. Откат: вернуть копию и перезапустить таймер.
# Пробный запуск:  sudo DRY_RUN=1 bash 07_replace_updater.sh
# Боевой запуск:   sudo bash 07_replace_updater.sh > step7-report.txt 2>&1
set -euo pipefail
DRY="${DRY_RUN:-0}"
say() { echo "[step7] $*"; }
[ "$(id -u)" = 0 ] || { echo "run as root (sudo)"; exit 1; }
REPO=maillunex-lang/LunexEconom
TARGET=/opt/lunexeconom-v2/ops/update_server.py
ENVF=/etc/lunexeconom-v2/v2.env
UNIT=lunexeconom-v2-update.service
DROPIN=/etc/systemd/system/$UNIT.d/10-env-write.conf
[ -f "$TARGET" ] || { echo "$TARGET not found"; exit 1; }
[ -f "$ENVF" ] || { echo "$ENVF not found"; exit 1; }

SHA=$(curl -fsS -m 20 "https://api.github.com/repos/$REPO/commits/main" | python3 -c 'import json,sys; print(json.load(sys.stdin)["sha"])')
say "main sha: $SHA"
TMP=$(mktemp); curl -fsSL -m 30 "https://raw.githubusercontent.com/$REPO/$SHA/ops/update_server.py" -o "$TMP"
python3 -m py_compile "$TMP" && say "downloaded file: syntax ok ($(wc -l < "$TMP") lines)"
grep -q "LUNEX_ENV_FILE" "$TMP" || { echo "downloaded file lacks LUNEX_ENV_FILE support, stop"; exit 1; }
say "differences (line counts only, no content shown): current $(wc -l < "$TARGET") -> new $(wc -l < "$TMP")"
say "V2 health before: $(curl -s -m 8 http://127.0.0.1:18777/health | head -c 200)"
say "V1 health before: $(curl -s -m 8 -o /dev/null -w '%{http_code}' http://127.0.0.1:18767/health)"
if [ "$DRY" = 1 ]; then say "DRY RUN: would back up $TARGET, install the new file, add $DROPIN and run the updater once"; rm -f "$TMP"; exit 0; fi

BK="$TARGET.before-repo-sync.$(date -u +%Y%m%d-%H%M%S)"
cp -a "$TARGET" "$BK"; say "backup: $BK"
if ! systemctl show "$UNIT" -p ReadWritePaths | grep -q "/etc/lunexeconom-v2"; then
  mkdir -p "$(dirname "$DROPIN")"
  printf '[Service]\nReadWritePaths=/etc/lunexeconom-v2\n' > "$DROPIN"
  say "added systemd drop-in $DROPIN"
fi
install -m 0644 -o root -g root "$TMP" "$TARGET.new" && mv -f "$TARGET.new" "$TARGET"; rm -f "$TMP"
systemctl daemon-reload
say "running the updater once"
systemctl start "$UNIT" || true
journalctl -u "$UNIT" -n 15 --no-pager -o cat | sed -E 's#(postgres(ql)?://[^:/@ ]+:)[^@ ]+@#\1***@#g'
say "timer: $(systemctl is-active lunexeconom-v2-update.timer) | V2 service: $(systemctl is-active lunexeconom-v2.service)"
HEALTH=$(curl -s -m 8 http://127.0.0.1:18777/health | head -c 300)
say "V2 health after: $HEALTH"
say "V1 health after: $(curl -s -m 8 -o /dev/null -w '%{http_code}' http://127.0.0.1:18767/health)"
echo "$HEALTH" | grep -q '"ok":true' || { say "V2 NOT healthy: restoring previous updater file"; cp -a "$BK" "$TARGET"; exit 1; }
say "DONE. Rollback: cp -a $BK $TARGET && rm -f $DROPIN && systemctl daemon-reload"
