#!/usr/bin/env bash
# Weekday evening pipeline: board bars (5d) → board heat → stock bars (5d).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"
mkdir -p logs

LOCK="/tmp/trade_agents_evening_market_sync.lock"
LOG="logs/evening_market_sync.log"
PY="${ROOT}/.venv/bin/python"

if [[ ! -x "${PY}" ]]; then
  echo "error: missing venv python at ${PY}" >&2
  exit 1
fi

exec 9>"${LOCK}"
if ! flock -n 9; then
  echo "$(date '+%F %T') skip: another evening sync is still running" | tee -a "${LOG}"
  exit 0
fi

{
  echo "======== $(date '+%F %T') start ========"
  echo "--- board daily bars (5 trading days) ---"
  "${PY}" -m app.jobs.sync_board_daily_bars --trading-days 5 --resume
  echo "--- board heat (industry + concept) ---"
  "${PY}" -m app.jobs.compute_board_heat --board-type all
  echo "--- stock daily bars (5 trading days) ---"
  "${PY}" -m app.jobs.sync_stock_daily_bars --trading-days 5 --resume
  echo "======== $(date '+%F %T') done ========"
} >>"${LOG}" 2>&1
