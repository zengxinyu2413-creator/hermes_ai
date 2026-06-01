"""RiskStateStore: persistence protocol for RiskGuard state snapshots.

In scope: RiskStateStore Protocol, InMemoryStateStore (test default),
FileStateStore (JSON snapshot, POSIX multi-process safe via fcntl.flock).

State dict schema: {"state": "ACTIVE" | "HALTED", "consecutive_losses": int}.
_daily_pnl is intentionally excluded — daily accumulator has ambiguous semantics
across restarts (D2 boundary).

FileStateStore uses fcntl.flock(LOCK_EX) to serialise concurrent access;
LOCK_UN is released in a finally clause so exceptions in the critical section
do not leak the lock.

LC-RISK-2 resolved: fcntl.flock 排他锁已加，多进程串行写入安全。
LC-XPLAT-1: POSIX (Linux) only — fcntl is not available on Windows;
Windows support not implemented.
"""

from __future__ import annotations

import fcntl
import json
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class RiskStateStore(Protocol):
    """Persistence contract for RiskGuard state.

    load() returns the last saved state dict, or None if no state exists yet.
    save() overwrites the stored state with a fresh snapshot; idempotent calls
    are allowed.
    """

    def load(self) -> dict | None:
        ...

    def save(self, state: dict) -> None:
        ...


class InMemoryStateStore:
    """In-process RiskStateStore backed by a single dict slot.

    Default for unit tests and the no-store fallback.  Zero disk / zero
    network — satisfies CK5 isolation guarantee.
    """

    def __init__(self) -> None:
        self._data: dict | None = None

    def load(self) -> dict | None:
        return dict(self._data) if self._data is not None else None

    def save(self, state: dict) -> None:
        self._data = dict(state)


class FileStateStore:
    """JSON-snapshot flat-file RiskStateStore.

    Each call to save() overwrites the file with the latest state dict.
    load() reads the file on demand (called once at RiskGuard construction).
    A missing file returns None — not an error.

    Both load() and save() hold fcntl.flock(LOCK_EX) over the critical
    section; LOCK_UN is released in a finally clause, so exceptions in the
    critical section do not leak the lock.

    LC-RISK-2 resolved: fcntl.flock 排他锁已加，多进程串行写入安全。
    LC-XPLAT-1: POSIX (Linux) only — Windows not supported.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def load(self) -> dict | None:
        if not self._path.exists():
            return None
        with self._path.open("r", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                content = fh.read()
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)
        return json.loads(content)

    def save(self, state: dict) -> None:
        with self._path.open("w", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                fh.write(json.dumps(state))
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)
