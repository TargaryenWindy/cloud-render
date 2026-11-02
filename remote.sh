#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
bash ./start.sh --setup-only --remote-dependencies
exec ./.venv/bin/python remote.py
