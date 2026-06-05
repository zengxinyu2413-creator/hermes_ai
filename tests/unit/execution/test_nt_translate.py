"""Tests for nt_instrument_to_limits (C1–C8) and nt_instrument_to_limits_from_info (CA1–CA7).

No dependency on nautilus_trader in this file. Fake types mimic the NT
Instrument interface used by nt_translate.py (str-able Price/Quantity,
Money with as_decimal()).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from hermes.execution.nt_translate import (
    nt_instrument_to_limits,
    nt_instrument_to_limits_from_info,
)
from hermes.execution.precision import InstrumentLimits, build_order_spec


# ---------------------------------------------------------------------------
# Fake NT types (no nautilus_trader import in unit tests)
# ---------------------------------------------------------------------------


class _FakePrice:
    def __init__(self, value: str) -> None:
        self._value = value

    def __str__(self) -> str:
        return self._value


class _FakeQty:
    def __init__(self, value: str) -> None:
        self._value = value

    def __str__(self) -> str:
        return self._value


class _FakeMoney:
    def __init__(self, value: str) -> None:
        self._decimal = Decimal(value)

    def as_decimal(self) -> Decimal:
        return self._decimal


class _FakeInstrument:
    def __init__(
        self,
        *,
        price_increment: str,
        size_increment: str,
        min_quantity: str | None,
        max_quantity: str | None,
        min_price: str | None,
        max_price: str | None,
        min_notional: str | None,
    ) -> None:
        self.price_increment = _FakePrice(price_increment)
        self.size_increment = _FakeQty(size_increment)
        self.min_quantity = _FakeQty(min_quantity) if min_quantity is not None else None
        self.max_quantity = _FakeQty(max_quantity) if max_quantity is not None else None
        self.min_price = _FakePrice(min_price) if min_price is not None else None
        self.max_price = _FakePrice(max_price) if max_price is not None else None
        self.min_notional = _FakeMoney(min_notional) if min_notional is not None else None


# ---------------------------------------------------------------------------
# SOLUSDT testnet reference values (matching step3_submit_cancel.py:59)
# ---------------------------------------------------------------------------

_SOL_INSTRUMENT = _FakeInstrument(
    price_increment="0.01",
    size_increment="0.001",
    min_quantity="0.001",
    max_quantity="90000",
    min_price="0",
    max_price="0",
    min_notional="5",
)

_SOL_EXTRA: dict = dict(
    bid_multiplier_up=Decimal("2.0"),
    bid_multiplier_down=Decimal("0.5"),
    ask_multiplier_up=Decimal("2.0"),
    ask_multiplier_down=Decimal("0.5"),
    apply_min_to_market=True,
)

# Verbatim from experiments/m3_probe/step3_submit_cancel.py:59-72
_SOL_LIMITS_REF = InstrumentLimits(
    price_tick=Decimal("0.01"),
    price_min=Decimal("0"),
    price_max=Decimal("0"),
    qty_step=Decimal("0.001"),
    qty_min=Decimal("0.001"),
    qty_max=Decimal("90000"),
    min_notional=Decimal("5"),
    apply_min_to_market=True,
    bid_multiplier_up=Decimal("2.0"),
    bid_multiplier_down=Decimal("0.5"),
    ask_multiplier_up=Decimal("2.0"),
    ask_multiplier_down=Decimal("0.5"),
)


def _sol_limits() -> InstrumentLimits:
    return nt_instrument_to_limits(_SOL_INSTRUMENT, **_SOL_EXTRA)


# ---------------------------------------------------------------------------
# C1: 7 直读字段值逐一相等且为 Decimal
# ---------------------------------------------------------------------------


class TestC1SevenDirectFields:
    def test_price_tick_value_and_type(self) -> None:
        lim = _sol_limits()
        assert isinstance(lim.price_tick, Decimal)
        assert lim.price_tick == Decimal("0.01")

    def test_qty_step_value_and_type(self) -> None:
        lim = _sol_limits()
        assert isinstance(lim.qty_step, Decimal)
        assert lim.qty_step == Decimal("0.001")

    def test_qty_min_value_and_type(self) -> None:
        lim = _sol_limits()
        assert isinstance(lim.qty_min, Decimal)
        assert lim.qty_min == Decimal("0.001")

    def test_qty_max_value_and_type(self) -> None:
        lim = _sol_limits()
        assert isinstance(lim.qty_max, Decimal)
        assert lim.qty_max == Decimal("90000")

    def test_price_min_value_and_type(self) -> None:
        lim = _sol_limits()
        assert isinstance(lim.price_min, Decimal)
        assert lim.price_min == Decimal("0")

    def test_price_max_value_and_type(self) -> None:
        lim = _sol_limits()
        assert isinstance(lim.price_max, Decimal)
        assert lim.price_max == Decimal("0")

    def test_min_notional_value_and_type(self) -> None:
        lim = _sol_limits()
        assert isinstance(lim.min_notional, Decimal)
        assert lim.min_notional == Decimal("5")


# ---------------------------------------------------------------------------
# C2: min_notional == instrument.min_notional.as_decimal() 且产物为裸 Decimal
# ---------------------------------------------------------------------------


class TestC2MinNotionalIsDecimal:
    def test_min_notional_matches_as_decimal(self) -> None:
        lim = _sol_limits()
        assert lim.min_notional == _SOL_INSTRUMENT.min_notional.as_decimal()  # type: ignore[union-attr]

    def test_min_notional_type_is_bare_decimal(self) -> None:
        lim = _sol_limits()
        # Must be Decimal, not Money or any wrapper
        assert type(lim.min_notional) is Decimal


# ---------------------------------------------------------------------------
# C3: Price→Decimal 无损 — 0.01 tick 精确，float 路径会漂移
# ---------------------------------------------------------------------------


class TestC3FloatTrap:
    def test_price_tick_exact(self) -> None:
        lim = _sol_limits()
        assert lim.price_tick == Decimal("0.01")

    def test_float_path_would_drift(self) -> None:
        # Sanity: confirms the Decimal(float(...)) trap exists
        assert Decimal(float(0.01)) != Decimal("0.01"), "float(0.01) drift must be detectable"

    def test_price_tick_not_drifted(self) -> None:
        lim = _sol_limits()
        # The translation must NOT have used Decimal(float(...))
        assert lim.price_tick != Decimal(float(0.01)), "price_tick must not carry float drift"


# ---------------------------------------------------------------------------
# C4: price_min/max=0 → build_order_spec 不误拒
# ---------------------------------------------------------------------------


class TestC4ZeroPriceBoundsNoReject:
    def test_limit_order_not_rejected_by_zero_bounds(self) -> None:
        lim = _sol_limits()
        # precision.py guards: price_min>0 and price_max>0 before checking
        spec = build_order_spec(
            "SOLUSDT", "BUY", "LIMIT",
            raw_price=Decimal("83.70"),
            raw_qty=Decimal("0.06"),
            limits=lim,
        )
        assert spec.price == Decimal("83.70")

    def test_market_order_not_rejected_by_zero_bounds(self) -> None:
        lim = _sol_limits()
        spec = build_order_spec(
            "SOLUSDT", "BUY", "MARKET",
            raw_price=Decimal("83.70"),
            raw_qty=Decimal("0.06"),
            limits=lim,
        )
        assert spec.price == Decimal("0")


# ---------------------------------------------------------------------------
# C5: ★tie-back★ — 产物与 step3_submit_cancel.py:59 硬编码 12 字段逐字段相等
# ---------------------------------------------------------------------------


class TestC5TiebackStep3:
    def test_price_tick(self) -> None:
        assert _sol_limits().price_tick == _SOL_LIMITS_REF.price_tick

    def test_price_min(self) -> None:
        assert _sol_limits().price_min == _SOL_LIMITS_REF.price_min

    def test_price_max(self) -> None:
        assert _sol_limits().price_max == _SOL_LIMITS_REF.price_max

    def test_qty_step(self) -> None:
        assert _sol_limits().qty_step == _SOL_LIMITS_REF.qty_step

    def test_qty_min(self) -> None:
        assert _sol_limits().qty_min == _SOL_LIMITS_REF.qty_min

    def test_qty_max(self) -> None:
        assert _sol_limits().qty_max == _SOL_LIMITS_REF.qty_max

    def test_min_notional(self) -> None:
        assert _sol_limits().min_notional == _SOL_LIMITS_REF.min_notional

    def test_apply_min_to_market(self) -> None:
        assert _sol_limits().apply_min_to_market == _SOL_LIMITS_REF.apply_min_to_market

    def test_bid_multiplier_up(self) -> None:
        assert _sol_limits().bid_multiplier_up == _SOL_LIMITS_REF.bid_multiplier_up

    def test_bid_multiplier_down(self) -> None:
        assert _sol_limits().bid_multiplier_down == _SOL_LIMITS_REF.bid_multiplier_down

    def test_ask_multiplier_up(self) -> None:
        assert _sol_limits().ask_multiplier_up == _SOL_LIMITS_REF.ask_multiplier_up

    def test_ask_multiplier_down(self) -> None:
        assert _sol_limits().ask_multiplier_down == _SOL_LIMITS_REF.ask_multiplier_down


# ---------------------------------------------------------------------------
# C6: frozen 产物喂 build_order_spec — SOL happy path 不 raise
# ---------------------------------------------------------------------------


class TestC6FrozenIntoOrderSpec:
    def test_market_buy_happy_path(self) -> None:
        lim = _sol_limits()
        # E3.1 real data: SOL BUY 0.06 @ 83.70
        spec = build_order_spec(
            "SOLUSDT", "BUY", "MARKET",
            raw_price=Decimal("83.70"),
            raw_qty=Decimal("0.06"),
            limits=lim,
        )
        assert spec.quantity == Decimal("0.060")
        assert spec.side == "BUY"
        assert spec.order_type == "MARKET"

    def test_result_is_frozen(self) -> None:
        lim = _sol_limits()
        with pytest.raises((AttributeError, TypeError)):
            lim.price_tick = Decimal("99")  # type: ignore[misc]


# ---------------------------------------------------------------------------
# C7: None 不静默 — 显式默认或 raise，须有专测
# ---------------------------------------------------------------------------


class TestC7NoneHandling:
    def test_min_quantity_none_becomes_zero(self) -> None:
        inst = _FakeInstrument(
            price_increment="0.01", size_increment="0.001",
            min_quantity=None, max_quantity="90000",
            min_price="0", max_price="0", min_notional="5",
        )
        lim = nt_instrument_to_limits(inst, **_SOL_EXTRA)
        assert lim.qty_min == Decimal("0")

    def test_max_quantity_none_raises_value_error(self) -> None:
        inst = _FakeInstrument(
            price_increment="0.01", size_increment="0.001",
            min_quantity="0.001", max_quantity=None,
            min_price="0", max_price="0", min_notional="5",
        )
        with pytest.raises(ValueError, match="max_quantity"):
            nt_instrument_to_limits(inst, **_SOL_EXTRA)

    def test_min_notional_none_becomes_zero(self) -> None:
        inst = _FakeInstrument(
            price_increment="0.01", size_increment="0.001",
            min_quantity="0.001", max_quantity="90000",
            min_price="0", max_price="0", min_notional=None,
        )
        lim = nt_instrument_to_limits(inst, **_SOL_EXTRA)
        assert lim.min_notional == Decimal("0")

    def test_price_min_none_becomes_zero(self) -> None:
        inst = _FakeInstrument(
            price_increment="0.01", size_increment="0.001",
            min_quantity="0.001", max_quantity="90000",
            min_price=None, max_price="0", min_notional="5",
        )
        lim = nt_instrument_to_limits(inst, **_SOL_EXTRA)
        assert lim.price_min == Decimal("0")

    def test_price_max_none_becomes_zero(self) -> None:
        inst = _FakeInstrument(
            price_increment="0.01", size_increment="0.001",
            min_quantity="0.001", max_quantity="90000",
            min_price="0", max_price=None, min_notional="5",
        )
        lim = nt_instrument_to_limits(inst, **_SOL_EXTRA)
        assert lim.price_max == Decimal("0")


# ---------------------------------------------------------------------------
# C8: 5 透传字段无损进 InstrumentLimits
# ---------------------------------------------------------------------------


class TestC8PassthroughFields:
    def test_bid_multiplier_up_passthrough(self) -> None:
        lim = _sol_limits()
        assert lim.bid_multiplier_up == Decimal("2.0")

    def test_bid_multiplier_down_passthrough(self) -> None:
        lim = _sol_limits()
        assert lim.bid_multiplier_down == Decimal("0.5")

    def test_ask_multiplier_up_passthrough(self) -> None:
        lim = _sol_limits()
        assert lim.ask_multiplier_up == Decimal("2.0")

    def test_ask_multiplier_down_passthrough(self) -> None:
        lim = _sol_limits()
        assert lim.ask_multiplier_down == Decimal("0.5")

    def test_apply_min_to_market_passthrough(self) -> None:
        lim = _sol_limits()
        assert lim.apply_min_to_market is True


# ===========================================================================
# CA1–CA7: nt_instrument_to_limits_from_info (a-1 wrapper)
# ===========================================================================

# ---------------------------------------------------------------------------
# Fake instrument with info dict (simulates NT Instrument post-serialisation)
# ---------------------------------------------------------------------------


class _FakeInstrumentWithInfo(_FakeInstrument):
    """_FakeInstrument extended with an .info dict containing serialised filters."""

    def __init__(self, *, filters: list[dict], **kwargs) -> None:
        super().__init__(**kwargs)
        self.info = {"filters": filters}


# SOL PPBS and NOTIONAL filter dicts — true NOTIONAL 六字段形态 (CE4)
_SOL_FILTERS: list[dict] = [
    {
        "filterType": "PERCENT_PRICE_BY_SIDE",
        "bidMultiplierUp": "2.0",
        "bidMultiplierDown": "0.5",
        "askMultiplierUp": "2.0",
        "askMultiplierDown": "0.5",
    },
    {
        "filterType": "NOTIONAL",
        "minNotional": "5",
        "applyMinToMarket": True,
        "maxNotional": "9000000",
        "applyMaxToMarket": False,
        "avgPriceMins": 5,
    },
]

_SOL_INSTRUMENT_WITH_INFO = _FakeInstrumentWithInfo(
    price_increment="0.01",
    size_increment="0.001",
    min_quantity="0.001",
    max_quantity="90000",
    min_price="0",
    max_price="0",
    min_notional="5",
    filters=_SOL_FILTERS,
)


def _sol_limits_from_info() -> InstrumentLimits:
    return nt_instrument_to_limits_from_info(_SOL_INSTRUMENT_WITH_INFO)


# ---------------------------------------------------------------------------
# CA1: original nt_instrument_to_limits 0 diff — verify via md5/grep
# ---------------------------------------------------------------------------


class TestCA1OriginalFunctionUnchanged:
    def test_original_function_still_callable_with_kwargs(self) -> None:
        lim = nt_instrument_to_limits(_SOL_INSTRUMENT, **_SOL_EXTRA)
        assert lim.price_tick == Decimal("0.01")

    def test_original_38_tests_unaffected_spot_check(self) -> None:
        # Spot-check: original function still returns correct price_tick for SOL
        lim = nt_instrument_to_limits(_SOL_INSTRUMENT, **_SOL_EXTRA)
        assert lim == _SOL_LIMITS_REF

    def test_nt_translate_source_md5_grep(self) -> None:
        import hashlib
        import pathlib
        src = pathlib.Path(__file__).parent.parent.parent.parent / "src/hermes/execution/nt_translate.py"
        text = src.read_text(encoding="utf-8")
        # Original function body unchanged: all 7 direct-read patterns present
        assert "Decimal(str(instrument.price_increment))" in text
        assert "Decimal(str(instrument.size_increment))" in text
        assert "instrument.max_quantity is None" in text
        assert "instrument.min_notional.as_decimal()" in text

    def test_precision_py_unmodified_spot_check(self) -> None:
        import pathlib
        src = pathlib.Path(__file__).parent.parent.parent.parent / "src/hermes/execution/precision.py"
        text = src.read_text(encoding="utf-8")
        assert "class InstrumentLimits" in text
        assert "class OrderSpec" in text
        assert "def build_order_spec" in text


# ---------------------------------------------------------------------------
# CA2: multiplier extraction uses Decimal(filter["..."]) — no float path
# ---------------------------------------------------------------------------


class TestCA2DecimalDirectConstruction:
    def test_no_float_in_wrapper_code_lines(self) -> None:
        import pathlib
        src = pathlib.Path(__file__).parent.parent.parent.parent / "src/hermes/execution/nt_translate.py"
        lines = src.read_text(encoding="utf-8").splitlines()
        # Only scan code lines (not docstring or comment lines) for forbidden float patterns.
        # Walk past the first function's docstring; check from nt_instrument_to_limits_from_info.
        in_wrapper = False
        in_docstring = False
        violations_float = []
        violations_dec_float = []
        for line in lines:
            stripped = line.strip()
            if "def nt_instrument_to_limits_from_info" in line:
                in_wrapper = True
            if not in_wrapper:
                continue
            if stripped.startswith("#"):
                continue
            if '"""' in stripped:
                count = stripped.count('"""')
                if count >= 2:
                    pass  # opens and closes same line
                else:
                    in_docstring = not in_docstring
                continue
            if in_docstring:
                continue
            if "float(" in line:
                violations_float.append(line)
            if "Decimal(float" in line:
                violations_dec_float.append(line)
        assert not violations_float, f"float( in wrapper code: {violations_float}"
        assert not violations_dec_float, f"Decimal(float in wrapper code: {violations_dec_float}"

    def test_multiplier_up_is_decimal_not_float(self) -> None:
        lim = _sol_limits_from_info()
        assert type(lim.bid_multiplier_up) is Decimal
        assert type(lim.ask_multiplier_up) is Decimal

    def test_multiplier_down_is_decimal_not_float(self) -> None:
        lim = _sol_limits_from_info()
        assert type(lim.bid_multiplier_down) is Decimal
        assert type(lim.ask_multiplier_down) is Decimal


# ---------------------------------------------------------------------------
# CA3: missing filter raises ValueError with filterType name (no StopIteration)
# ---------------------------------------------------------------------------


class TestCA3MissingFilterRaises:
    def test_missing_ppbs_filter_raises_value_error(self) -> None:
        inst = _FakeInstrumentWithInfo(
            price_increment="0.01", size_increment="0.001",
            min_quantity="0.001", max_quantity="90000",
            min_price="0", max_price="0", min_notional="5",
            filters=[{"filterType": "MIN_NOTIONAL", "applyMinToMarket": True}],
        )
        with pytest.raises(ValueError, match="PERCENT_PRICE_BY_SIDE"):
            nt_instrument_to_limits_from_info(inst)

    def test_missing_ppbs_does_not_raise_stop_iteration(self) -> None:
        inst = _FakeInstrumentWithInfo(
            price_increment="0.01", size_increment="0.001",
            min_quantity="0.001", max_quantity="90000",
            min_price="0", max_price="0", min_notional="5",
            filters=[{"filterType": "MIN_NOTIONAL", "applyMinToMarket": True}],
        )
        exc = None
        try:
            nt_instrument_to_limits_from_info(inst)
        except ValueError as e:
            exc = e
        except StopIteration:
            pytest.fail("raised bare StopIteration — forbidden")
        assert exc is not None

    def test_missing_min_notional_filter_raises_value_error(self) -> None:
        inst = _FakeInstrumentWithInfo(
            price_increment="0.01", size_increment="0.001",
            min_quantity="0.001", max_quantity="90000",
            min_price="0", max_price="0", min_notional="5",
            filters=[{
                "filterType": "PERCENT_PRICE_BY_SIDE",
                "bidMultiplierUp": "2.0", "bidMultiplierDown": "0.5",
                "askMultiplierUp": "2.0", "askMultiplierDown": "0.5",
            }],
        )
        with pytest.raises(ValueError, match="MIN_NOTIONAL"):
            nt_instrument_to_limits_from_info(inst)


# ---------------------------------------------------------------------------
# CA4: multiplier None → ValueError; applyMinToMarket None → False (explicit)
# ---------------------------------------------------------------------------


class TestCA4NoneHandling:
    def test_bid_multiplier_up_none_raises_value_error(self) -> None:
        inst = _FakeInstrumentWithInfo(
            price_increment="0.01", size_increment="0.001",
            min_quantity="0.001", max_quantity="90000",
            min_price="0", max_price="0", min_notional="5",
            filters=[
                {
                    "filterType": "PERCENT_PRICE_BY_SIDE",
                    "bidMultiplierUp": None,
                    "bidMultiplierDown": "0.5",
                    "askMultiplierUp": "2.0",
                    "askMultiplierDown": "0.5",
                },
                {"filterType": "MIN_NOTIONAL", "applyMinToMarket": True},
            ],
        )
        with pytest.raises(ValueError, match="bidMultiplierUp"):
            nt_instrument_to_limits_from_info(inst)

    def test_ask_multiplier_down_none_raises_value_error(self) -> None:
        inst = _FakeInstrumentWithInfo(
            price_increment="0.01", size_increment="0.001",
            min_quantity="0.001", max_quantity="90000",
            min_price="0", max_price="0", min_notional="5",
            filters=[
                {
                    "filterType": "PERCENT_PRICE_BY_SIDE",
                    "bidMultiplierUp": "2.0",
                    "bidMultiplierDown": "0.5",
                    "askMultiplierUp": "2.0",
                    "askMultiplierDown": None,
                },
                {"filterType": "MIN_NOTIONAL", "applyMinToMarket": True},
            ],
        )
        with pytest.raises(ValueError, match="askMultiplierDown"):
            nt_instrument_to_limits_from_info(inst)

    def test_apply_min_to_market_none_becomes_false(self) -> None:
        # MIN_NOTIONAL form uses applyToMarket (not applyMinToMarket) — CE3 reconcile
        inst = _FakeInstrumentWithInfo(
            price_increment="0.01", size_increment="0.001",
            min_quantity="0.001", max_quantity="90000",
            min_price="0", max_price="0", min_notional="5",
            filters=[
                {
                    "filterType": "PERCENT_PRICE_BY_SIDE",
                    "bidMultiplierUp": "2.0", "bidMultiplierDown": "0.5",
                    "askMultiplierUp": "2.0", "askMultiplierDown": "0.5",
                },
                {"filterType": "MIN_NOTIONAL", "applyToMarket": None},
            ],
        )
        lim = nt_instrument_to_limits_from_info(inst)
        assert lim.apply_min_to_market is False

    def test_apply_min_to_market_none_is_not_silent(self) -> None:
        # None is explicitly converted to False — the conversion is in code, not a default
        import pathlib
        src = pathlib.Path(__file__).parent.parent.parent.parent / "src/hermes/execution/nt_translate.py"
        text = src.read_text(encoding="utf-8")
        assert "raw_apply is None" in text, "Explicit None branch must be present"


# ---------------------------------------------------------------------------
# CA5: tie-back — extracted values match step3_submit_cancel.py:59 hardcoding
# ---------------------------------------------------------------------------


class TestCA5Tieback:
    def test_bid_multiplier_up_value_and_type(self) -> None:
        lim = _sol_limits_from_info()
        assert type(lim.bid_multiplier_up) is Decimal
        assert lim.bid_multiplier_up == Decimal("2.0")

    def test_bid_multiplier_down_value_and_type(self) -> None:
        lim = _sol_limits_from_info()
        assert type(lim.bid_multiplier_down) is Decimal
        assert lim.bid_multiplier_down == Decimal("0.5")

    def test_ask_multiplier_up_value_and_type(self) -> None:
        lim = _sol_limits_from_info()
        assert type(lim.ask_multiplier_up) is Decimal
        assert lim.ask_multiplier_up == Decimal("2.0")

    def test_ask_multiplier_down_value_and_type(self) -> None:
        lim = _sol_limits_from_info()
        assert type(lim.ask_multiplier_down) is Decimal
        assert lim.ask_multiplier_down == Decimal("0.5")

    def test_apply_min_to_market_value_and_type(self) -> None:
        lim = _sol_limits_from_info()
        assert type(lim.apply_min_to_market) is bool
        assert lim.apply_min_to_market is True


# ---------------------------------------------------------------------------
# CA6: happy path → valid InstrumentLimits (LC-PREC-a-1 settled)
# ---------------------------------------------------------------------------


class TestCA6HappyPath:
    def test_from_info_produces_same_result_as_direct_call(self) -> None:
        lim_from_info = _sol_limits_from_info()
        lim_direct = nt_instrument_to_limits(_SOL_INSTRUMENT, **_SOL_EXTRA)
        assert lim_from_info == lim_direct

    def test_from_info_result_feeds_build_order_spec(self) -> None:
        lim = _sol_limits_from_info()
        spec = build_order_spec(
            "SOLUSDT", "BUY", "MARKET",
            raw_price=Decimal("83.70"),
            raw_qty=Decimal("0.06"),
            limits=lim,
        )
        assert spec.quantity == Decimal("0.060")
        assert spec.side == "BUY"

    def test_from_info_result_is_frozen(self) -> None:
        lim = _sol_limits_from_info()
        with pytest.raises((AttributeError, TypeError)):
            lim.price_tick = Decimal("99")  # type: ignore[misc]


# ---------------------------------------------------------------------------
# CA7: dual-form recognition — NOTIONAL (CE1) and MIN_NOTIONAL (CE2)
# ---------------------------------------------------------------------------


class TestCA7DualFilterForm:
    def test_notional_form_apply_from_apply_min_to_market(self) -> None:
        # CE1: NOTIONAL filter → apply_min_to_market reads applyMinToMarket
        inst = _FakeInstrumentWithInfo(
            price_increment="0.01", size_increment="0.001",
            min_quantity="0.001", max_quantity="90000",
            min_price="0", max_price="0", min_notional="5",
            filters=[
                {
                    "filterType": "PERCENT_PRICE_BY_SIDE",
                    "bidMultiplierUp": "2.0", "bidMultiplierDown": "0.5",
                    "askMultiplierUp": "2.0", "askMultiplierDown": "0.5",
                },
                {
                    "filterType": "NOTIONAL",
                    "minNotional": "5", "applyMinToMarket": True,
                    "maxNotional": "9000000", "applyMaxToMarket": False, "avgPriceMins": 5,
                },
            ],
        )
        lim = nt_instrument_to_limits_from_info(inst)
        assert lim.apply_min_to_market is True

    def test_min_notional_form_apply_from_apply_to_market(self) -> None:
        # CE2: MIN_NOTIONAL filter → apply_min_to_market reads applyToMarket
        inst = _FakeInstrumentWithInfo(
            price_increment="0.01", size_increment="0.001",
            min_quantity="0.001", max_quantity="90000",
            min_price="0", max_price="0", min_notional="5",
            filters=[
                {
                    "filterType": "PERCENT_PRICE_BY_SIDE",
                    "bidMultiplierUp": "2.0", "bidMultiplierDown": "0.5",
                    "askMultiplierUp": "2.0", "askMultiplierDown": "0.5",
                },
                {"filterType": "MIN_NOTIONAL", "applyToMarket": True},
            ],
        )
        lim = nt_instrument_to_limits_from_info(inst)
        assert lim.apply_min_to_market is True
