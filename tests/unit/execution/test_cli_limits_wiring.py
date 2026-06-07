"""CF9/CF10: equivalence pairing between the deleted cli.py::_parse_instrument_limits
and nt_instrument_to_limits_from_info, plus the documented missing-PPBS ValueError.

No network / testnet connection — all filter data is offline-fixed, real SOLUSDT
testnet reference values (see _SOL_FULL_FILTERS docstring for provenance).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from hermes.execution.nt_translate import nt_instrument_to_limits_from_info
from hermes.execution.precision import InstrumentLimits

# ---------------------------------------------------------------------------
# CF10a/b: frozen verbatim snapshot of the deleted cli.py::_parse_instrument_limits
#
# Source: cli.py::_parse_instrument_limits @ commit
#         91b8e6f0521d99de558fb31cf353f5c390434aa3 (function deleted in this
#         same refactor — kept here ONLY as an equivalence-pairing reference,
#         NOT production code; never imported/called outside this test file).
#
# Verify fidelity (CF10b — paste alongside this function in the run log):
#         git show 91b8e6f0521d99de558fb31cf353f5c390434aa3:src/hermes/cli.py \
#             | sed -n '/^def _parse_instrument_limits/,/^    )$/p'
# ---------------------------------------------------------------------------


def _frozen_parse_instrument_limits_snapshot(filters: list[dict]) -> InstrumentLimits:
    """Verbatim body of the deleted _parse_instrument_limits — see header comment."""
    price_tick = Decimal("0.01")
    price_min = Decimal("0")
    price_max = Decimal("0")
    qty_step = Decimal("0.001")
    qty_min = Decimal("0.001")
    qty_max = Decimal("9000")
    min_notional = Decimal("5")
    apply_min_to_market = True
    bid_mul_up = Decimal("5")
    bid_mul_down = Decimal("0.2")
    ask_mul_up = Decimal("5")
    ask_mul_down = Decimal("0.2")

    for f in filters:
        ft = f["filterType"]
        if ft == "PRICE_FILTER":
            price_tick = Decimal(f["tickSize"])
            price_min = Decimal(f["minPrice"])
            price_max = Decimal(f["maxPrice"])
        elif ft == "LOT_SIZE":
            qty_step = Decimal(f["stepSize"])
            qty_min = Decimal(f["minQty"])
            qty_max = Decimal(f["maxQty"])
        elif ft in ("NOTIONAL", "MIN_NOTIONAL"):
            min_notional = Decimal(f["minNotional"])
            apply_min_to_market = bool(f.get("applyMinToMarket", True))
        elif ft == "PERCENT_PRICE_BY_SIDE":
            bid_mul_up = Decimal(f["bidMultiplierUp"])
            bid_mul_down = Decimal(f["bidMultiplierDown"])
            ask_mul_up = Decimal(f["askMultiplierUp"])
            ask_mul_down = Decimal(f["askMultiplierDown"])

    return InstrumentLimits(
        price_tick=price_tick,
        price_min=price_min,
        price_max=price_max,
        qty_step=qty_step,
        qty_min=qty_min,
        qty_max=qty_max,
        min_notional=min_notional,
        apply_min_to_market=apply_min_to_market,
        bid_multiplier_up=bid_mul_up,
        bid_multiplier_down=bid_mul_down,
        ask_multiplier_up=ask_mul_up,
        ask_multiplier_down=ask_mul_down,
    )


# ---------------------------------------------------------------------------
# Offline-fixed real SOLUSDT exchangeInfo filters — no testnet connection.
#
# PRICE_FILTER / LOT_SIZE: constructed from the real SOLUSDT testnet reference
#   numeric values recorded in
#   tests/unit/execution/test_nt_translate.py::_SOL_INSTRUMENT_WITH_INFO
#   (provenance there: "matching step3_submit_cancel.py:59", i.e.
#   experiments/m3_probe/step3_submit_cancel.py:59-72 — a real captured
#   testnet instrument's price_increment/size_increment/min_quantity/
#   max_quantity/min_price/max_price translated back into raw filter dicts).
#
# PERCENT_PRICE_BY_SIDE / NOTIONAL: copied verbatim from
#   tests/unit/execution/test_nt_translate.py::_SOL_FILTERS
#   ("SOL PPBS and NOTIONAL filter dicts — true NOTIONAL 六字段形态 (CE4)").
# ---------------------------------------------------------------------------

_SOL_FULL_FILTERS: list[dict] = [
    {
        "filterType": "PRICE_FILTER",
        "minPrice": "0",
        "maxPrice": "0",
        "tickSize": "0.01",
    },
    {
        "filterType": "LOT_SIZE",
        "minQty": "0.001",
        "maxQty": "90000",
        "stepSize": "0.001",
    },
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


class _FakeMoney:
    def __init__(self, value: str) -> None:
        self._decimal = Decimal(value)

    def as_decimal(self) -> Decimal:
        return self._decimal


def _build_fake_instrument(filters: list[dict]) -> object:
    """Build a fake NT instrument whose 7 direct attrs are derived from the
    same *filters* list's PRICE_FILTER/LOT_SIZE/NOTIONAL entries, and whose
    .info["filters"] is that same list — the equivalence precondition: both
    paths read from one shared, real, offline-fixed source.
    """
    price_filter = next(f for f in filters if f["filterType"] == "PRICE_FILTER")
    lot_size_filter = next(f for f in filters if f["filterType"] == "LOT_SIZE")
    notional_filter = next(
        f for f in filters if f["filterType"] in ("NOTIONAL", "MIN_NOTIONAL")
    )

    class _FakeInstrument:
        pass

    instrument = _FakeInstrument()
    instrument.price_increment = Decimal(price_filter["tickSize"])  # type: ignore[attr-defined]
    instrument.size_increment = Decimal(lot_size_filter["stepSize"])  # type: ignore[attr-defined]
    instrument.min_quantity = Decimal(lot_size_filter["minQty"])  # type: ignore[attr-defined]
    instrument.max_quantity = Decimal(lot_size_filter["maxQty"])  # type: ignore[attr-defined]
    instrument.min_price = Decimal(price_filter["minPrice"])  # type: ignore[attr-defined]
    instrument.max_price = Decimal(price_filter["maxPrice"])  # type: ignore[attr-defined]
    instrument.min_notional = _FakeMoney(notional_filter["minNotional"])  # type: ignore[attr-defined]
    instrument.info = {"filters": filters}  # type: ignore[attr-defined]
    return instrument


# ---------------------------------------------------------------------------
# Block B test 1 — equivalence pairing (CF9/CF10c)
# ---------------------------------------------------------------------------


class TestEquivalencePairing:
    """Feed one shared, real, offline-fixed SOLUSDT filters JSON through the
    frozen snapshot of the deleted _parse_instrument_limits and through
    nt_instrument_to_limits_from_info; compare all 12 InstrumentLimits fields.
    """

    def _pair(self) -> tuple[InstrumentLimits, InstrumentLimits]:
        old = _frozen_parse_instrument_limits_snapshot(_SOL_FULL_FILTERS)
        fake = _build_fake_instrument(_SOL_FULL_FILTERS)
        new = nt_instrument_to_limits_from_info(fake)
        return old, new

    def test_price_tick_equal(self) -> None:
        old, new = self._pair()
        assert old.price_tick == new.price_tick

    def test_price_min_equal(self) -> None:
        old, new = self._pair()
        assert old.price_min == new.price_min

    def test_price_max_equal(self) -> None:
        old, new = self._pair()
        assert old.price_max == new.price_max

    def test_qty_step_equal(self) -> None:
        old, new = self._pair()
        assert old.qty_step == new.qty_step

    def test_qty_min_equal(self) -> None:
        old, new = self._pair()
        assert old.qty_min == new.qty_min

    def test_qty_max_equal(self) -> None:
        old, new = self._pair()
        assert old.qty_max == new.qty_max

    def test_min_notional_equal(self) -> None:
        old, new = self._pair()
        assert old.min_notional == new.min_notional

    def test_apply_min_to_market_equal(self) -> None:
        """Honest record (CF10c — no manufactured divergence):

        The real SOLUSDT NOTIONAL filter carries an explicit
        applyMinToMarket=True. The old snapshot reads it via
        bool(f.get("applyMinToMarket", True)) -> True; the new function reads
        it via its NOTIONAL-preferred branch -> True. Both land on True by
        EXPLICIT read, not by each side's differing absent-field default
        (old default True / new default False) — that divergence is a
        separate absent-field edge case, already covered in
        test_nt_translate.py (e.g. test_apply_min_to_market_none_becomes_false)
        and out of scope for this equivalence-pairing test.
        """
        old, new = self._pair()
        assert old.apply_min_to_market is True
        assert new.apply_min_to_market is True
        assert old.apply_min_to_market == new.apply_min_to_market

    def test_bid_multiplier_up_equal(self) -> None:
        old, new = self._pair()
        assert old.bid_multiplier_up == new.bid_multiplier_up

    def test_bid_multiplier_down_equal(self) -> None:
        old, new = self._pair()
        assert old.bid_multiplier_down == new.bid_multiplier_down

    def test_ask_multiplier_up_equal(self) -> None:
        old, new = self._pair()
        assert old.ask_multiplier_up == new.ask_multiplier_up

    def test_ask_multiplier_down_equal(self) -> None:
        old, new = self._pair()
        assert old.ask_multiplier_down == new.ask_multiplier_down

    def test_full_record_equal_twelve_of_twelve(self) -> None:
        """Frozen-dataclass __eq__ — all 12 fields identical in one assertion."""
        old, new = self._pair()
        assert old == new


# ---------------------------------------------------------------------------
# Block B test 2 — missing PERCENT_PRICE_BY_SIDE raises ValueError
# (documented behavior, nt_translate.py:113)
# ---------------------------------------------------------------------------


class TestMissingPPBSRaises:
    def test_missing_ppbs_raises_value_error(self) -> None:
        filters_without_ppbs = [
            f for f in _SOL_FULL_FILTERS if f["filterType"] != "PERCENT_PRICE_BY_SIDE"
        ]
        fake = _build_fake_instrument(filters_without_ppbs)
        with pytest.raises(ValueError, match="PERCENT_PRICE_BY_SIDE"):
            nt_instrument_to_limits_from_info(fake)
