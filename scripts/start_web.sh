#!/usr/bin/env bash
# Start the web app with multiple uvicorn workers (forecast charts are CPU-heavy).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p logs
WORKERS="${UVICORN_WORKERS:-2}"
PORT="${PORT:-8000}"
pkill -f 'uvicorn app.main:app' 2>/dev/null || true
sleep 1
nohup .venv/bin/uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "$PORT" \
  --workers "$WORKERS" \
  > logs/uvicorn.log 2>&1 &
sleep 2
curl -sS "http://127.0.0.1:${PORT}/health"
echo
echo "uvicorn workers=${WORKERS} port=${PORT}"
