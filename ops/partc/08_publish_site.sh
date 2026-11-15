#!/usr/bin/env bash
# Часть C: публикация статического сайта V2 на временный адрес https://rikagro.ru/lunexeconom/v2/ (идемпотентно, с откатом).
# Берёт файлы web/ из GitHub для указанного коммита (по умолчанию HEAD main), переопределяет ТОЛЬКО адрес в config.js,
# сохраняет копию прежней версии, добавляет блок nginx только если его ещё нет, проверяет адреса.
# Ничего не удаляет. Пробный запуск:  sudo DRY_RUN=1 bash 08_publish_site.sh
# Боевой запуск:                       sudo bash 08_publish_site.sh      (SHA=<40 hex> чтобы закрепить коммит)
set -euo pipefail
DRY="${DRY_RUN:-0}"
SITE_BASE="${SITE_BASE:-https://rikagro.ru/lunexeconom/v2}"
DEST=/var/www/rikagro-game/lunexeconom-v2
CONF=/etc/nginx/sites-available/rikagro-game
REPO=maillunex-lang/LunexEconom
FILES="index.html styles.css config.js site.js roadmap.json"
say() { echo "[site] $*"; }
[ "$(id -u)" = 0 ] || { echo "run as root (sudo)"; exit 1; }

SHA="${SHA:-}"
if [ -z "$SHA" ]; then
  REM=$(curl -fsS -m 20 https://api.github.com/rate_limit | python3 -c 'import json,sys; print(json.load(sys.stdin)["resources"]["core"]["remaining"])')
  [ "$REM" -gt 20 ] || { echo "GitHub API remaining=$REM, set SHA=<commit> explicitly"; exit 1; }
  SHA=$(curl -fsS -m 20 "https://api.github.com/repos/$REPO/commits/main" | python3 -c 'import json,sys; print(json.load(sys.stdin)["sha"])')
fi
echo "$SHA" | grep -Eq '^[0-9a-f]{40}$' || { echo "bad SHA"; exit 1; }
say "commit: $SHA"
nginx -t >/dev/null 2>&1 || { echo "nginx -t fails before any change, stop"; exit 1; }

STAGE=$(mktemp -d)
python3 - "$SHA" "$STAGE" "$SITE_BASE" "$FILES" <<'PY'
import json, sys, urllib.request
from pathlib import Path
sha, stage, base, files = sys.argv[1], Path(sys.argv[2]), sys.argv[3], sys.argv[4].split()
root = f"https://raw.githubusercontent.com/maillunex-lang/LunexEconom/{sha}/web/"
for name in files:
    req = urllib.request.Request(root + name, headers={"User-Agent": "LunexEconom-site-publisher"})
    data = urllib.request.urlopen(req, timeout=20).read()
    if not data or len(data) > 200000: raise SystemExit("invalid source: " + name)
    if name == "config.js":
        text = data.decode()
        if 'window.LUNEX_PUBLIC_BASE = "' not in text: raise SystemExit("config.js has no LUNEX_PUBLIC_BASE")
        import re
        text = re.sub(r'(window\.LUNEX_PUBLIC_BASE = ")[^"]*(")', lambda m: m.group(1) + base + m.group(2), text, count=1)
        data = text.encode()
    if name.endswith(".json"): json.loads(data)
    (stage / name).write_bytes(data)
    print("staged", name, len(data), "bytes")
PY
if [ "$DRY" = 1 ]; then say "DRY RUN: would publish the files above to $DEST (config.js base -> $SITE_BASE)"; grep -c 'location ^~ /lunexeconom/v2/ {' "$CONF" | sed 's/^/[site] existing v2 location blocks in nginx: /'; rm -rf "$STAGE"; exit 0; fi

mkdir -p "$DEST"
if [ -n "$(ls -A "$DEST" 2>/dev/null)" ]; then cp -a "$DEST" "$DEST.before-$(date -u +%Y%m%dT%H%M%SZ)"; say "previous version kept next to $DEST"; fi
for f in $FILES; do install -m 0644 -o root -g root "$STAGE/$f" "$DEST/$f.new"; mv -f "$DEST/$f.new" "$DEST/$f"; done
echo "$SHA" > "$DEST/DEPLOYED_SHA.txt"; rm -rf "$STAGE"

if grep -q 'location ^~ /lunexeconom/v2/ {' "$CONF"; then
  say "nginx block already present, no nginx change"
else
  BACKUP="$CONF.before-lunexeconom-v2-site.$(date -u +%Y%m%dT%H%M%SZ)"; cp -a "$CONF" "$BACKUP"; say "nginx backup: $BACKUP"
  python3 - "$CONF" <<'PY'
import sys, os
from pathlib import Path
p = Path(sys.argv[1]); data = p.read_text()
anchor = "    location ^~ /lunexeconom/api/ {"
assert data.count(anchor) == 1, "expected exactly one V1 api location anchor"
block = """    # LunexEconom V2 only: static landing and roadmap (longer /v2/api/ stays proxied).
    location = /lunexeconom/v2 {
        return 308 /lunexeconom/v2/;
    }
    location = /lunexeconom/v2/roadmap.json {
        alias /var/www/rikagro-game/lunexeconom-v2/roadmap.json;
        add_header Cache-Control "no-store" always;
    }
    location ^~ /lunexeconom/v2/ {
        alias /var/www/rikagro-game/lunexeconom-v2/;
        index index.html;
        autoindex off;
        try_files $uri $uri/ =404;
        add_header X-Content-Type-Options nosniff always;
    }

"""
tmp = p.with_name(p.name + ".new"); tmp.write_text(data.replace(anchor, block + anchor)); os.chmod(tmp, p.stat().st_mode & 0o777); os.replace(tmp, p)
PY
  if ! nginx -t; then cp -a "$BACKUP" "$CONF"; nginx -t; exit 1; fi
  systemctl reload nginx || { cp -a "$BACKUP" "$CONF"; nginx -t; systemctl reload nginx; exit 1; }
fi

say "verification"
for P in /lunexeconom/v2/ /lunexeconom/v2/roadmap.json /lunexeconom/v2/site.js /lunexeconom/v2/api/health; do
  printf '%s ' "$P"; curl -fsS -o /dev/null -w '%{http_code} %{content_type}\n' --max-time 12 "https://rikagro.ru$P"
done
say "DONE. Rollback of files: restore the .before-* directory; of nginx: the .before-lunexeconom-v2-site.* copy."
