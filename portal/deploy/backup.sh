#!/bin/sh
# Daily SQLite API backup; run as createportal, never copy a live WAL file directly.
set -eu
export PORTAL_DB="${PORTAL_DB:-/var/lib/createportal/portal.sqlite}"
export PORTAL_BACKUP_DIR="${PORTAL_BACKUP_DIR:-/var/backups/createportal}"
cd "${PORTAL_APP_DIR:-/opt/createportal}"
python3 - <<'PY'
import os
from portal.backup.core import create_backup, verify_backup
p=create_backup(os.environ["PORTAL_DB"],os.environ["PORTAL_BACKUP_DIR"],keep=14)
if not verify_backup(p)["ok"]:raise SystemExit("backup integrity failure")
print("Backup verified:",os.path.basename(p))
PY
