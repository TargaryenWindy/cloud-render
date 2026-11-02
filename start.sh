#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
ROOT="$PWD"
export UV_PYTHON_INSTALL_DIR="$ROOT/tools/python"
export UV_CACHE_DIR="$ROOT/tools/uv-cache"
export UV_PYTHON_INSTALL_BIN=0
export UV_NO_MODIFY_PATH=1
get_uv() {
    UV="$ROOT/tools/uv/uv"
    if [[ ! -x "$UV" ]]; then
        command -v curl >/dev/null || { echo 'Install curl to download missing dependencies.' >&2; exit 1; }
        case "$(uname -m)" in x86_64) arch=x86_64;; aarch64|arm64) arch=aarch64;; *) echo 'Unsupported CPU architecture.' >&2; exit 1;; esac
        mkdir -p "$ROOT/tools/uv"
        archive="$ROOT/tools/uv/uv.tar.gz"
        curl -fL --retry 3 "https://github.com/astral-sh/uv/releases/latest/download/uv-$arch-unknown-linux-gnu.tar.gz" -o "$archive.part"
        mv -- "$archive.part" "$archive"
        tar -xzf "$archive" --strip-components=1 -C "$ROOT/tools/uv"
        rm -- "$archive"
    fi
}
PYTHON="$ROOT/.venv/bin/python"
if ! "$PYTHON" -c 'import sys; assert sys.version_info >= (3,10)' 2>/dev/null; then
    candidate=''
    for executable in "${RENDER_PYTHON:-}" python3 python; do
        [[ -n "$executable" ]] || continue
        if "$executable" -c 'import sys; assert sys.version_info >= (3,10)' 2>/dev/null; then
            candidate="$("$executable" -c 'import sys; print(sys.executable)')"; break
        fi
    done
    if [[ -e "$ROOT/.venv" ]]; then mv -- "$ROOT/.venv" "$ROOT/.venv-replaced-$(date +%s)-$$"; fi
    if [[ -n "$candidate" ]] && "$candidate" -m venv "$ROOT/.venv"; then :
    else
        # uv can build an environment even if distro Python lacks ensurepip/venv.
        get_uv
        if [[ -n "$candidate" ]]; then
            "$UV" venv --clear --seed --python "$candidate" --no-python-downloads "$ROOT/.venv"
        else
            echo 'Downloading private Python into tools/python...'
            "$UV" venv --seed --managed-python --python 3.12 "$ROOT/.venv"
        fi
    fi
fi
if ! "$PYTHON" -c 'import flask, waitress' 2>/dev/null; then
    if "$PYTHON" -c 'import pip' 2>/dev/null; then
        "$PYTHON" -m pip install -r "$ROOT/requirements.txt" --index-url https://pypi.org/simple
    else
        get_uv
        "$UV" pip install --python "$PYTHON" -r "$ROOT/requirements.txt" --index-url https://pypi.org/simple
    fi
fi
args=()
[[ " ${*} " == *' --remote-dependencies '* ]] && args+=(--remote)
"$PYTHON" "$ROOT/dependencies.py" "${args[@]}"
if [[ " ${*} " == *' --setup-only '* ]]; then echo 'Render desk dependencies are ready.'; exit 0; fi
exec "$PYTHON" "$ROOT/app.py"
