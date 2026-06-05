"""Translate a NautilusTrader Instrument into InstrumentLimits.

Implements PREC translation layer (a): NT Instrument → InstrumentLimits.
precision.py is not modified; this module is the bridge layer only.
"""

from __future__ import annotations

from decimal import Decimal

from hermes.execution.precision import InstrumentLimits


def nt_instrument_to_limits(
    instrument,
    *,
    bid_multiplier_up: Decimal,
    bid_multiplier_down: Decimal,
    ask_multiplier_up: Decimal,
    ask_multiplier_down: Decimal,
    apply_min_to_market: bool,
) -> InstrumentLimits:
    """Translate a NautilusTrader Instrument into InstrumentLimits.

    Seven fields are read directly from the NT Instrument object:
        price_increment → price_tick
        size_increment  → qty_step
        min_quantity    → qty_min   (None → Decimal("0"), meaning no minimum enforced)
        max_quantity    → qty_max   (None → raises ValueError; no safe default exists)
        min_price       → price_min (None → Decimal("0"), meaning no lower bound)
        max_price       → price_max (None → Decimal("0"), meaning no upper bound)
        min_notional    → min_notional via Money.as_decimal() (None → Decimal("0"))

    Five fields are NOT stored on NT Instrument and must be supplied by the caller:

        bid_multiplier_up / bid_multiplier_down / ask_multiplier_up / ask_multiplier_down:
            Source: raw BinanceSymbolFilter with filterType == "PERCENT_PRICE_BY_SIDE",
            fields bidMultiplierUp / bidMultiplierDown / askMultiplierUp / askMultiplierDown.
            NT's spot/providers.py does not read these into CurrencyPair; they are present
            only on the deserialized BinanceSymbolFilter schema object from exchangeInfo.

        apply_min_to_market:
            Source: raw BinanceSymbolFilter with filterType == "MIN_NOTIONAL",
            field applyMinToMarket (bool | None). NT's spot/providers.py reads minNotional
            but not this flag; the caller must extract it from the raw filter dict.

    All price/qty conversions use Decimal(str(...)) — never Decimal(float(...)) —
    to avoid IEEE-754 representation drift.

    Raises:
        ValueError: if instrument.max_quantity is None (no safe default for qty_max).
    """
    price_tick = Decimal(str(instrument.price_increment))
    qty_step = Decimal(str(instrument.size_increment))

    if instrument.min_quantity is None:
        qty_min = Decimal("0")
    else:
        qty_min = Decimal(str(instrument.min_quantity))

    if instrument.max_quantity is None:
        raise ValueError(
            "instrument.max_quantity is None; cannot build InstrumentLimits "
            "without qty_max — no safe default exists for this field."
        )
    qty_max = Decimal(str(instrument.max_quantity))

    price_min = Decimal(str(instrument.min_price)) if instrument.min_price is not None else Decimal("0")
    price_max = Decimal(str(instrument.max_price)) if instrument.max_price is not None else Decimal("0")

    if instrument.min_notional is None:
        min_notional = Decimal("0")
    else:
        min_notional = instrument.min_notional.as_decimal()

    return InstrumentLimits(
        price_tick=price_tick,
        price_min=price_min,
        price_max=price_max,
        qty_step=qty_step,
        qty_min=qty_min,
        qty_max=qty_max,
        min_notional=min_notional,
        apply_min_to_market=apply_min_to_market,
        bid_multiplier_up=bid_multiplier_up,
        bid_multiplier_down=bid_multiplier_down,
        ask_multiplier_up=ask_multiplier_up,
        ask_multiplier_down=ask_multiplier_down,
    )


_PPBS = "PERCENT_PRICE_BY_SIDE"
_NOTIONAL = "NOTIONAL"
_MN = "MIN_NOTIONAL"


def nt_instrument_to_limits_from_info(instrument) -> InstrumentLimits:
    """Extract 5 non-NT fields from instrument.info["filters"] and build InstrumentLimits.

    This is a convenience wrapper around nt_instrument_to_limits that reads the 5
    caller-supplied fields directly from the NT Instrument's .info dict, which is
    populated by Binance spot providers via _symbol_info_to_dict (recursive msgspec
    serialisation of BinanceSpotSymbolInfo including all BinanceSymbolFilter entries).

    Sources:
        instrument.info["filters"] — list[dict], filterType already converted to str
        filterType "PERCENT_PRICE_BY_SIDE" → bidMultiplierUp/Down, askMultiplierUp/Down
            (stored as str in the filter dict; converted to Decimal via Decimal(str_value))
        filterType "NOTIONAL" → applyMinToMarket (bool; None treated as False) [preferred]
        filterType "MIN_NOTIONAL" → applyToMarket (bool; None treated as False) [fallback]

    Raises:
        ValueError: if PERCENT_PRICE_BY_SIDE filter absent from filters list.
        ValueError: if neither NOTIONAL nor MIN_NOTIONAL filter found in filters list.
        ValueError: if any of the four multiplier fields is None in the PPBS filter.
    """
    filters: list[dict] = instrument.info["filters"]

    ppbs_list = [f for f in filters if f["filterType"] == _PPBS]
    if not ppbs_list:
        raise ValueError(
            f"filterType '{_PPBS}' not found in instrument.info['filters']; "
            "cannot extract bid/ask multipliers"
        )
    ppbs = ppbs_list[0]

    for key in ("bidMultiplierUp", "bidMultiplierDown", "askMultiplierUp", "askMultiplierDown"):
        if ppbs.get(key) is None:
            raise ValueError(
                f"PERCENT_PRICE_BY_SIDE filter field '{key}' is None; "
                "cannot build InstrumentLimits without a complete bid/ask multiplier set"
            )

    bid_multiplier_up   = Decimal(ppbs["bidMultiplierUp"])
    bid_multiplier_down = Decimal(ppbs["bidMultiplierDown"])
    ask_multiplier_up   = Decimal(ppbs["askMultiplierUp"])
    ask_multiplier_down = Decimal(ppbs["askMultiplierDown"])

    notional_list = [f for f in filters if f["filterType"] == _NOTIONAL]
    mn_list = [f for f in filters if f["filterType"] == _MN]

    if notional_list:
        raw_apply = notional_list[0].get("applyMinToMarket")
    elif mn_list:
        raw_apply = mn_list[0].get("applyToMarket")
    else:
        raise ValueError(
            f"Neither '{_NOTIONAL}' nor '{_MN}' filter found in instrument.info['filters']; "
            "cannot extract apply_min_to_market"
        )
    apply_min_to_market: bool = False if raw_apply is None else bool(raw_apply)

    return nt_instrument_to_limits(
        instrument,
        bid_multiplier_up=bid_multiplier_up,
        bid_multiplier_down=bid_multiplier_down,
        ask_multiplier_up=ask_multiplier_up,
        ask_multiplier_down=ask_multiplier_down,
        apply_min_to_market=apply_min_to_market,
    )
