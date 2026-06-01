"""Tests for position_realized_pnl_extractor: CE1 / CE2 / CE3."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from hermes.execution.exec_bridge import position_realized_pnl_extractor


def _make_position_event(realized_pnl_decimal: Decimal) -> MagicMock:
    """Build a mock PositionEvent with the given realized_pnl value."""
    money = MagicMock()
    money.as_decimal.return_value = realized_pnl_decimal
    event = MagicMock()
    event.realized_pnl = money
    return event


# ── CE1: returns Decimal via as_decimal(), no Decimal(str()) / float() ────────

class TestCE1ExtractorUsesAsDecimal:
    def test_return_type_is_decimal(self):
        event = _make_position_event(Decimal("12.50"))
        result = position_realized_pnl_extractor(event)
        assert isinstance(result, Decimal)

    def test_as_decimal_called_exactly_once(self):
        event = _make_position_event(Decimal("5.00"))
        position_realized_pnl_extractor(event)
        event.realized_pnl.as_decimal.assert_called_once()

    def test_no_float_or_str_conversion_in_source(self):
        import inspect
        import re
        src = inspect.getsource(position_realized_pnl_extractor)
        # Strip docstring before searching
        body_start = src.find('return ')
        body = src[body_start:]
        assert re.search(r'Decimal\s*\(\s*str\s*\(', body) is None, \
            "extractor body must not use Decimal(str(...))"
        assert re.search(r'float\s*\(', body) is None, \
            "extractor body must not use float(...)"


# ── CE2: all three PositionEvent subclasses yield realized_pnl ────────────────

class TestCE2AllSubclasses:
    def test_position_opened_realized_pnl(self):
        from nautilus_trader.model.events.position import PositionOpened
        event = MagicMock(spec=PositionOpened)
        event.realized_pnl.as_decimal.return_value = Decimal("3.00")
        assert position_realized_pnl_extractor(event) == Decimal("3.00")

    def test_position_changed_realized_pnl(self):
        from nautilus_trader.model.events.position import PositionChanged
        event = MagicMock(spec=PositionChanged)
        event.realized_pnl.as_decimal.return_value = Decimal("7.50")
        assert position_realized_pnl_extractor(event) == Decimal("7.50")

    def test_position_closed_realized_pnl(self):
        from nautilus_trader.model.events.position import PositionClosed
        event = MagicMock(spec=PositionClosed)
        event.realized_pnl.as_decimal.return_value = Decimal("20.00")
        assert position_realized_pnl_extractor(event) == Decimal("20.00")


# ── CE3: cumulative semantics — returns NT value directly, no delta ───────────

class TestCE3CumulativeSemantics:
    def test_returns_nt_value_directly(self):
        """event.realized_pnl=X → extractor returns X (no delta subtraction)."""
        event = _make_position_event(Decimal("100.00"))
        assert position_realized_pnl_extractor(event) == Decimal("100.00")

    def test_second_call_independent_of_first(self):
        """Calling extractor twice with different events returns each event's value."""
        e1 = _make_position_event(Decimal("50.00"))
        e2 = _make_position_event(Decimal("80.00"))
        r1 = position_realized_pnl_extractor(e1)
        r2 = position_realized_pnl_extractor(e2)
        # If extractor were doing delta: r2 would be 30, not 80.
        assert r1 == Decimal("50.00")
        assert r2 == Decimal("80.00")

    def test_negative_realized_pnl_returned_as_is(self):
        """Losses (negative pnl) pass through unchanged."""
        event = _make_position_event(Decimal("-15.75"))
        assert position_realized_pnl_extractor(event) == Decimal("-15.75")
