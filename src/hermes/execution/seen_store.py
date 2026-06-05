"""SeenStore: persistence protocol for OrderIdFactory dedup set.

In scope: SeenStore Protocol, InMemoryStore (test default), FileStore
(append-only, cross-platform with graceful lock degradation).

FileStore uses fcntl.flock(LOCK_EX) to serialise concurrent access from
multiple processes; LOCK_UN is released in a finally clause so exceptions
in the critical section do not leak the lock.

LC-EXEC-5 resolved: fcntl.flock 排他锁已加，多进程串行写入安全。
LC-XPLAT-1 resolved (P1 soft-degrade): Cross-platform: POSIX flock
(multi-process safe) / Windows soft-degrade (single-process only,
RuntimeWarning on first use).
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Protocol, runtime_checkable

try:
    import fcntl
    _HAVE_FCNTL = True
except ImportError:        # Windows: fcntl unavailable
    fcntl = None           # type: ignore[assignment]
    _HAVE_FCNTL = False

_WARNED_NO_LOCK = False


def _lock_ex(fh) -> None:
    global _WARNED_NO_LOCK
    if _HAVE_FCNTL:
        fcntl.flock(fh, fcntl.LOCK_EX)
    elif not _WARNED_NO_LOCK:
        _WARNED_NO_LOCK = True
        warnings.warn(
            "seen_store.FileStore: fcntl unavailable (Windows); running "
            "WITHOUT multi-process lock - single-process use only",
            RuntimeWarning,
            stacklevel=3,
        )


def _unlock(fh) -> None:
    if _HAVE_FCNTL:
        fcntl.flock(fh, fcntl.LOCK_UN)
    # no-op when fcntl absent


@runtime_checkable
class SeenStore(Protocol):
    """Persistence contract for the OrderIdFactory dedup set.

    Implementors must provide:
    - load() → a snapshot of all previously persisted IDs (may return copy).
    - add(order_id) → durably record one ID; idempotent calls are allowed.
    """

    def load(self) -> set[str]:
        ...

    def add(self, order_id: str) -> None:
        ...


class InMemoryStore:
    """In-process SeenStore backed by a plain set.

    Default for unit tests and the no-store fallback.  Zero disk / zero
    network — satisfies CX4 isolation guarantee.
    """

    def __init__(self) -> None:
        self._data: set[str] = set()

    def load(self) -> set[str]:
        return set(self._data)

    def add(self, order_id: str) -> None:
        self._data.add(order_id)


class FileStore:
    """Append-only flat-file SeenStore.

    Each call to add() appends one line.  load() reads all lines on demand
    (called once at OrderIdFactory construction).  Empty lines are ignored.

    Both load() and add() hold fcntl.flock(LOCK_EX) over the critical
    section; LOCK_UN is released in a finally clause, so exceptions in the
    critical section do not leak the lock.

    LC-EXEC-5 resolved: fcntl.flock 排他锁已加，多进程串行写入安全。
    LC-XPLAT-1 resolved (P1): Cross-platform: POSIX flock (multi-process safe) /
    Windows soft-degrade (single-process only, RuntimeWarning on first use).
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def load(self) -> set[str]:
        if not self._path.exists():
            return set()
        with self._path.open("r", encoding="utf-8") as fh:
            _lock_ex(fh)
            try:
                content = fh.read()
            finally:
                _unlock(fh)
        return {line.strip() for line in content.splitlines() if line.strip()}

    def add(self, order_id: str) -> None:
        with self._path.open("a", encoding="utf-8") as fh:
            _lock_ex(fh)
            try:
                fh.write(order_id + "\n")
            finally:
                _unlock(fh)
