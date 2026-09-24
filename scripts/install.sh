#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python_version() {
  "$1" -c 'import sys; print("%d.%d" % sys.version_info[:2])'
}

python_is_supported() {
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'
}

if [[ -n "${PYTHON:-}" ]]; then
  if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "PYTHON=${PYTHON} was not found." >&2
    exit 1
  fi
  if ! python_is_supported "$PYTHON"; then
    echo "PYTHON=${PYTHON} is $(python_version "$PYTHON"). Python 3.11 or newer is required." >&2
    exit 1
  fi
else
  PYTHON=""
  for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && python_is_supported "$candidate"; then
      PYTHON="$candidate"
      break
    fi
  done
  if [[ -z "$PYTHON" ]]; then
    echo "Python 3.11 or newer was not found. Install it, then run this script again." >&2
    exit 1
  fi
fi

echo "Using $($PYTHON -c 'import sys; print(sys.executable)') ($(python_version "$PYTHON"))"

"$PYTHON" -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

echo "Dependencies installed in ${ROOT}/.venv"
