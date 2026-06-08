"""RestReader — thin read-only wrapper over BinanceRestClient.

Only the ALLOW whitelist is called: {get_klines, server_time_ms, ping}.
No new_order, no _request direct calls, no signed endpoints.
"""
from __future__ import annotations

from hermes.exchanges.binance_contracts import Kline, KlineInterval
from hermes.exchanges.binance_rest import BinanceRestClient


class RestReader:
    """Read-only facade over BinanceRestClient for the monitoring bot."""

    def __init__(self, client: BinanceRestClient, symbol: str = "SOLUSDT") -> None:
        self._client = client
        self._symbol = symbol

    async def read_ping(self) -> bool:
        """Return True if Binance REST responds, False on any exception."""
        try:
            await self._client.ping()
            return True
        except Exception:
            return False

    async def read_server_time(self) -> int | None:
        """Return Binance server time in ms, or None on failure."""
        try:
            return await self._client.server_time_ms()
        except Exception:
            return None

    async def read_klines(self, limit: int = 2) -> list[Kline]:
        """Return recent 1h klines for the configured symbol, or [] on failure."""
        try:
            return await self._client.get_klines(
                symbol=self._symbol,
                interval=KlineInterval.HOUR_1,
                limit=limit,
            )
        except Exception:
            return []
