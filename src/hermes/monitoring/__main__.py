"""Entry point: python -m hermes.monitoring  OR  hermes-monitor.

Requires [monitor] optional dep:  pip install -e '.[monitor]'
Requires .env:  HERMES_TELEGRAM_BOT_TOKEN  HERMES_TELEGRAM_CHAT_ID

SIGINT / SIGTERM → graceful stop (no traceback).
"""
from __future__ import annotations

import asyncio
import contextlib
import signal
import sys
from typing import Any

from hermes.exchanges.binance_credentials import BinanceEnvironment


def main() -> None:
    try:
        from telegram.ext import Application, CommandHandler
    except ImportError:
        print(
            "python-telegram-bot not installed. "
            "Run: pip install -e '.[monitor]'",
            file=sys.stderr,
        )
        sys.exit(1)

    from hermes.exchanges.binance_rest import BinanceRestClient
    from hermes.monitoring.alerter import Alerter
    from hermes.monitoring.config import TelegramConfig
    from hermes.monitoring.rest_reader import RestReader

    config = TelegramConfig()  # type: ignore[call-arg]

    async def _run() -> None:
        app: Any = (
            Application.builder()
            .token(config.bot_token.get_secret_value())
            .build()
        )

        # Public endpoints (ping/time/klines) do not use credentials;
        # BinanceRestClient requires non-empty strings, so we pass "public".
        async with BinanceRestClient(
            api_key="public",
            api_secret="public",
            env=BinanceEnvironment.TESTNET,
        ) as client:
            reader = RestReader(client=client, symbol=config.symbol)

            async def send_fn(msg: str) -> None:
                await app.bot.send_message(chat_id=config.chat_id, text=msg)

            alerter = Alerter(
                reader=reader,
                send_fn=send_fn,
                poll_interval_s=config.poll_interval_s,
                clock_drift_warn_ms=config.clock_drift_warn_ms,
                price_move_warn_pct=config.price_move_warn_pct,
            )

            async def cmd_status(update: Any, context: Any) -> None:
                await update.message.reply_text(alerter.get_status())

            async def cmd_price(update: Any, context: Any) -> None:
                snap = alerter.last_snapshot
                text = (
                    f"{snap.latest_price:.2f}"
                    if snap and snap.latest_price is not None
                    else "N/A"
                )
                await update.message.reply_text(text)

            async def cmd_ping(update: Any, context: Any) -> None:
                ok = await reader.read_ping()
                await update.message.reply_text("✅ ok" if ok else "\U0001f534 fail")

            app.add_handler(CommandHandler("status", cmd_status))
            app.add_handler(CommandHandler("price", cmd_price))
            app.add_handler(CommandHandler("ping", cmd_ping))

            loop = asyncio.get_running_loop()
            loop.add_signal_handler(signal.SIGTERM, alerter.stop)
            loop.add_signal_handler(signal.SIGINT, alerter.stop)

            async with app:
                await app.start()
                await app.updater.start_polling()
                await alerter.run()
                await app.updater.stop()
                await app.stop()

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_run())


if __name__ == "__main__":
    main()
