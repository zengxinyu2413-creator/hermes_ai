"""Concurrent and exception-path tests for FileStateStore (CL8 + CL9)."""

from __future__ import annotations

import fcntl
import multiprocessing
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hermes.risk.risk_state_store import FileStateStore


# ---------------------------------------------------------------------------
# Module-level worker — must be picklable for multiprocessing
# ---------------------------------------------------------------------------

def _worker_save(path_str: str, state: dict) -> None:
    FileStateStore(path_str).save(state)


# ---------------------------------------------------------------------------
# CL8 — multi-process concurrent save: no JSON corruption
# ---------------------------------------------------------------------------

def test_concurrent_save_no_corruption(tmp_path):
    """Ten processes saving concurrently produce valid JSON (last-write-wins)."""
    path = str(tmp_path / "state.json")

    # Seed file with a valid initial state
    FileStateStore(path).save({"state": "ACTIVE", "consecutive_losses": 0})

    valid_states = [
        {"state": "ACTIVE", "consecutive_losses": i} for i in range(10)
    ]

    procs = [
        multiprocessing.Process(target=_worker_save, args=(path, s))
        for s in valid_states
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join()

    for i, p in enumerate(procs):
        assert p.exitcode == 0, f"worker-{i} exited with {p.exitcode}"

    result = FileStateStore(path).load()
    assert result is not None, "File is missing or empty after concurrent saves"
    assert "state" in result, f"Corrupted JSON — missing 'state' key: {result}"
    assert "consecutive_losses" in result, (
        f"Corrupted JSON — missing 'consecutive_losses' key: {result}"
    )
    assert result in valid_states, f"Unexpected state after concurrent saves: {result}"


# ---------------------------------------------------------------------------
# CL9 — exception in critical section: lock released via finally
# ---------------------------------------------------------------------------

def test_save_lock_released_on_exception(tmp_path, monkeypatch):
    """LOCK_UN is called in finally even when write raises — no lock leak."""
    from hermes.risk import risk_state_store as mod

    calls: list[int] = []
    monkeypatch.setattr(mod.fcntl, "flock", lambda fh, op: calls.append(op))

    store = FileStateStore(tmp_path / "state.json")

    # Verify normal path
    store.save({"state": "ACTIVE", "consecutive_losses": 0})
    assert calls == [fcntl.LOCK_EX, fcntl.LOCK_UN]
    calls.clear()

    # Inject failure in write — patch at class level
    mock_fh = MagicMock()
    mock_fh.write.side_effect = OSError("simulated disk error")
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_fh)
    mock_ctx.__exit__ = MagicMock(return_value=False)

    with patch.object(Path, "open", return_value=mock_ctx):
        with pytest.raises(OSError, match="simulated disk error"):
            store.save({"state": "HALTED", "consecutive_losses": 5})

    assert calls.count(fcntl.LOCK_EX) == 1, "LOCK_EX not acquired"
    assert calls.count(fcntl.LOCK_UN) == 1, "LOCK_UN not released — lock leaked!"


def test_load_lock_released_on_exception(tmp_path, monkeypatch):
    """LOCK_UN is called in finally even when read raises — no lock leak."""
    from hermes.risk import risk_state_store as mod

    (tmp_path / "state.json").write_text(
        '{"state":"ACTIVE","consecutive_losses":0}', encoding="utf-8"
    )

    calls: list[int] = []
    monkeypatch.setattr(mod.fcntl, "flock", lambda fh, op: calls.append(op))

    store = FileStateStore(tmp_path / "state.json")

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
