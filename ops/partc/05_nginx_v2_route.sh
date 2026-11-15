#!/usr/bin/env bash
# Часть C, шаг 5: ВРЕМЕННЫЙ маршрут V2 в nginx:  /lunexeconom/v2/api/  ->  127.0.0.1:18777
# Старый маршрут V1 (/lunexeconom/api/ -> 18767) НЕ меняется. Добавляется один блок рядом с ним.
# Перед правкой делается копия файла; проверка `nginx -t`; при любой ошибке файл возвращается автоматически.
# Пробный запуск (покажет файл и добавляемые строки, ничего не меняет):  sudo DRY_RUN=1 bash 05_nginx_v2_route.sh
# Боевой запуск:                                                         sudo bash 05_nginx_v2_route.sh > step5-report.txt 2>&1
set -euo pipefail
DRY="${DRY_RUN:-0}"
say() { echo "[step5] $*"; }
[ "$(id -u)" = 0 ] || { echo "run as root (sudo)"; exit 1; }

say "V2 local health: $(curl -s -m 8 -o /dev/null -w '%{http_code}' http://127.0.0.1:18777/health)  (need 200)"
[ "$(curl -s -m 8 -o /dev/null -w '%{http_code}' http://127.0.0.1:18777/health)" = 200 ] || { echo "V2 is not healthy, stop"; exit 1; }
say "V1 local health: $(curl -s -m 8 -o /dev/null -w '%{http_code}' http://127.0.0.1:18767/health)"
nginx -t >/dev/null 2>&1 || { echo "nginx -t fails BEFORE any change, stop"; nginx -t; exit 1; }

FILE=$(grep -rl 'location ^~ /lunexeconom/api/ {' /etc/nginx/sites-enabled /etc/nginx/conf.d 2>/dev/null | head -1 || true)
[ -n "$FILE" ] || { echo "could not find the file with the V1 api location"; exit 1; }
FILE=$(readlink -f "$FILE")
say "nginx file: $FILE"
grep -q 'lunexeconom/v2/api' "$FILE" && { echo "V2 route is already present, nothing to do"; exit 0; }

BACKUP="/root/nginx-before-step5-$(date -u +%Y%m%d-%H%M%S).conf"
NEW=$(mktemp)
python3 - "$FILE" "$NEW" <<'PY'
import re, sys
src, dst = sys.argv[1], sys.argv[2]
text = open(src, encoding="utf-8").read()
def block(start_marker):
    i = text.index(start_marker)
    j = text.index("{", i)
    depth = 0
    for k in range(j, len(text)):
        if text[k] == "{": depth += 1
        elif text[k] == "}":
            depth -= 1
            if depth == 0: return i, k + 1
    raise SystemExit("unbalanced braces")
i, k = block("location ^~ /lunexeconom/api/ {")
v1 = text[i:k]
if "18767" not in v1:
    raise SystemExit("V1 block does not proxy to 18767, refusing to guess")
v2 = v1.replace("/lunexeconom/api/", "/lunexeconom/v2/api/", 1).replace("18767", "18777")
if "X-Real-IP" not in v2:
    v2 = v2.rstrip()[:-1].rstrip() + "\n        proxy_set_header X-Real-IP $remote_addr;\n    }"
admin = "location ^~ /lunexeconom/v2/api/admin/ { return 404; }"
indent = re.search(r"([ \t]*)location \^~ /lunexeconom/api/ \{", text).group(1)
insert = (indent + "# LunexEconom V2 temporary route (step 5, remove when V2 replaces V1)\n"
          + indent + admin + "\n" + indent + v2 + "\n\n")
line_start = text.rfind("\n", 0, i) + 1
out = text[:line_start] + insert + text[line_start:]
open(dst, "w", encoding="utf-8").write(out)
print(insert)
PY
say "lines above will be inserted before the V1 api location"
if [ "$DRY" = 1 ]; then say "DRY RUN: no changes made"; rm -f "$NEW"; exit 0; fi

cp -a "$FILE" "$BACKUP"; say "backup: $BACKUP"
restore() { say "ROLLBACK: restoring $FILE"; cp -a "$BACKUP" "$FILE"; nginx -t && systemctl reload nginx; }
cat "$NEW" > "$FILE"; rm -f "$NEW"
nginx -t || { restore; exit 1; }
systemctl reload nginx

say "verification through public name (resolved to this server)"
H="--resolve rikagro.ru:443:127.0.0.1"
V2=$(curl -sk $H -m 10 -o /dev/null -w '%{http_code}' https://rikagro.ru/lunexeconom/v2/api/health || true)
V1=$(curl -sk $H -m 10 -o /dev/null -w '%{http_code}' https://rikagro.ru/lunexeconom/api/health || true)
AD=$(curl -sk $H -m 10 -o /dev/null -w '%{http_code}' https://rikagro.ru/lunexeconom/v2/api/admin/x || true)
say "V2 via nginx: $V2 (need 200) | V1 via nginx: $V1 (need 200) | V2 admin path: $AD (need 404)"
if [ "$V2" != 200 ] || [ "$V1" != 200 ] || [ "$AD" != 404 ]; then restore; echo "verification failed, nginx restored"; exit 1; fi
curl -sk $H -m 10 https://rikagro.ru/lunexeconom/v2/api/health | head -c 400; echo
say "DONE. To remove the route: cp -a $BACKUP $FILE && nginx -t && systemctl reload nginx"
