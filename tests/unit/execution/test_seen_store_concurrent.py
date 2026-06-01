"""Concurrent and exception-path tests for FileStore (CL7 + CL9)."""

from __future__ import annotations

import fcntl
import multiprocessing
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hermes.execution.seen_store import FileStore


# ---------------------------------------------------------------------------
# Module-level worker — must be picklable for multiprocessing
# ---------------------------------------------------------------------------

def _worker_add(path_str: str, ids: list[str]) -> None:
    store = FileStore(path_str)
    for id_ in ids:
        store.add(id_)


# ---------------------------------------------------------------------------
# CL7 — multi-process concurrent add: no write loss
# ---------------------------------------------------------------------------

def test_concurrent_add_no_write_loss(tmp_path):
    """Two processes writing concurrently lose no entries (flock serialises)."""
    path = str(tmp_path / "seen.txt")
    batch_a = [f"proc-a-{i}" for i in range(50)]
    batch_b = [f"proc-b-{i}" for i in range(50)]

    p1 = multiprocessing.Process(target=_worker_add, args=(path, batch_a))
    p2 = multiprocessing.Process(target=_worker_add, args=(path, batch_b))
    p1.start()
    p2.start()
    p1.join()
    p2.join()

    assert p1.exitcode == 0, f"proc-a exited with {p1.exitcode}"
    assert p2.exitcode == 0, f"proc-b exited with {p2.exitcode}"

    result = FileStore(path).load()
    expected = set(batch_a + batch_b)
    missing = expected - result
    assert not missing, f"Lost {len(missing)} writes: {sorted(missing)[:5]}..."


# ---------------------------------------------------------------------------
# CL9 — exception in critical section: lock released via finally
# ---------------------------------------------------------------------------

def test_add_lock_released_on_exception(tmp_path, monkeypatch):
    """LOCK_UN is called in finally even when write raises — no lock leak."""
    from hermes.execution import seen_store as mod

    calls: list[int] = []
    monkeypatch.setattr(mod.fcntl, "flock", lambda fh, op: calls.append(op))

    store = FileStore(tmp_path / "seen.txt")

    # Verify normal path: LOCK_EX then LOCK_UN
    store.add("ok")
    assert calls == [fcntl.LOCK_EX, fcntl.LOCK_UN]
    calls.clear()

    # Inject failure in write — patch at class level (instance attr is read-only)
    mock_fh = MagicMock()
    mock_fh.write.side_effect = OSError("simulated disk error")
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_fh)
    mock_ctx.__exit__ = MagicMock(return_value=False)

    with patch.object(Path, "open", return_value=mock_ctx):
        with pytest.raises(OSError, match="simulated disk error"):
            store.add("boom")

    assert calls.count(fcntl.LOCK_EX) == 1, "LOCK_EX not acquired"
    assert calls.count(fcntl.LOCK_UN) == 1, "LOCK_UN not released — lock leaked!"


def test_load_lock_released_on_exception(tmp_path, monkeypatch):
    """LOCK_UN is called in finally even when read raises — no lock leak."""
    from hermes.execution import seen_store as mod

    (tmp_path / "seen.txt").write_text("existing-id\n", encoding="utf-8")

    calls: list[int] = []
    monkeypatch.setattr(mod.fcntl, "flock", lambda fh, op: calls.append(op))

    store = FileStore(tmp_path / "seen.txt")

    mock_fh = MagicMock()
    mock_fh.read.side_effect = OSError("simulated read error")
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_fh)
    mock_ctx.__exit__ = MagicMock(return_value=False)

    with patch.object(Path, "open", return_value=mock_ctx):
        with pytest.raises(OSError, match="simulated read error"):
            store.load()

    assert calls.count(fcntl.LOCK_EX) == 1, "LOCK_EX not acquired"
    assert calls.count(fcntl.LOCK_UN) == 1, "LOCK_UN not released — lock leaked!"
