#!/usr/bin/env bash
# VPS-ADM: isolated admin static publisher. No nginx edits.
# Usage: DRY_RUN=1 SHA=<40-hex> bash ops/partc/12_publish_admin.sh
#        SHA=<40-hex> bash ops/partc/12_publish_admin.sh
set -euo pipefail
umask 022
DRY_RUN="${DRY_RUN:-0}"
DEST=/var/www/rikagro-game/lunexeconom-admin
REPO=maillunex-lang/LunexEconom
FILES=(index.html app.js a3.js styles.css config.js)
[ "$(id -u)" -eq 0 ] || { echo 'must run as root'; exit 1; }
[[ "$DRY_RUN" == 0 || "$DRY_RUN" == 1 ]] || { echo 'DRY_RUN must be 0 or 1'; exit 1; }
SHA="${SHA:-}"
if [[ -z "$SHA" ]]; then
  SHA="$(curl -fsS --max-time 20 -H 'Accept: application/vnd.github+json' "https://api.github.com/repos/$REPO/commits/main" | python3 -c 'import json,sys; print(json.load(sys.stdin)["sha"])')"
fi
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || { echo 'SHA must be a 40-character commit hash'; exit 1; }
echo "[admin] source SHA: $SHA"
# All downloads and checks stay in a temporary directory, including DRY_RUN.
STAGE="$(mktemp -d /tmp/lunexeconom-admin-stage.XXXXXXXX)"
trap 'rm -rf "$STAGE"' EXIT
for file in "${FILES[@]}"; do
  curl -fLsS --max-time 30 --retry 2 -o "$STAGE/$file" "https://raw.githubusercontent.com/$REPO/$SHA/web/admin/$file"
  [[ -s "$STAGE/$file" ]] || { echo "empty: $file"; exit 1; }
  [[ "$(stat -c %s "$STAGE/$file")" -le 300000 ]] || { echo "unexpected size: $file"; exit 1; }
  echo "[admin] validated download: $file ($(stat -c %s "$STAGE/$file") bytes)"
done
grep -Fq "window.ADMIN_CONFIG" "$STAGE/config.js"
grep -Fq "/lunexeconom/v2/admin-api/" "$STAGE/config.js"
grep -Fq './app.js' "$STAGE/index.html"
grep -Fq './a3.js' "$STAGE/index.html"
if grep -Eiq '<script([^>]*)(>|[[:space:]])[^>]*>[^[:space:]<]|[[:space:]]on(click|load|input|submit|change)=' "$STAGE/index.html"; then
  echo 'inline script/handler found: review CSP before deployment'; exit 1
fi
if [[ "$DRY_RUN" == 1 ]]; then
  echo "[admin] DRY_RUN: no site files or nginx configuration changed"
  echo "[admin] would atomically publish ${FILES[*]} to $DEST with root:root 0644 and DEPLOYED_SHA.txt"
  exit 0
fi
[[ ! -L "$DEST" ]] || { echo "destination is symlink; stop"; exit 1; }
[[ ! -e "$DEST" || -d "$DEST" ]] || { echo "destination is not directory; stop"; exit 1; }
PARENT="$(dirname "$DEST")"
[[ -d "$PARENT" ]] || { echo "parent missing: $PARENT"; exit 1; }
NEXT="$(mktemp -d "$PARENT/.lunexeconom-admin-next.XXXXXXXX")"
cleanup_next() { [[ -d "$NEXT" ]] && rm -rf "$NEXT" || :; }
trap 'cleanup_next; rm -rf "$STAGE"' EXIT
for file in "${FILES[@]}"; do
  install -o root -g root -m 0644 "$STAGE/$file" "$NEXT/$file"
done
printf '%s\n' "$SHA" > "$NEXT/DEPLOYED_SHA.txt"
chmod 0644 "$NEXT/DEPLOYED_SHA.txt"
chown root:root "$NEXT/DEPLOYED_SHA.txt"
chmod 0755 "$NEXT"
BACKUP=''
if [[ -d "$DEST" ]]; then
  BACKUP="$DEST.before-$(date -u +%Y%m%dT%H%M%S%NZ)"
  mv -- "$DEST" "$BACKUP"
  echo "[admin] previous directory backup: $BACKUP"
fi
if ! mv -- "$NEXT" "$DEST"; then
  if [[ -n "$BACKUP" && ! -e "$DEST" ]]; then mv -- "$BACKUP" "$DEST"; fi
  echo '[admin] install failed; previous version restored if available' >&2
  exit 1
fi
echo "[admin] installed SHA=$SHA at $DEST"
echo "[admin] static rollback: mv $DEST $DEST.failed-<timestamp> && mv <BACKUP> $DEST"
