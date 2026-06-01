"""Tests for RiskStateStore Protocol + InMemoryStateStore + FileStateStore — CK1~CK10."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hermes.risk.guard import GuardState, RiskDenied, RiskGuard
from hermes.risk.risk_state_store import FileStateStore, InMemoryStateStore, RiskStateStore


# ---------------------------------------------------------------------------
# CK5 — InMemoryStateStore: zero disk, zero network
# ---------------------------------------------------------------------------


class TestInMemoryStateStore:
    def test_ck5_empty_load_returns_none(self):
        store = InMemoryStateStore()
        assert store.load() is None

    def test_ck5_save_and_load_roundtrip(self):
        store = InMemoryStateStore()
        snap = {"state": "ACTIVE", "consecutive_losses": 2}
        store.save(snap)
        assert store.load() == snap

    def test_ck5_load_returns_copy(self):
        store = InMemoryStateStore()
        store.save({"state": "ACTIVE", "consecutive_losses": 0})
        loaded = store.load()
        assert loaded is not None
        loaded["consecutive_losses"] = 99
        assert store.load()["consecutive_losses"] == 0

    def test_ck5_protocol_satisfied(self):
        assert isinstance(InMemoryStateStore(), RiskStateStore)


# ---------------------------------------------------------------------------
# CK6 — FileStateStore tmp_path roundtrip
# ---------------------------------------------------------------------------


class TestFileStateStore:
    def test_ck6_missing_file_returns_none(self, tmp_path: Path):
        assert FileStateStore(tmp_path / "state.json").load() is None

    def test_ck6_save_and_load_roundtrip(self, tmp_path: Path):
        path = tmp_path / "state.json"
        snap = {"state": "HALTED", "consecutive_losses": 3}
        FileStateStore(path).save(snap)
        assert FileStateStore(path).load() == snap

    def test_ck6_save_overwrites(self, tmp_path: Path):
        path = tmp_path / "state.json"
        store = FileStateStore(path)
        store.save({"state": "ACTIVE", "consecutive_losses": 1})
        store.save({"state": "HALTED", "consecutive_losses": 3})
        assert store.load() == {"state": "HALTED", "consecutive_losses": 3}

    def test_ck6_no_workspace_residual(self, tmp_path: Path):
        path = tmp_path / "state.json"
        FileStateStore(path).save({"state": "ACTIVE", "consecutive_losses": 0})
        assert path.exists()
        assert not Path("state.json").exists()

    def test_ck6_protocol_satisfied(self, tmp_path: Path):
        assert isinstance(FileStateStore(tmp_path / "f.json"), RiskStateStore)


# ---------------------------------------------------------------------------
# CK3 — Cross-restart streak roundtrip (simulated via two guard instances)
# ---------------------------------------------------------------------------


class TestCrossRestartStreak:
    def test_ck3_streak_survives_restart(self, tmp_path: Path):
        path = tmp_path / "risk.json"
        guard_a = RiskGuard(
            consecutive_loss_limit=5,
            on_halt=lambda: None,
            state_store=FileStateStore(path),
        )
        for _ in range(3):
            guard_a.on_trade_result(Decimal("-1"))

        guard_b = RiskGuard(
            consecutive_loss_limit=5,
            on_halt=lambda: None,
            state_store=FileStateStore(path),
        )
        assert guard_b.consecutive_losses == 3
        assert guard_b.state is GuardState.ACTIVE

    def test_ck3_streak_reset_also_persists(self, tmp_path: Path):
        path = tmp_path / "risk.json"
        guard_a = RiskGuard(
            consecutive_loss_limit=5,
            on_halt=lambda: None,
            state_store=FileStateStore(path),
        )
        for _ in range(3):
            guard_a.on_trade_result(Decimal("-1"))
        guard_a.on_trade_result(Decimal("1"))  # resets streak to 0

        guard_b = RiskGuard(
            consecutive_loss_limit=5,
            on_halt=lambda: None,
            state_store=FileStateStore(path),
        )
        assert guard_b.consecutive_losses == 0
        assert guard_b.state is GuardState.ACTIVE


# ---------------------------------------------------------------------------
# CK4 — Cross-restart HALTED (D5: single-direction safety lock, no auto-clear)
# ---------------------------------------------------------------------------


class TestCrossRestartHalted:
    def test_ck4_consecutive_halt_survives_restart(self, tmp_path: Path):
        path = tmp_path / "risk.json"
        guard_a = RiskGuard(
            consecutive_loss_limit=3,
            on_halt=lambda: None,
            state_store=FileStateStore(path),
        )
        for _ in range(3):
            guard_a.on_trade_result(Decimal("-1"))
        assert guard_a.state is GuardState.HALTED

        guard_b = RiskGuard(
            consecutive_loss_limit=3,
            on_halt=lambda: None,
            state_store=FileStateStore(path),
        )
        assert guard_b.state is GuardState.HALTED

    def test_ck4_reloaded_halted_blocks_check_order(self, tmp_path: Path):
        path = tmp_path / "risk.json"
        guard_a = RiskGuard(
            consecutive_loss_limit=99,
            on_halt=lambda: None,
            state_store=FileStateStore(path),
        )
        guard_a.halt()

        guard_b = RiskGuard(
            consecutive_loss_limit=99,
            on_halt=lambda: None,
            state_store=FileStateStore(path),
        )
        assert guard_b.state is GuardState.HALTED
        with pytest.raises(RiskDenied):
            guard_b.check_order()

    def test_ck4_explicit_halt_persists(self, tmp_path: Path):
        path = tmp_path / "risk.json"
        RiskGuard(
            consecutive_loss_limit=99,
            on_halt=lambda: None,
            state_store=FileStateStore(path),
        ).halt()

        guard_b = RiskGuard(
            consecutive_loss_limit=99,
            on_halt=lambda: None,
            state_store=FileStateStore(path),
        )
        assert guard_b.state is GuardState.HALTED


# ---------------------------------------------------------------------------
# CK7 — save trigger points: streak change + explicit halt; store=None no-save
# ---------------------------------------------------------------------------


class TestSaveTriggerPoints:
    def _spy_store(self):
        store = MagicMock(spec=["load", "save"])
        store.load.return_value = None
        return store

    def test_ck7_loss_calls_save(self):
        store = self._spy_store()
        RiskGuard(consecutive_loss_limit=5, on_halt=lambda: None, state_store=store).on_trade_result(
            Decimal("-1")
        )
        store.save.assert_called_once()

    def test_ck7_win_calls_save(self):
        store = self._spy_store()
        RiskGuard(consecutive_loss_limit=5, on_halt=lambda: None, state_store=store).on_trade_result(
            Decimal("1")
        )
        store.save.assert_called_once()

    def test_ck7_halt_calls_save(self):
        store = self._spy_store()
        RiskGuard(consecutive_loss_limit=5, on_halt=lambda: None, state_store=store).halt()
        store.save.assert_called_once()

    def test_ck7_none_store_no_save_called(self):
        guard = RiskGuard(consecutive_loss_limit=3, on_halt=lambda: None)
        guard.on_trade_result(Decimal("-1"))
        guard.on_trade_result(Decimal("1"))
        guard.halt()
        assert guard._store is None  # no AttributeError, no save attempted


# ---------------------------------------------------------------------------
# CK8 — _daily_pnl not restored from store (D2 boundary)
# ---------------------------------------------------------------------------


class TestDailyPnlNotPersisted:
    def test_ck8_daily_pnl_zero_after_reload(self, tmp_path: Path):
        path = tmp_path / "risk.json"
        guard_a = RiskGuard(
            consecutive_loss_limit=99,
            on_halt=lambda: None,
            state_store=FileStateStore(path),
        )
        guard_a.on_trade_result(Decimal("-50"))
        assert guard_a.daily_pnl == Decimal("-50")

        guard_b = RiskGuard(
            consecutive_loss_limit=99,
            on_halt=lambda: None,
            state_store=FileStateStore(path),
        )
        assert guard_b.daily_pnl == Decimal(0)

    def test_ck8_daily_pnl_key_absent_from_saved_snapshot(self, tmp_path: Path):
        path = tmp_path / "risk.json"
        store = FileStateStore(path)
        guard = RiskGuard(
            consecutive_loss_limit=99,
            on_halt=lambda: None,
            state_store=store,
        )
        guard.on_trade_result(Decimal("-50"))
        snap = store.load()
        assert snap is not None
        assert "daily_pnl" not in snap


# ---------------------------------------------------------------------------
# CK1 — backward compat: store=None behaviour identical to pre-store baseline
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    def test_ck1_no_store_initial_state_active(self):
        guard = RiskGuard(consecutive_loss_limit=3, on_halt=lambda: None)
        assert guard.state is GuardState.ACTIVE
        assert guard.consecutive_losses == 0
        assert guard.daily_pnl == Decimal(0)

    def test_ck1_no_store_halts_on_n_losses(self):
        guard = RiskGuard(consecutive_loss_limit=3, on_halt=lambda: None)
        for _ in range(3):
            guard.on_trade_result(Decimal("-1"))
        assert guard.state is GuardState.HALTED

    def test_ck1_memory_store_no_prior_state_starts_active(self):
        guard = RiskGuard(
            consecutive_loss_limit=3,
            on_halt=lambda: None,
            state_store=InMemoryStateStore(),
        )
        assert guard.state is GuardState.ACTIVE
        assert guard.consecutive_losses == 0


# ---------------------------------------------------------------------------
# CK10 — LC-RISK-2 documentation check (static)
# ---------------------------------------------------------------------------


class TestLC2Documentation:
    def test_ck10_lc_risk2_in_module_docstring(self):
        import hermes.risk.risk_state_store as mod

        src = mod.__doc__ or ""
        assert "LC-RISK-2" in src

    def test_ck10_file_state_store_class_doc_mentions_lc_risk2(self):
        from hermes.risk.risk_state_store import FileStateStore as FS

        doc = FS.__doc__ or ""
        assert "LC-RISK-2" in doc
