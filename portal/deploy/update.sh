#!/bin/sh
# Explicit operator action: install with automatic code rollback on health failure.
set -eu
[ "$(id -u)" -eq 0 ] || { echo "Run as root" >&2; exit 1; }
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if /bin/bash "$HERE/install.sh" "$@"; then
  echo "CreatePortal update succeeded"
  exit 0
fi
echo "Update failed: attempting to restore previous application code" >&2
if [ -d /opt/createportal.prev ]; then
  systemctl stop createportal || true
  mv /opt/createportal /opt/createportal.failed-$(date +%Y%m%d-%H%M%S)
  mv /opt/createportal.prev /opt/createportal
  systemctl start createportal
  curl --fail --silent --show-error http://127.0.0.1:18790/health
  echo "Previous application restored. Database schema may require separate backup restore." >&2
else
  echo "No previous application available; manual recovery required" >&2
fi
exit 1
