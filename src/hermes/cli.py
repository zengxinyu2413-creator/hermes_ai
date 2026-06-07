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

import os
from decimal import Decimal

import click
from nautilus_trader.adapters.binance import BinanceExecClientConfig, BinanceLiveExecClientFactory
from nautilus_trader.adapters.binance.common.enums import BinanceAccountType, BinanceEnvironment
from nautilus_trader.adapters.binance.config import BinanceInstrumentProviderConfig
from nautilus_trader.adapters.binance.http.client import BinanceHttpClient
from nautilus_trader.adapters.binance.spot.providers import BinanceSpotInstrumentProvider
from nautilus_trader.common.component import LiveClock
from nautilus_trader.live.config import TradingNodeConfig
from nautilus_trader.live.node import TradingNode
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue

from hermes.execution.nt_translate import nt_instrument_to_limits_from_info
from hermes.execution.oneshot_strategy import OneShotConfig, OneShotStrategy
from hermes.execution.precision import build_order_spec

_TESTNET_BASE = "https://testnet.binance.vision"


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
                instrument_provider=BinanceInstrumentProviderConfig(
                    load_ids=frozenset({InstrumentId.from_str(f"{symbol.upper()}.BINANCE")})
                ),
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

    node = TradingNode(config=config)
    node.add_exec_client_factory("BINANCE", BinanceLiveExecClientFactory)
    node.build()

    if os.getenv("HERMES_SKIP_INJECT") != "1":
        # ---- 路径 C：注入现货 instrument 进 cache（== RiskEngine 读的 Cache）----
        _inj_clock = LiveClock()
        _inj_http = BinanceHttpClient(            # exchangeInfo 公开端点，无需凭据
            clock=_inj_clock, api_key=None, api_secret=None,
            base_url=_TESTNET_BASE,
        )
        _inj_provider = BinanceSpotInstrumentProvider(
            client=_inj_http, clock=_inj_clock, account_type=BinanceAccountType.SPOT,
        )
        _iid = InstrumentId(Symbol(symbol.upper()), Venue("BINANCE"))
        node.kernel.loop.run_until_complete(_inj_provider.load_ids_async([_iid]))
        _instrument = _inj_provider.find(_iid)
        assert _instrument is not None, f"path-C: provider 未取到 {_iid}"
        node.kernel.cache.add_instrument(_instrument)
        assert node.kernel.cache.instrument(_iid) is not None, f"path-C: cache 回读 {_iid} 空"
        # ---- 路径 C 结束 ----

        limits = nt_instrument_to_limits_from_info(_instrument)

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

        strategy_config = OneShotConfig(
            instrument_id_str=f"{symbol.upper()}.BINANCE",
            order_side_str=side.upper(),
            price_str=str(order_spec.price),
            quantity_str=str(order_spec.quantity),
        )
        strategy = OneShotStrategy(config=strategy_config, on_done=on_done)

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
    else:
        click.echo(
            "HERMES_SKIP_INJECT=1: instrument 未注入 cache, 跳过下单"
            "(诊断模式: instrument 未注入, 不构造订单/策略, 不下单)",
            err=True,
        )
        return
