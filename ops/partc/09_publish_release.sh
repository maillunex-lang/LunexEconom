#!/usr/bin/env bash
# Publish a specific, OWNER-APPROVED signed GitHub Release, no private keys.
# Usage: sudo DRY_RUN=1 bash 09_publish_release.sh v0.1.0
#        sudo bash 09_publish_release.sh v0.1.0
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TAG="${1:?Usage: 09_publish_release.sh v0.1.N}"
if [[ "${DRY_RUN:-0}" == 1 ]]; then
    exec /opt/lunexeconom-v2/venv/bin/python "$DIR/release_common.py" --tag "$TAG" --dry-run
fi
exec /opt/lunexeconom-v2/venv/bin/python "$DIR/release_common.py" --tag "$TAG"