#!/usr/bin/env bash
# CreatePortal: установка и обновление одной командой (запускает владелец на VPS от root).
#   sudo bash install.sh            # установка или обновление из ветки main
#   sudo bash install.sh --repo /путь/к/клону   # взять код из локальной папки (без GitHub)
# Безопасно запускать повторно: база и пароль не затрагиваются, перед обновлением кода делается копия базы.
set -euo pipefail

REPO_URL="https://github.com/maillunex-lang/LunexEconom.git"
APP=/opt/createportal
DATA=/var/lib/createportal
BAK=/var/backups/createportal
SRC=""
[ "${1:-}" = "--repo" ] && SRC="${2:?укажите папку клона}"

[ "$(id -u)" = 0 ] || { echo "Запустите от root: sudo bash install.sh"; exit 1; }
command -v python3 >/dev/null || { echo "Нужен python3 (3.12+)"; exit 1; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)' || { echo "Нужен Python 3.12 или новее"; exit 1; }
command -v sqlite3 >/dev/null || echo "Предупреждение: sqlite3 не найден, ежедневные копии будут через python"

TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
if [ -n "$SRC" ]; then cp -r "$SRC" "$TMP/repo"; else git clone --depth 1 --branch main "$REPO_URL" "$TMP/repo"; fi
R="$TMP/repo"
[ -f "$R/portal/serve.py" ] || { echo "В источнике нет portal/serve.py"; exit 1; }

id createportal >/dev/null 2>&1 || useradd --system --home "$APP" --shell /usr/sbin/nologin createportal
install -d -m 0700 -o createportal -g createportal "$DATA"
install -d -m 0700 -o root -g root "$BAK"

# копия базы перед обновлением (если есть)
if [ -f "$DATA/portal.sqlite" ]; then
  python3 - "$DATA/portal.sqlite" "$BAK/portal-pre-update-$(date +%F-%H%M).sqlite" <<'PY'
import sqlite3, sys
s = sqlite3.connect(sys.argv[1]); d = sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()
PY
fi

# код: предыдущую версию сохраняем для отката
rm -rf "$APP.prev"; [ -d "$APP" ] && mv "$APP" "$APP.prev"
install -d -m 0755 "$APP/tools"
cp -r "$R/portal" "$APP/portal"
cp "$R/tools/work_plan.py" "$APP/tools/work_plan.py"; : > "$APP/tools/__init__.py"
find "$APP" -name __pycache__ -prune -exec rm -rf {} +
rm -rf "$APP/portal/tests" "$APP/portal/ui_tests" "$APP/portal/qa"
chown -R root:root "$APP"; chmod -R a+rX,go-w "$APP"

# сервис (сохраняем правки владельца в unit-файле, если он уже есть)
[ -f /etc/systemd/system/createportal.service ] || cp "$R/portal/deploy/createportal.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable createportal >/dev/null 2>&1
systemctl restart createportal

# ежедневная копия базы, хранить 14 дней
cat > /etc/cron.daily/createportal-backup <<'CR'
#!/bin/sh
python3 - <<'PY'
import sqlite3, time
s = sqlite3.connect("/var/lib/createportal/portal.sqlite")
d = sqlite3.connect("/var/backups/createportal/portal-%s.sqlite" % time.strftime("%F"))
s.backup(d); d.close(); s.close()
PY
find /var/backups/createportal -name 'portal-*.sqlite' -mtime +14 -delete
CR
chmod 0755 /etc/cron.daily/createportal-backup

# проверка работы
for i in 1 2 3 4 5 6 7 8; do
  curl -fsS http://127.0.0.1:18790/health >/dev/null 2>&1 && OK=1 && break; sleep 1
done
if [ "${OK:-0}" != 1 ]; then
  echo "ОШИБКА: сервис не отвечает. Журнал: journalctl -u createportal -n 50"
  echo "Откат: systemctl stop createportal; rm -rf $APP; mv $APP.prev $APP; systemctl start createportal"
  exit 1
fi
echo "Сервис работает: $(curl -fsS http://127.0.0.1:18790/health)"

# пароль владельца: спросит один раз, если ещё не задан
if ! python3 - <<'PY'
import sqlite3, sys
try:
    c = sqlite3.connect("file:/var/lib/createportal/portal.sqlite?mode=ro", uri=True)
    sys.exit(0 if c.execute("select count(*) from users").fetchone()[0] else 1)
except Exception:
    sys.exit(1)
PY
then
  echo "Задайте пароль владельца (не короче 14 символов, ввод скрыт):"
  (cd "$APP" && sudo -u createportal PORTAL_DB="$DATA/portal.sqlite" python3 -m portal.manage set-password owner)
fi

echo
echo "Осталось подключить nginx (один раз): см. portal/DEPLOY.md, шаг 6."
echo "Готово. Откат: systemctl stop createportal; rm -rf $APP; mv $APP.prev $APP; systemctl start createportal"
