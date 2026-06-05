"""Compute the far-limit buy price for post-only orders.

Authority: stopb_cb0_production_path.py / stopb_phase1_cancel.py.
This module is the single canonical implementation; experiments/ copies are deprecated.

Algorithm (production path):
    ppbs_lower = avg_price * bid_multiplier_down          # PPBS lower bound
    raw_far    = ppbs_lower * (1 + safety_margin)         # nudge up off the PPBS floor (anti-rejection margin)
    far_limit  = floor_to_tick(raw_far, tick)             # align to exchange tick
"""

from __future__ import annotations

from decimal import Decimal

from hermes.execution.precision import floor_to_tick


def compute_far_limit_buy(
    avg: Decimal,
    bid_multiplier_down: Decimal,
    tick: Decimal,
    safety_margin: Decimal = Decimal("0.001"),
) -> Decimal:
    """Return the far-limit buy price floored to tick.

    Args:
        avg: Reference price (e.g. 5-min VWAP or last traded price).
        bid_multiplier_down: PPBS bidMultiplierDown from exchangeInfo filters.
        tick: Price tick size (price_increment) for the symbol.
        safety_margin: Fractional nudge above the PPBS floor to avoid rejection (default 0.1%).

    Returns:
        Far-limit price as Decimal, floored to the nearest tick below raw_far.

    Raises:
        ValueError: if avg <= 0 or bid_multiplier_down <= 0 (far-limit is meaningless).
        ValueError: if tick <= 0 (propagated from floor_to_tick).
    """
    if avg <= Decimal(0):
        raise ValueError(f"avg must be positive, got {avg!r}")
    if bid_multiplier_down <= Decimal(0):
        raise ValueError(f"bid_multiplier_down must be positive, got {bid_multiplier_down!r}")

    ppbs_lower = avg * bid_multiplier_down
    raw_far = ppbs_lower * (Decimal("1") + safety_margin)
    return floor_to_tick(raw_far, tick)
