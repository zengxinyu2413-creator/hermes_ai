"""V25 trend strategy — NT BacktestEngine port (M2 one-period migration).

Faithfully replicates run_v25 single-bar logic.
Excluded (one-period scope): Bank profit extraction, rm draw-down half-pos, Monte Carlo.
"""
from __future__ import annotations

from collections import deque
from decimal import Decimal
from typing import Any

from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Quantity
from nautilus_trader.trading.strategy import Strategy, StrategyConfig


class V25TrendConfig(StrategyConfig, frozen=True):  # type: ignore[call-arg, misc]
    instrument_id: InstrumentId
    bar_type: BarType
    init_capital: str = "10000"
    size_precision: int = 2  # matches make_solusdt_binance size_precision


class V25TrendStrategy(Strategy):  # type: ignore[misc]
    """V25 trend-following strategy ported to nautilus BacktestEngine.

    Indicator set (all via rolling deques, matching V25's vectorised formulae):
      EMA20/50/100 — recursive ewm(adjust=False)
      ATR14        — rolling-14 mean of true range
      ADX14        — rolling-14 mean of DX (simple sums, not Wilder's, same as V25)
      high_20      — shift(1) rolling-20 max of bar highs
      recent_low   — shift(1) rolling-10 min of bar lows
      consecutive_up — streak of bullish bars (close > prev close)

    Position management mirrors V25 run_v25 for-po loop:
      Hard stops   : −18% / −12%(post-pyramid) / −6%(halve, once)
      Take profits : 8%→tp=1 (−10% initial) / 15%→tp=2 / 30%→tp=3
      Trailing stop: peak−6×ATR or dd2>0.55 (fires only when tp>0)
      Pyramid add  : high_20×0.995 breakout, 3 levels
      Dominance add: ADX>40 + consecutive_up≥4 (once per position)

    Entry (module C): consecutive-loss cooldown, blk filter, en condition,
    bp sizing 0.025/0.040/0.075 by ADX tier.
    """

    def __init__(self, config: V25TrendConfig) -> None:
        super().__init__(config)
        self._instrument_id: InstrumentId = config.instrument_id
        self._bar_type: BarType = config.bar_type
        self._init_capital: float = float(config.init_capital)
        self._sp: int = config.size_precision  # size_precision shorthand

        # equity tracker (mirrors V25's eq)
        self._eq: float = self._init_capital

        # position state dict — None when flat (mirrors V25's pos[0])
        self._pos: dict[str, Any] | None = None

        # cooldown / recent-loss counter (mirrors V25's cd / rl)
        self._cd: int = 0
        self._rl: int = 0

        # trade log (mirrors V25's tl)
        self._tl: list[float] = []

        # EMA state (float running values)
        self._ema20: float | None = None
        self._ema50: float | None = None
        self._ema100: float | None = None
        self._prev_ema20: float | None = None  # pr['ema20'] in V25

        # ATR14: rolling 14 true-range values
        self._tr_buf: deque[float] = deque(maxlen=14)
        self._atr: float | None = None

        # ADX14: rolling 14 +DM / −DM / DX values
        self._pdm_buf: deque[float] = deque(maxlen=14)
        self._mdm_buf: deque[float] = deque(maxlen=14)
        self._dx_buf: deque[float] = deque(maxlen=14)
        self._adx: float | None = None
        self._prev_adx: float | None = None  # pr['adx'] in V25

        # high_20 (shift-1): rolling-20 max of previous bars' highs
        self._high_hist: deque[float] = deque(maxlen=20)
        self._high_20: float | None = None

        # recent_low (shift-1): rolling-10 min of previous bars' lows
        self._low_hist: deque[float] = deque(maxlen=10)
        self._recent_low: float | None = None

        # consecutive bullish bars
        self._consecutive_up: int = 0

        # previous bar OHLC (for TR, DM, consecutive_up)
        self._prev_high: float | None = None
        self._prev_low: float | None = None
        self._prev_close: float | None = None

    # ── NT lifecycle ──────────────────────────────────────────────────────────

    def on_start(self) -> None:
        self.subscribe_bars(self._bar_type)

    def on_bar(self, bar: Bar) -> None:
        h = float(bar.high)
        lo = float(bar.low)
        p = float(bar.close)  # V25: p = row['close']

        self._update_indicators(h, lo, p)

        if not self._indicators_ready():
            return

        at: float = max(self._atr, 0.001)  # type: ignore[arg-type]
        ad: float = self._adx  # type: ignore[assignment]
        vf: float = at / p if p > 0 else 0.0

        if self._cd > 0:
            self._cd -= 1

        if self._pos is not None:
            self._manage_position(p, at, ad)

        if self._pos is None and self._cd == 0:
            self._try_entry(p, at, ad, vf)

        # save for next bar (mirrors V25's pr = df.iloc[i-1])
        self._prev_ema20 = self._ema20
        self._prev_adx = ad

    def on_stop(self) -> None:
        pass

    # ── indicator updates ─────────────────────────────────────────────────────

    def _update_indicators(self, h: float, lo: float, p: float) -> None:
        # EMA (ewm adjust=False → α·p + (1−α)·prev)
        a20, a50, a100 = 2.0 / 21, 2.0 / 51, 2.0 / 101
        self._ema20 = p if self._ema20 is None else a20 * p + (1 - a20) * self._ema20
        self._ema50 = p if self._ema50 is None else a50 * p + (1 - a50) * self._ema50
        self._ema100 = p if self._ema100 is None else a100 * p + (1 - a100) * self._ema100

        # True range
        if self._prev_close is not None:
            tr = max(h - lo, abs(h - self._prev_close), abs(lo - self._prev_close))
        else:
            tr = h - lo
        self._tr_buf.append(tr)
        self._atr = sum(self._tr_buf) / len(self._tr_buf) if len(self._tr_buf) == 14 else None

        # +DM / −DM (V25 vectorised formula)
        if self._prev_high is not None and self._prev_low is not None:
            up = h - self._prev_high
            dn = self._prev_low - lo
            pdm = max(up, 0.0) if up > dn else 0.0
            mdm = max(dn, 0.0) if dn > up else 0.0
        else:
            pdm = mdm = 0.0
        self._pdm_buf.append(pdm)
        self._mdm_buf.append(mdm)

        # ADX (V25 uses simple rolling sums, not Wilder's smoothing)
        if len(self._tr_buf) == 14 and len(self._pdm_buf) == 14:
            ts = sum(self._tr_buf)
            pdi = 100.0 * sum(self._pdm_buf) / ts if ts > 0 else 0.0
            mdi = 100.0 * sum(self._mdm_buf) / ts if ts > 0 else 0.0
            denom = pdi + mdi
            dx = abs(pdi - mdi) / denom * 100.0 if denom > 0 else 0.0
            self._dx_buf.append(dx)
            self._adx = sum(self._dx_buf) / len(self._dx_buf) if len(self._dx_buf) == 14 else None

        # high_20 / recent_low: compute BEFORE appending current bar (= shift-1 semantics)
        self._high_20 = max(self._high_hist) if len(self._high_hist) == 20 else None
        self._high_hist.append(h)
        self._recent_low = min(self._low_hist) if len(self._low_hist) == 10 else None
        self._low_hist.append(lo)

        # consecutive_up
        if self._prev_close is not None:
            self._consecutive_up = (self._consecutive_up + 1) if p > self._prev_close else 0

        self._prev_high = h
        self._prev_low = lo
        self._prev_close = p

    def _indicators_ready(self) -> bool:
        return (
            self._atr is not None
            and self._adx is not None
            and self._high_20 is not None
            and self._recent_low is not None
            and self._prev_ema20 is not None
            and self._prev_adx is not None
        )

    # ── order helpers ─────────────────────────────────────────────────────────

    def _qty(self, sz: float) -> Quantity | None:
        rounded = round(sz, self._sp)
        if rounded <= 0:
            return None
        return Quantity.from_str(f"{rounded:.{self._sp}f}")

    def _buy(self, sz: float) -> None:
        qty = self._qty(sz)
        if qty is None:
            return
        self.submit_order(
            self.order_factory.market(
                instrument_id=self._instrument_id,
                order_side=OrderSide.BUY,
                quantity=qty,
            )
        )

    def _sell(self, sz: float) -> None:
        qty = self._qty(sz)
        if qty is None:
            return
        self.submit_order(
            self.order_factory.market(
                instrument_id=self._instrument_id,
                order_side=OrderSide.SELL,
                quantity=qty,
            )
        )

    # ── position management (mirrors V25's "for po in pos[:]" block) ──────────

    def _manage_position(self, p: float, at: float, ad: float) -> None:
        po = self._pos
        assert po is not None

        pnl = (p - po["avg_price"]) / po["avg_price"]
        po["peak_price"] = max(po["peak_price"], p)
        mp = (po["peak_price"] - po["avg_price"]) / po["avg_price"]

        # ── hard stop −18% ──
        if pnl <= -0.18:
            self._eq += po["size"] * p
            self._tl.append(pnl)
            self._rl += 1
            self.close_all_positions(self._instrument_id)
            self._pos = None
            return

        # ── hard stop −12% after pyramid ──
        if pnl <= -0.12 and po["add_count"] > 0:
            self._eq += po["size"] * p
            self._tl.append(pnl)
            self._rl += 1
            self.close_all_positions(self._instrument_id)
            self._pos = None
            return

        # ── soft stop −6%: halve position (once) ──
        if pnl <= -0.06 and not po.get("ss", False):
            red = po["size"] * 0.5
            if red > 0:
                self._eq += red * p
                po["size"] -= red
                po["ss"] = True
                self._sell(red)

        # ── TP 8% → tp=1 ──
        if pnl >= 0.08 and po["tp"] == 0:
            cs = po["initial_size"] * 0.10
            if cs < po["size"]:
                self._eq += cs * p
                po["size"] -= cs
                self._sell(cs)
            po["tp"] = 1

        # ── TP 15% → tp=2 ──
        if pnl >= 0.15 and po["tp"] == 1:
            cs = po["initial_size"] * 0.10
            if cs < po["size"]:
                self._eq += cs * p
                po["size"] -= cs
                self._sell(cs)
            po["tp"] = 2

        # ── TP 30% → tp=3 ──
        if pnl >= 0.30 and po["tp"] == 2:
            cs = po["initial_size"] * 0.15
            if cs < po["size"]:
                self._eq += cs * p
                po["size"] -= cs
                self._sell(cs)
            po["tp"] = 3

        # ── ATR / drawdown trailing stop ──
        dd2 = 0.0
        if mp > 0.10 and (po["peak_price"] - po["avg_price"]) > 0:
            dd2 = (po["peak_price"] - p) / (po["peak_price"] - po["avg_price"])
        me = p < (po["peak_price"] - 6.0 * at) or dd2 > 0.55
        if me and po["tp"] > 0:
            self._eq += po["size"] * p
            self._tl.append(pnl)
            if pnl > 0:
                self._rl = 0
                self.close_all_positions(self._instrument_id)
                self._pos = None
                return
            # pnl<=0: fall through — V25 faithful (position stays in this edge case)

        # ── pyramid add ──
        if self._pos is not None and self._high_20 is not None and p > self._high_20 * 0.995:
            cost = 0.0
            ac = po["add_count"]
            if ac == 0:
                cost = po["base_val"]
            elif ac == 1 and p > po["peak_price"]:
                cost = po["base_val"] * 1.2
            elif ac == 2 and p > po["peak_price"]:
                cost = po["base_val"] * 1.5
            if cost > 0 and self._eq >= cost:
                sz = cost / p
                new_avg = (po["size"] * po["avg_price"] + cost) / (po["size"] + sz)
                po["avg_price"] = new_avg
                po["size"] += sz
                po["add_count"] += 1
                self._eq -= cost
                self._buy(sz)

        # ── dominance add ──
        if self._pos is not None and not po.get("dom", False):
            if ad > 40 and self._consecutive_up >= 4:
                cost = po["base_val"] * 2.0
                if self._eq >= cost:
                    sz = cost / p
                    new_avg = (po["size"] * po["avg_price"] + cost) / (po["size"] + sz)
                    po["avg_price"] = new_avg
                    po["size"] += sz
                    po["dom"] = True
                    self._eq -= cost
                    self._buy(sz)

    # ── entry (mirrors V25's module C) ───────────────────────────────────────

    def _try_entry(self, p: float, at: float, ad: float, vf: float) -> None:
        # consecutive-loss cooldown
        if self._rl >= 3:
            self._rl = 0
            self._cd = 24
            return

        # blocking filter (ema20<=pr_ema20 → trending down)
        if self._ema20 is None or self._prev_ema20 is None:
            return
        blk = vf < 0.02 or vf > 0.08 or ad < 20 or self._ema20 <= self._prev_ema20
        if blk:
            return

        # entry condition
        rl = self._recent_low
        rb = (p - rl) / rl if rl and rl > 0 else 0.0
        if self._ema50 is None or self._ema100 is None or self._prev_adx is None:
            return
        en = (
            p > self._ema50
            and p > self._ema100
            and ad > 20
            and ad > self._prev_adx
            and rb >= max(0.015, 0.8 * vf)
        )
        if not en:
            return

        # position sizing (rm=1.0 always — bank/drawdown excluded from one-period scope)
        bp = 0.025 if ad < 25 else (0.040 if ad < 35 else 0.075)
        bv = self._eq * bp
        sz = bv / p
        if self._qty(sz) is None:
            return

        self._pos = {
            "avg_price": p,
            "initial_size": sz,
            "size": sz,
            "base_val": bv,
            "peak_price": p,
            "add_count": 0,
            "tp": 0,
            "ss": False,
            "dom": False,
        }
        self._eq -= bv
        self._cd = 6
        self._buy(sz)
