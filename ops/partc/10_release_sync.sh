#!/usr/bin/env bash
# Every 30 minutes check the newest published, non-prerelease alpha GitHub release.
# Only update latest.json after a verified signed manifest and a verified APK.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${DRY_RUN:-0}" == 1 ]]; then
    exec /opt/lunexeconom-v2/venv/bin/python "$DIR/release_common.py" --sync --dry-run
fi
exec /opt/lunexeconom-v2/venv/bin/python "$DIR/release_common.py" --sync