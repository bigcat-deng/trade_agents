"""Load the shared project environment file."""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ENV = Path(__file__).resolve().parents[1] / ".env"


def load_env(path: Path | None = None) -> None:
    """Load KEY=VALUE pairs into the process environment.

    Existing variables win, so a shell export overrides the file.
    """
    env_path = path or PROJECT_ENV
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)
