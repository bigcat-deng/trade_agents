"""Background runner for sync dashboard jobs (global single-flight)."""

from __future__ import annotations

import subprocess
import sys
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]

JOB_IDS = (
    "stock_universe",
    "stock_daily_bars",
    "board_universe",
    "board_daily_bars",
    "board_constituents",
)

# Jobs that take an explicit --day snapshot date.
DAY_JOB_IDS = frozenset({"stock_universe", "board_universe", "board_constituents"})

JOB_LABELS: dict[str, str] = {
    "stock_universe": "个股名单",
    "stock_daily_bars": "个股日 K",
    "board_universe": "板块名单",
    "board_daily_bars": "板块日 K",
    "board_constituents": "板块成分",
}


@dataclass
class SyncJobState:
    job_id: str | None = None
    label: str | None = None
    running: bool = False
    started_at: datetime | None = None
    finished_at: datetime | None = None
    exit_code: int | None = None
    command: list[str] = field(default_factory=list)
    log_tail: str = ""
    error: str | None = None


_lock = threading.Lock()
_state = SyncJobState()
_process: subprocess.Popen[str] | None = None
_log_chunks: list[str] = []
_MAX_LOG_CHARS = 8000


def get_runner_state() -> dict[str, Any]:
    with _lock:
        return {
            "busy": _state.running,
            "job_id": _state.job_id,
            "label": _state.label,
            "started_at": _state.started_at.isoformat() if _state.started_at else None,
            "finished_at": (
                _state.finished_at.isoformat() if _state.finished_at else None
            ),
            "exit_code": _state.exit_code,
            "command": list(_state.command),
            "log_tail": _state.log_tail,
            "error": _state.error,
        }


def _append_log(text: str) -> None:
    global _log_chunks
    if not text:
        return
    _log_chunks.append(text)
    joined = "".join(_log_chunks)
    if len(joined) > _MAX_LOG_CHARS:
        joined = joined[-_MAX_LOG_CHARS:]
        _log_chunks = [joined]
    _state.log_tail = joined


def _build_command(
    job_id: str,
    *,
    trading_days: int | None,
    resume: bool,
    day: date | None,
) -> list[str]:
    py = sys.executable
    if job_id == "stock_universe":
        cmd = [py, "-m", "app.jobs.sync_stock_universe"]
        if day is not None:
            cmd.extend(["--day", day.isoformat()])
        return cmd
    if job_id == "stock_daily_bars":
        cmd = [py, "-m", "app.jobs.sync_stock_daily_bars"]
        if trading_days is not None:
            cmd.extend(["--trading-days", str(trading_days)])
        if resume:
            cmd.append("--resume")
        return cmd
    if job_id == "board_universe":
        cmd = [py, "-m", "app.jobs.sync_board_universe"]
        if day is not None:
            cmd.extend(["--day", day.isoformat()])
        return cmd
    if job_id == "board_daily_bars":
        cmd = [py, "-m", "app.jobs.sync_board_daily_bars"]
        if trading_days is not None:
            cmd.extend(["--trading-days", str(trading_days)])
        if resume:
            cmd.append("--resume")
        return cmd
    if job_id == "board_constituents":
        cmd = [py, "-m", "app.jobs.sync_board_constituents"]
        if day is not None:
            cmd.extend(["--day", day.isoformat()])
        if resume:
            cmd.append("--resume")
        return cmd
    raise ValueError(f"unknown job_id: {job_id}")


def _watch_process(proc: subprocess.Popen[str], job_id: str) -> None:
    global _process
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            with _lock:
                _append_log(line)
        code = proc.wait()
        with _lock:
            _state.running = False
            _state.finished_at = datetime.now(timezone.utc).astimezone()
            _state.exit_code = code
            if code != 0 and not _state.error:
                _state.error = f"exit code {code}"
            _process = None
    except Exception as exc:  # noqa: BLE001
        with _lock:
            _state.running = False
            _state.finished_at = datetime.now(timezone.utc).astimezone()
            _state.exit_code = -1
            _state.error = str(exc)
            _process = None


def start_job(
    job_id: str,
    *,
    trading_days: int | None = 200,
    resume: bool = True,
    day: date | None = None,
) -> dict[str, Any]:
    if job_id not in JOB_IDS:
        raise ValueError(f"unknown job_id: {job_id}")

    if job_id in {"stock_daily_bars", "board_daily_bars"}:
        if trading_days is None or trading_days < 1:
            raise ValueError("trading_days must be >= 1")
    else:
        trading_days = None

    if job_id in DAY_JOB_IDS:
        if day is None:
            raise ValueError("day is required (YYYY-MM-DD)")
    else:
        day = None

    # constituents: resume optional too
    command = _build_command(
        job_id, trading_days=trading_days, resume=resume, day=day
    )

    with _lock:
        if _state.running:
            raise RuntimeError(
                f"busy: {_state.label or _state.job_id} is already running"
            )
        global _process, _log_chunks
        _log_chunks = []
        _state.job_id = job_id
        _state.label = JOB_LABELS[job_id]
        _state.running = True
        _state.started_at = datetime.now(timezone.utc).astimezone()
        _state.finished_at = None
        _state.exit_code = None
        _state.command = command
        _state.log_tail = ""
        _state.error = None

        proc = subprocess.Popen(
            command,
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        _process = proc

    thread = threading.Thread(
        target=_watch_process,
        args=(proc, job_id),
        name=f"sync-job-{job_id}",
        daemon=True,
    )
    thread.start()
    return get_runner_state()
