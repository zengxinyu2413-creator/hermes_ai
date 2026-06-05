"""
Unit tests for V25TrendStrategy — pure logic (M2 route).

TestableV25 subclass overrides _buy/_sell/close_all_positions with call counters
and patches Strategy.__init__ to no-op so no NT engine is needed.
"""
from __future__ import annotations

from collections import deque
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.objects import Quantity

from hermes.strategies.v25_trend import V25TrendConfig, V25TrendStrategy


# ── helpers ──────────────────────────────────────────────────────────────────

def make_config() -> V25TrendConfig:
    return V25TrendConfig(
        instrument_id=InstrumentId(Symbol("SOLUSDT"), Venue("BINANCE")),
        bar_type=MagicMock(),
        init_capital=10_000.0,
        size_precision=3,
    )


def make_strategy() -> "TestableV25":
    cfg = make_config()
    with patch.object(V25TrendStrategy, "__init__", lambda self, config: None):
        strat = _TestableV25.__new__(_TestableV25)
        # manually replicate __init__ state (mirrors V25TrendStrategy.__init__)
        strat._instrument_id = cfg.instrument_id
        strat._bar_type = cfg.bar_type
        strat._init_capital = float(cfg.init_capital)
        strat._sp = cfg.size_precision
        strat._eq = strat._init_capital
        strat._pos = None
        strat._cd = 0
        strat._rl = 0
        strat._tl = []
        strat._ema20 = None
        strat._ema50 = None
        strat._ema100 = None
        strat._prev_ema20 = None
        strat._tr_buf = deque(maxlen=14)
        strat._atr = None
        strat._pdm_buf = deque(maxlen=14)
        strat._mdm_buf = deque(maxlen=14)
        strat._dx_buf = deque(maxlen=14)
        strat._adx = None
        strat._prev_adx = None
        strat._high_hist = deque(maxlen=20)
        strat._high_20 = None
        strat._low_hist = deque(maxlen=10)
        strat._recent_low = None
        strat._consecutive_up = 0
        strat._prev_high = None
        strat._prev_low = None
        strat._prev_close = None
        # counters
        strat._sell_calls: list[float] = []
        strat._buy_calls: list[float] = []
        strat._close_calls: int = 0
    return strat


def _pos(
    avg: float,
    size: float,
    initial_size: float | None = None,
    tp: int = 0,
    ss: bool = False,
    add_count: int = 0,
    peak_price: float | None = None,
) -> dict:
    if initial_size is None:
        initial_size = size
    if peak_price is None:
        peak_price = avg
    return {
        "avg_price": avg,
        "initial_size": initial_size,
        "size": size,
        "base_val": initial_size * avg,
        "peak_price": peak_price,
        "add_count": add_count,
        "tp": tp,
        "ss": ss,
        "dom": False,
    }


class _TestableV25(V25TrendStrategy):
    def _sell(self, sz: float) -> None:
        self._sell_calls.append(sz)

    def _buy(self, sz: float) -> None:
        self._buy_calls.append(sz)

    def close_all_positions(self, *args, **kwargs) -> None:  # type: ignore[override]
        self._close_calls += 1

    def _qty(self, sz: float) -> Quantity | None:
        return Quantity.from_str(f"{sz:.3f}")


# ── S3-A: hard stops (V-b) ────────────────────────────────────────────────────

class TestHardStops:
    def test_hard_stop_18_closes_position_no_sell(self):
        s = make_strategy()
        avg = 100.0
        size = 10.0
        s._pos = _pos(avg=avg, size=size)
        p = avg * (1 - 0.19)  # pnl = -0.19 < -0.18
        s._manage_position(p=p, at=1.0, ad=10.0)

        assert s._close_calls == 1
        assert len(s._sell_calls) == 0
        assert s._pos is None
        assert s._rl == 1

    def test_hard_stop_18_returns_no_fallthrough(self):
        """After -18% close, no TP or trailing logic fires."""
        s = make_strategy()
        avg = 100.0
        size = 10.0
        s._pos = _pos(avg=avg, size=size, tp=2)
        p = avg * (1 - 0.19)
        s._manage_position(p=p, at=1.0, ad=10.0)

        # only one close, no sells from TP logic
        assert s._close_calls == 1
        assert len(s._sell_calls) == 0

    def test_hard_stop_12_after_pyramid_sells_full_size(self):
        s = make_strategy()
        avg = 100.0
        size = 10.0
        s._pos = _pos(avg=avg, size=size, add_count=1)
        p = avg * (1 - 0.13)  # pnl = -0.13 <= -0.12, add_count=1
        s._manage_position(p=p, at=1.0, ad=10.0)

        assert s._close_calls == 1
        assert s._pos is None
        assert s._rl == 1

    def test_hard_stop_12_no_pyramid_does_not_fire(self):
        s = make_strategy()
        avg = 100.0
        size = 10.0
        s._pos = _pos(avg=avg, size=size, add_count=0)
        p = avg * (1 - 0.13)  # pnl = -0.13, but add_count=0
        s._manage_position(p=p, at=1.0, ad=10.0)

        # -12% guard requires add_count > 0; falls to soft stop (-6% not triggered here either)
        assert s._close_calls == 0

    def test_hard_stop_12_returns_no_fallthrough(self):
        """After -12%+pyramid close, no subsequent logic fires."""
        s = make_strategy()
        avg = 100.0
        size = 10.0
        s._pos = _pos(avg=avg, size=size, add_count=2, tp=3)
        p = avg * (1 - 0.13)
        s._manage_position(p=p, at=1.0, ad=10.0)

        assert s._close_calls == 1
        assert len(s._sell_calls) == 0


# ── S3-B: soft stop ss guard (V-c) ───────────────────────────────────────────

class TestSoftStopSSGuard:
    def test_soft_stop_fires_once_halves_position(self):
        s = make_strategy()
        avg = 100.0
        size = 10.0
        s._pos = _pos(avg=avg, size=size, ss=False)
        p = avg * (1 - 0.07)  # pnl = -0.07 <= -0.06
        s._manage_position(p=p, at=1.0, ad=10.0)

        assert len(s._sell_calls) == 1
        assert abs(s._sell_calls[0] - size * 0.5) < 1e-9
        assert s._pos["ss"] is True
        assert abs(s._pos["size"] - size * 0.5) < 1e-9

    def test_soft_stop_idempotent_when_ss_true(self):
        s = make_strategy()
        avg = 100.0
        size = 5.0  # already halved
        s._pos = _pos(avg=avg, size=size, ss=True)
        p = avg * (1 - 0.07)
        s._manage_position(p=p, at=1.0, ad=10.0)

        assert len(s._sell_calls) == 0

    def test_soft_stop_does_not_return_falls_through_to_tp(self):
        """Soft stop does NOT return; TP logic can still fire in same call."""
        s = make_strategy()
        avg = 100.0
        size = 20.0
        # pnl = -0.07 triggers ss, but also set tp=0 so TP block won't fire
        # (we just confirm _pos still exists after soft stop)
        s._pos = _pos(avg=avg, size=size, ss=False, tp=0)
        p = avg * (1 - 0.07)
        s._manage_position(p=p, at=1.0, ad=10.0)

        assert s._pos is not None  # position alive — no return after soft stop


# ── S3-C: TP ladder (V-d) ────────────────────────────────────────────────────

class TestTPLadder:
    def test_tp1_triggers_at_8pct_sells_10pct(self):
        s = make_strategy()
        avg = 100.0
        initial = 10.0
        size = 10.0
        s._pos = _pos(avg=avg, size=size, initial_size=initial, tp=0)
        p = avg * 1.09  # pnl ~ 0.09 >= 0.08
        s._manage_position(p=p, at=1.0, ad=10.0)

        assert s._pos["tp"] == 1
        assert len(s._sell_calls) == 1
        assert abs(s._sell_calls[0] - initial * 0.10) < 1e-9

    def test_tp2_triggers_at_15pct_sells_10pct(self):
        s = make_strategy()
        avg = 100.0
        initial = 10.0
        size = 9.0  # already had tp=1 sell
        s._pos = _pos(avg=avg, size=size, initial_size=initial, tp=1)
        p = avg * 1.16  # pnl ~ 0.16 >= 0.15
        s._manage_position(p=p, at=1.0, ad=10.0)

        assert s._pos["tp"] == 2
        assert len(s._sell_calls) == 1
        assert abs(s._sell_calls[0] - initial * 0.10) < 1e-9

    def test_tp3_triggers_at_30pct_sells_15pct(self):
        s = make_strategy()
        avg = 100.0
        initial = 10.0
        size = 8.0
        s._pos = _pos(avg=avg, size=size, initial_size=initial, tp=2)
        p = avg * 1.31  # pnl ~ 0.31 >= 0.30
        s._manage_position(p=p, at=1.0, ad=10.0)

        assert s._pos["tp"] == 3
        assert len(s._sell_calls) == 1
        assert abs(s._sell_calls[0] - initial * 0.15) < 1e-9

    def test_tp_size_guard_blocks_sell_when_cs_ge_size(self):
        """cs >= size → _sell not called, but tp state still advances."""
        s = make_strategy()
        avg = 100.0
        initial = 10.0
        size = 0.5  # tiny remaining — cs=1.0 > size=0.5
        s._pos = _pos(avg=avg, size=size, initial_size=initial, tp=0)
        p = avg * 1.09
        s._manage_position(p=p, at=1.0, ad=10.0)

        assert len(s._sell_calls) == 0
        assert s._pos["tp"] == 1

    def test_tp_state_machine_advances_0_to_1_to_2_to_3(self):
        s = make_strategy()
        avg = 100.0
        initial = 10.0
        size = 10.0

        # step to tp=1
        s._pos = _pos(avg=avg, size=size, initial_size=initial, tp=0)
        s._manage_position(p=avg * 1.09, at=1.0, ad=10.0)
        assert s._pos["tp"] == 1

        # step to tp=2
        s._pos["tp"] = 1
        s._sell_calls.clear()
        s._manage_position(p=avg * 1.16, at=1.0, ad=10.0)
        assert s._pos["tp"] == 2

        # step to tp=3
        s._pos["tp"] = 2
        s._sell_calls.clear()
        s._manage_position(p=avg * 1.31, at=1.0, ad=10.0)
        assert s._pos["tp"] == 3

    def test_tp1_does_not_fire_when_tp_already_1(self):
        s = make_strategy()
        avg = 100.0
        initial = 10.0
        size = 9.0
        s._pos = _pos(avg=avg, size=size, initial_size=initial, tp=1)
        p = avg * 1.09  # pnl>=0.08 but tp==1 not 0
        s._manage_position(p=p, at=1.0, ad=10.0)

        assert s._pos["tp"] == 1  # no advancement
        assert len(s._sell_calls) == 0


# ── S3-D: ATR / dd2 trailing stop (V-e) ──────────────────────────────────────

class TestTrailingStop:
    def _make_atr_trigger_pos(
        self,
        avg: float = 100.0,
        size: float = 10.0,
        tp: int = 2,
        pnl_sign: float = 1.09,
    ) -> tuple["TestableV25", float, float]:
        """Returns (strat, p, at) where p < peak - 6*at triggers ATR."""
        s = make_strategy()
        peak = avg * 1.20
        p = avg * pnl_sign
        at = (peak - p) / 6.0 - 0.01  # ensures p < peak - 6*at
        s._pos = _pos(avg=avg, size=size, tp=tp, peak_price=peak)
        return s, p, at

    # D1: ATR path, pnl>0 → close
    def test_D1_atr_trigger_pnl_positive_closes(self):
        s, p, at = self._make_atr_trigger_pos(pnl_sign=1.09)
        eq_before = s._eq
        s._manage_position(p=p, at=at, ad=10.0)

        assert s._close_calls == 1
        assert s._pos is None
        assert s._rl == 0
        assert s._eq > eq_before  # equity credited

    # D2: dd2 path, pnl>0 → close
    def test_D2_dd2_trigger_pnl_positive_closes(self):
        s = make_strategy()
        avg = 100.0
        size = 10.0
        peak = avg * 1.30   # mp = 0.30 > 0.10 ✓
        # dd2 = (peak - p)/(peak - avg) > 0.55 → p < peak - 0.55*(peak-avg)
        p = peak - 0.56 * (peak - avg)  # dd2 ~ 0.56 > 0.55
        assert p > avg  # pnl > 0
        at = 999.0  # ATR path not triggered (p >> peak-6*at irrelevant)
        s._pos = _pos(avg=avg, size=size, tp=2, peak_price=peak)
        s._manage_position(p=p, at=at, ad=10.0)

        assert s._close_calls == 1
        assert s._pos is None
        assert s._rl == 0

    # D3: faithful edge — me=True, tp>0, pnl<=0 → no close, no return, eq+append, fall-through
    def test_D3_faithful_edge_pnl_nonpositive_no_close(self):
        s = make_strategy()
        avg = 100.0
        size = 10.0
        peak = avg * 1.20
        # force pnl <= 0: p <= avg
        p = avg * 0.99   # pnl ~ -0.01
        at = (peak - p) / 6.0 + 0.01  # ATR trigger
        s._pos = _pos(avg=avg, size=size, tp=2, peak_price=peak)
        eq_before = s._eq
        tl_before = len(s._tl)
        s._manage_position(p=p, at=at, ad=10.0)

        assert s._close_calls == 0           # no close
        assert s._pos is not None            # position alive (no return)
        assert s._eq > eq_before             # _eq += size*p fired
        assert len(s._tl) == tl_before + 1  # _tl.append fired

    # D4: tp=0 gate — me=True but tp==0 → entire block skipped
    def test_D4_tp0_gate_blocks_trailing(self):
        # pnl=0.03: positive (above avg), < 0.08 so TP=1 block does NOT fire first
        s = make_strategy()
        avg = 100.0
        size = 10.0
        peak = avg * 1.20
        p = avg * 1.03  # pnl=0.03 < 0.08 → TP ladder silent
        at = (peak - p) / 6.0 - 0.01  # ATR triggered: p < peak-6*at
        s._pos = _pos(avg=avg, size=size, tp=0, peak_price=peak)
        s._manage_position(p=p, at=at, ad=10.0)

        assert s._close_calls == 0
        assert s._pos is not None

    # D5: dd2 not computed when mp<=0.10 → me stays False (no close)
    def test_D5_dd2_zero_when_mp_le_010(self):
        s = make_strategy()
        avg = 100.0
        size = 10.0
        # mp = (peak-avg)/avg <= 0.10
        peak = avg * 1.05  # mp=0.05 ≤ 0.10 → dd2 branch skipped → dd2=0.0
        # p chosen so ATR path also NOT triggered
        p = avg * 1.04
        at = (peak - p) / 6.0 + 0.01  # p > peak - 6*at → ATR not triggered
        s._pos = _pos(avg=avg, size=size, tp=2, peak_price=peak)
        s._manage_position(p=p, at=at, ad=10.0)

        assert s._close_calls == 0
        assert s._pos is not None
