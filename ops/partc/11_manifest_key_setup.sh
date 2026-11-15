#!/usr/bin/env bash
# Wrapper: prepares a temporary venv with cryptography and PyNaCl and runs 11_manifest_key_setup.py.
# Usage: sudo bash 11_manifest_key_setup.sh --dry-run   |   sudo bash 11_manifest_key_setup.sh
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run as root (sudo)"; exit 1; }
D=$(mktemp -d /tmp/lunex-keysetup.XXXXXX)
python3 -m venv "$D/venv"
"$D/venv/bin/pip" install -q cryptography pynacl
curl -fsSL -m 30 https://raw.githubusercontent.com/maillunex-lang/LunexEconom/main/ops/partc/11_manifest_key_setup.py -o "$D/setup.py"
"$D/venv/bin/python" "$D/setup.py" "$@"
echo "temporary venv left in $D (no secrets inside; may be removed by the owner later)"
