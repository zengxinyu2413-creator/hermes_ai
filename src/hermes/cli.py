"""Hermes AI CLI entry point.

Entry point registered in pyproject.toml:
    hermes = "hermes.cli:main"

Subcommands
-----------
trade-live  Launch the live/testnet order-submission node (NT Binance adapter, b3b).

Architecture note (X-path, b3b)
--------------------------------
The self-built execution chain (new_order / nt_order_translate / BinanceLiveExecClient
from b3a / 3b10272) is dormant on the live path: NT's built-in BinanceLiveExecClientFactory
is used directly, bypassing those modules.  The self-built modules are kept and their tests
continue to run; they are not deleted.
"""
from __future__ import annotations

import asyncio
import contextlib
from decimal import Decimal
from typing import Any

import click
import httpx
from nautilus_trader.adapters.binance import BinanceExecClientConfig, BinanceLiveExecClientFactory
from nautilus_trader.adapters.binance.common.enums import BinanceAccountType, BinanceEnvironment
from nautilus_trader.live.config import TradingNodeConfig
from nautilus_trader.live.node import TradingNode

from hermes.execution.oneshot_strategy import OneShotConfig, OneShotStrategy
from hermes.execution.precision import InstrumentLimits, build_order_spec

_TESTNET_BASE = "https://testnet.binance.vision"


def _parse_instrument_limits(filters: list[dict[str, Any]]) -> InstrumentLimits:
    """Build InstrumentLimits from a Binance exchangeInfo filters list."""
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


@click.group()
def main() -> None:
    """Hermes AI trading system."""


@main.command("trade-live")
@click.option("--dry", is_flag=True, help="Validate config and print summary; no connection.")
@click.option("--symbol", default="ETHUSDT", show_default=True, help="Trading pair symbol.")
@click.option(
    "--side",
    type=click.Choice(["BUY", "SELL"], case_sensitive=False),
    default="BUY",
    show_default=True,
    help="Order side.",
)
@click.option("--price", "price_str", default=None, help="Limit price (required for live run).")
@click.option("--qty", "qty_str", default=None, help="Order quantity (required for live run).")
def trade_live(
    dry: bool,
    symbol: str,
    side: str,
    price_str: str | None,
    qty_str: str | None,
) -> None:
    """Launch the live/testnet order-submission node.

    Uses NT's built-in Binance adapter (X-path, b3b).  Credentials are read at
    runtime from BINANCE_TESTNET_API_KEY / BINANCE_TESTNET_API_SECRET (not stored
    in config).  --dry exits before TradingNode is constructed; no network connection.
    """
    config = TradingNodeConfig(
        trader_id="TRADER-001",
        exec_clients={
            "BINANCE": BinanceExecClientConfig(
                environment=BinanceEnvironment.TESTNET,  # critical: omitting → LIVE (mainnet)
                account_type=BinanceAccountType.SPOT,
                max_retries=0,  # zero retries on order submission
                # api_key / api_secret left None: NT reads BINANCE_TESTNET_API_KEY/SECRET
            )
        },
    )

    exec_cfg = config.exec_clients["BINANCE"]
    # Safety: reject any non-TESTNET config unconditionally.
    if exec_cfg.environment != BinanceEnvironment.TESTNET:
        raise click.ClickException("ABORT: non-TESTNET environment is forbidden")

    if dry:
        click.echo(
            f"dry-run: config validated — "
            f"env={exec_cfg.environment.value} "
            f"account={exec_cfg.account_type.value} "
            f"max_retries={exec_cfg.max_retries}, no connection"
        )
        return

    if price_str is None or qty_str is None:
        raise click.UsageError("--price and --qty are required for live run")

    # --- fetch exchange constraints (testnet, read-only) ---
    resp = httpx.get(
        f"{_TESTNET_BASE}/api/v3/exchangeInfo",
        params={"symbol": symbol.upper()},
        timeout=10.0,
    )
    resp.raise_for_status()
    sym_info = next(
        s for s in resp.json()["symbols"] if s["symbol"] == symbol.upper()
    )
    limits = _parse_instrument_limits(sym_info["filters"])

    # --- precision round + validate (raises OrderRejected on filter violation) ---
    order_spec = build_order_spec(
        symbol=symbol.upper(),
        side=side.upper(),
        order_type="LIMIT",
        raw_price=Decimal(price_str),
        raw_qty=Decimal(qty_str),
        limits=limits,
        avg_price=None,
    )

    # J2 pre-submit five-field verification
    click.echo(
        f"J2 pre-submit: symbol={order_spec.symbol} side={order_spec.side} "
        f"type={order_spec.order_type} price={order_spec.price} qty={order_spec.quantity}"
    )

    # --- wire strategy ---
    result: dict[str, str | None] = {}

    def on_done(venue_order_id: str | None, reason: str | None) -> None:
        result["venue_order_id"] = venue_order_id
        result["reason"] = reason
        with contextlib.suppress(RuntimeError):
            asyncio.get_running_loop().stop()

    strategy_config = OneShotConfig(
        instrument_id_str=f"{symbol.upper()}.BINANCE",
        order_side_str=side.upper(),
        price_str=str(order_spec.price),
        quantity_str=str(order_spec.quantity),
    )
    strategy = OneShotStrategy(config=strategy_config, on_done=on_done)

    node = TradingNode(config=config)
    node.add_exec_client_factory("BINANCE", BinanceLiveExecClientFactory)
    node.build()
    node.trader.add_strategy(strategy)
    node.run()

    # --- report result ---
    if result.get("venue_order_id"):
        click.echo(
            f"ORDER ACCEPTED  orderId={result['venue_order_id']}"
            f"  price={order_spec.price}  qty={order_spec.quantity}"
        )
    elif result.get("reason"):
        click.echo(f"ORDER REJECTED  reason={result['reason']}", err=True)
        raise SystemExit(1)
    else:
        click.echo("Order result unknown — no response received", err=True)
        raise SystemExit(2)
