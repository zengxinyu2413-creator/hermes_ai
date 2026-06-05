"""RiskStateStore: persistence protocol for RiskGuard state snapshots.

In scope: RiskStateStore Protocol, InMemoryStateStore (test default),
FileStateStore (JSON snapshot, atomic write via tempfile + os.replace).

State dict schema: {"state": "ACTIVE" | "HALTED", "consecutive_losses": int}.
_daily_pnl is intentionally excluded — daily accumulator has ambiguous semantics
across restarts (D2 boundary).

FileStateStore.save() writes to a tempfile in the same directory, fsyncs,
then os.replace()s into place; the reader never sees a truncated or partial file.

LC-RISK-2 superseded: 原子 os.replace 消除截断 race；单写设计，并发 writer = last-write-wins.
LC-RISK-4 resolved; LC-XPLAT-1 resolved: 无 fcntl，os.replace 跨平台原子.
"""

from __future__ import annotations

import json
import os
import tempfile
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

    save() writes to a tempfile in the same directory, fsyncs, then
    os.replace()s into place — atomic; the reader never sees a truncated file.
    load() reads the file on demand (called once at RiskGuard construction).
    A missing file returns None — not an error.

    LC-RISK-4 resolved: atomic os.replace eliminates the truncation race.
    LC-RISK-2 superseded: 原子 os.replace 消除截断 race；单写设计，并发 writer = last-write-wins.
    LC-XPLAT-1 resolved: 无 fcntl，os.replace 跨平台原子.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def load(self) -> dict | None:
        if not self._path.exists():
            return None
        return json.loads(self._path.read_text(encoding="utf-8"))

    def save(self, state: dict) -> None:
        fd, tmp = tempfile.mkstemp(
            prefix=f".{self._path.name}.", suffix=".tmp", dir=self._path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(state))
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self._path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
