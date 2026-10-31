#!/usr/bin/env bash
# Weekday flash append: CLS 重点 + Tonghuashun. Meant for every 10 minutes, 08:00–23:00.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"
mkdir -p logs

LOCK="/tmp/trade_agents_news_flash.lock"
LOG="logs/news_flash_sync.log"
PY="${ROOT}/.venv/bin/python"

if [[ ! -x "${PY}" ]]; then
  echo "error: missing venv python at ${PY}" >&2
  exit 1
fi

exec 9>"${LOCK}"
if ! flock -n 9; then
  echo "$(date '+%F %T') skip: another flash sync is still running" | tee -a "${LOG}"
  exit 0
fi

{
  echo "======== $(date '+%F %T') start ========"
  "${PY}" -m app.jobs.sync_news_flash
  echo "======== $(date '+%F %T') done ========"
} >>"${LOG}" 2>&1
