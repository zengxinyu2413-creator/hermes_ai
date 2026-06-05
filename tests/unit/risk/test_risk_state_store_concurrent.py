"""Concurrent and exception-path tests for FileStateStore (CL8 + CL9)."""

from __future__ import annotations

import multiprocessing
from pathlib import Path

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
# CL9 — atomic-write invariants (supersedes old fcntl lock-release tests)
# ---------------------------------------------------------------------------

def test_cl9_no_fcntl_in_module():
    """LC-XPLAT-1 resolved: risk_state_store no longer imports fcntl."""
    import hermes.risk.risk_state_store as mod

    assert not hasattr(mod, "fcntl"), "fcntl must not be present — LC-XPLAT-1 fix"


def test_cl9_save_exception_no_residual(tmp_path, monkeypatch):
    """Atomic save: OSError during fsync leaves no tmp file; original is intact."""
    path = tmp_path / "state.json"
    store = FileStateStore(path)
    store.save({"state": "ACTIVE", "consecutive_losses": 0})

    def bad_fsync(fd: int) -> None:
        raise OSError("simulated fsync error")

    monkeypatch.setattr("os.fsync", bad_fsync)

    with pytest.raises(OSError):
        store.save({"state": "HALTED", "consecutive_losses": 5})

    assert list(tmp_path.glob(".state.json.*.tmp")) == []
    assert store.load() == {"state": "ACTIVE", "consecutive_losses": 0}
