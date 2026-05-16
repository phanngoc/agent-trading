"""PID-based lock for the daily orchestrator.

The cron job + a manually-triggered ``run_daily`` could collide otherwise
and double-bill the agent runs. A simple file lock is enough — we don't
need fcntl-grade exclusion since both invocations are on the same
machine and the worst case is "two backtests stomp on the same output
dir", which is recoverable.

Lock contents are the PID + ISO start timestamp. Stale locks (PID no
longer alive) are auto-released so a crash doesn't wedge the next run.
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from datetime import datetime


def _pid_alive(pid: int) -> bool:
    """Return True if ``pid`` is currently running on this machine."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def _read_existing(path: str) -> tuple[int, str] | None:
    try:
        with open(path, "r") as f:
            raw = f.read().strip()
    except OSError:
        return None
    if not raw:
        return None
    parts = raw.split(None, 1)
    try:
        pid = int(parts[0])
    except ValueError:
        return None
    timestamp = parts[1] if len(parts) > 1 else ""
    return pid, timestamp


class LockBusy(RuntimeError):
    """Raised when an existing healthy lock blocks acquisition."""


@contextmanager
def acquire(lock_path: str):
    """Best-effort exclusive lock for a single-machine cron / manual run.

    On entry: write our PID + start timestamp to ``lock_path``. If a
    healthy lock already exists, raise :class:`LockBusy`. On exit:
    remove the file unconditionally so a normal completion never leaves
    a stale lock behind.
    """
    os.makedirs(os.path.dirname(lock_path) or ".", exist_ok=True)

    existing = _read_existing(lock_path)
    if existing is not None:
        pid, started = existing
        if _pid_alive(pid):
            raise LockBusy(f"Another run_daily is in flight (pid={pid}, started={started})")
        # Stale — silently overwrite.

    with open(lock_path, "w") as f:
        f.write(f"{os.getpid()} {datetime.utcnow().isoformat(timespec='seconds')}Z\n")

    try:
        yield
    finally:
        try:
            os.remove(lock_path)
        except FileNotFoundError:
            pass
