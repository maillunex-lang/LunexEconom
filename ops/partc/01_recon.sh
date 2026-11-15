#!/usr/bin/env bash
# Часть C, шаг 1: РАЗВЕДКА VPS. Только чтение, ничего не меняет и не перезапускает.
# Запуск владельцем на VPS:  sudo bash 01_recon.sh > recon.txt
# Секретные значения маскируются. Перед отправкой recon.txt директору просмотри файл глазами.
set -u
mask() { sed -E 's/((PASS(WORD)?|SECRET|TOKEN|KEY|DSN|DATABASE_URL)[A-Za-z0-9_]*[=:] *)[^ ]+/\1***MASKED***/Ig; s#(postgres(ql)?://[^:/@ ]+:)[^@ ]+@#\1***MASKED***@#g'; }
sec() { printf '\n===== %s =====\n' "$1"; }

sec "host"; hostname; date -u +%FT%TZ; uname -srm; id -un
sec "disk and memory"; df -h / /var /opt 2>/dev/null; free -m
sec "services matching lunex|nginx|postgres|update"
systemctl list-units --type=service --all --no-legend 2>/dev/null | grep -i -E 'lunex|nginx|postgres|update' | awk '{print $1, $2, $3, $4}'
sec "timers"
systemctl list-timers --all --no-legend 2>/dev/null | grep -i -E 'lunex|update' | awk '{print $NF, $(NF-1)}'
sec "unit details (no environment values)"
for u in $(systemctl list-units --type=service --all --no-legend 2>/dev/null | awk '{print $1}' | grep -i lunex); do
  echo "--- $u"; systemctl show "$u" -p FragmentPath -p User -p WorkingDirectory -p ExecStart -p EnvironmentFiles -p ActiveState 2>/dev/null | mask
done
sec "listening ports"
ss -ltnp 2>/dev/null | awk 'NR==1 || /LISTEN/' | mask
sec "nginx (selected directives only)"
if command -v nginx >/dev/null 2>&1; then
  nginx -v 2>&1
  nginx -T 2>/dev/null | grep -E '^\s*(server_name|listen|location|proxy_pass|root|alias|include|ssl_certificate |return)\b' | sed -E 's/^\s+//' | head -120 | mask
else echo "nginx not found"; fi
sec "tls certificates"
(command -v certbot >/dev/null 2>&1 && certbot certificates 2>/dev/null | grep -E 'Certificate Name|Domains|Expiry') || echo "certbot not available"
sec "postgresql (names and sizes only)"
(command -v psql >/dev/null 2>&1 && sudo -u postgres psql -Atc "select version()" 2>/dev/null) || echo "psql/postgres not reachable"
sudo -u postgres psql -Atc "select datname||' '||pg_size_pretty(pg_database_size(datname)) from pg_database where not datistemplate" 2>/dev/null
sudo -u postgres psql -Atc "select rolname from pg_roles where rolname !~ '^pg_'" 2>/dev/null
sec "application directories (names only)"
ls -la /opt 2>/dev/null; ls -la /var/lib 2>/dev/null | grep -i -E 'lunex|update'; ls -la /var/www 2>/dev/null | head -20
sec "python"
python3 --version 2>&1; python3 -c "import psycopg, psycopg_pool, waitress, jsonschema, cryptography; print('v2 dependencies: present')" 2>&1 | tail -1
sec "firewall"
(command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | head -15) || echo "ufw not available"
sec "end"; echo done
