"""SeenStore: persistence protocol for OrderIdFactory dedup set.

In scope: SeenStore Protocol, InMemoryStore (test default), FileStore
(append-only, POSIX multi-process safe via fcntl.flock).

FileStore uses fcntl.flock(LOCK_EX) to serialise concurrent access from
multiple processes; LOCK_UN is released in a finally clause so exceptions
in the critical section do not leak the lock.

LC-EXEC-5 resolved: fcntl.flock 排他锁已加，多进程串行写入安全。
LC-XPLAT-1: POSIX (Linux) only — fcntl is not available on Windows;
Windows support not implemented.
"""

from __future__ import annotations

import fcntl
from pathlib import Path
from typing import Protocol, runtime_checkable


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
    LC-XPLAT-1: POSIX (Linux) only — Windows not supported.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def load(self) -> set[str]:
        if not self._path.exists():
            return set()
        with self._path.open("r", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                content = fh.read()
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)
        return {line.strip() for line in content.splitlines() if line.strip()}

    def add(self, order_id: str) -> None:
        with self._path.open("a", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                fh.write(order_id + "\n")
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)
