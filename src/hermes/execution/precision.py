"""Order precision: tick/step rounding, filter checks, order spec construction.

All arithmetic uses Decimal throughout. No float allowed on price/qty paths.
InstrumentLimits is provided by the caller — this module does no network I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal, InvalidOperation


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class OrderRejected(Exception):
    """Raised when an order fails a filter check (size, notional, price band)."""


# ---------------------------------------------------------------------------
# Data contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InstrumentLimits:
    """Exchange filter limits for a single instrument.

    All price/qty fields are Decimal strings converted at construction time
    by the caller. The percent-price multipliers apply to LIMIT orders only;
    market orders skip that check.

    Fields:
        price_tick:         minimum price increment
        price_min:          LOT_SIZE-style min price (0 = not enforced)
        price_max:          max price (0 = not enforced)
        qty_step:           minimum qty increment (LOT_SIZE filter)
        qty_min:            minimum order quantity
        qty_max:            maximum order quantity
        min_notional:       minimum notional value (price * qty after floor)
        apply_min_to_market: whether MIN_NOTIONAL applies to MARKET orders
        bid_multiplier_up:   PERCENT_PRICE_BY_SIDE upper multiplier for BUY
        bid_multiplier_down: PERCENT_PRICE_BY_SIDE lower multiplier for BUY
        ask_multiplier_up:   PERCENT_PRICE_BY_SIDE upper multiplier for SELL
        ask_multiplier_down: PERCENT_PRICE_BY_SIDE lower multiplier for SELL
    """

    price_tick: Decimal
    price_min: Decimal
    price_max: Decimal
    qty_step: Decimal
    qty_min: Decimal
    qty_max: Decimal
    min_notional: Decimal
    apply_min_to_market: bool
    # PERCENT_PRICE_BY_SIDE multipliers
    bid_multiplier_up: Decimal
    bid_multiplier_down: Decimal
    ask_multiplier_up: Decimal
    ask_multiplier_down: Decimal


@dataclass(frozen=True, slots=True)
class OrderSpec:
    """Validated, floor-rounded order ready for submission."""

    symbol: str
    side: str          # "BUY" | "SELL"
    order_type: str    # "LIMIT" | "MARKET"
    price: Decimal     # 0 for MARKET orders
    quantity: Decimal


# ---------------------------------------------------------------------------
# Low-level rounding helpers
# ---------------------------------------------------------------------------


def _tick_precision(tick: Decimal) -> int:
    """Return the number of decimal places implied by *tick*."""
    t = tick.as_tuple()
    exp = t.exponent
    if not isinstance(exp, int):
        raise ValueError(f"Cannot determine precision of special Decimal: {tick!r}")
    return max(0, -exp)


def floor_to_tick(value: Decimal, tick: Decimal) -> Decimal:
    """Floor *value* to the nearest multiple of *tick* (no rounding up).

    >>> floor_to_tick(Decimal("123.456"), Decimal("0.01"))
    Decimal('123.45')
    """
    if tick <= Decimal(0):
        raise ValueError(f"tick must be positive, got {tick!r}")
    places = _tick_precision(tick)
    quantizer = Decimal(10) ** -places
    # Divide → floor via ROUND_DOWN → multiply back
    floored = (value / tick).to_integral_value(rounding=ROUND_DOWN) * tick
    return floored.quantize(quantizer)


def floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    """Alias for floor_to_tick for quantity steps — same semantics."""
    return floor_to_tick(value, step)


def round_price(price: Decimal, limits: InstrumentLimits) -> Decimal:
    """Floor *price* to the instrument's price tick."""
    return floor_to_tick(price, limits.price_tick)


def round_quantity(qty: Decimal, limits: InstrumentLimits) -> Decimal:
    """Floor *qty* to the instrument's qty step."""
    return floor_to_step(qty, limits.qty_step)


# ---------------------------------------------------------------------------
# Filter checks
# ---------------------------------------------------------------------------


def check_notional(
    price: Decimal,
    qty: Decimal,
    limits: InstrumentLimits,
    *,
    is_market: bool = False,
) -> None:
    """Raise OrderRejected if notional < min_notional after flooring.

    For MARKET orders respects apply_min_to_market flag.
    """
    if is_market and not limits.apply_min_to_market:
        return
    notional = price * qty
    if notional < limits.min_notional:
        raise OrderRejected(
            f"notional {notional} < min_notional {limits.min_notional} "
            f"(price={price}, qty={qty})"
        )


def check_percent_price(
    price: Decimal,
    side: str,
    limits: InstrumentLimits,
    avg_price: Decimal | None,
) -> None:
    """Raise OrderRejected if *price* violates PERCENT_PRICE_BY_SIDE.

    Skipped when avg_price is None (caller signals: no 5-min average available).
    MARKET orders should not call this function.
    """
    if avg_price is None:
        return
    side_upper = side.upper()
    if side_upper == "BUY":
        lower = avg_price * limits.bid_multiplier_down
        upper = avg_price * limits.bid_multiplier_up
    elif side_upper == "SELL":
        lower = avg_price * limits.ask_multiplier_down
        upper = avg_price * limits.ask_multiplier_up
    else:
        raise ValueError(f"Unknown side: {side!r}")

    if price < lower or price > upper:
        raise OrderRejected(
            f"price {price} outside PERCENT_PRICE band [{lower}, {upper}] "
            f"for side={side_upper} avg_price={avg_price}"
        )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def build_order_spec(
    symbol: str,
    side: str,
    order_type: str,
    raw_price: Decimal,
    raw_qty: Decimal,
    limits: InstrumentLimits,
    *,
    avg_price: Decimal | None = None,
) -> OrderSpec:
    """Validate and floor-round an order, returning a ready-to-submit OrderSpec.

    Steps (in order):
    1. Floor qty to step, then check qty_min / qty_max.
    2. Floor price to tick (LIMIT only), check price_min / price_max if set.
    3. PERCENT_PRICE_BY_SIDE check (LIMIT only, skipped if avg_price is None).
    4. MIN_NOTIONAL check.

    Raises OrderRejected on any filter violation.
    Raises ValueError on bad limits (zero tick/step).
    """
    is_market = order_type.upper() == "MARKET"

    # --- qty ---
    qty = round_quantity(raw_qty, limits)
    if qty < limits.qty_min:
        raise OrderRejected(
            f"qty {qty} (floored from {raw_qty}) < qty_min {limits.qty_min}"
        )
    if qty > limits.qty_max:
        raise OrderRejected(
            f"qty {qty} (floored from {raw_qty}) > qty_max {limits.qty_max}"
        )

    # --- price ---
    if is_market:
        price = Decimal(0)
    else:
        price = round_price(raw_price, limits)
        if limits.price_min > Decimal(0) and price < limits.price_min:
            raise OrderRejected(
                f"price {price} < price_min {limits.price_min}"
            )
        if limits.price_max > Decimal(0) and price > limits.price_max:
            raise OrderRejected(
                f"price {price} > price_max {limits.price_max}"
            )
        check_percent_price(price, side, limits, avg_price)

    # --- notional ---
    notional_price = raw_price if is_market else price
    check_notional(notional_price, qty, limits, is_market=is_market)

    return OrderSpec(
        symbol=symbol,
        side=side.upper(),
        order_type=order_type.upper(),
        price=price,
        quantity=qty,
    )
