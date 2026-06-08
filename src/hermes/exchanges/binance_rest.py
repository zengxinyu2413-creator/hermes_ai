"""Binance Spot REST client for Hermes AI v6.

This file is the entry point for all Binance HTTP API calls. It owns:
    * httpx.AsyncClient (one per BinanceRestClient instance)
    * base URL selection (testnet vs mainnet)
    * authenticated signing (delegated to _signing.sign)

What lives here vs elsewhere:
    * Signing → _signing.py (pure HMAC, no I/O)
    * Credentials → binance_credentials.py (env var loading)
    * Errors → core/exceptions.py (BinanceAPIError, RateLimitError, ...)
    * This file: HTTP transport, URL construction, lifecycle, endpoint methods

Lifecycle:
    async with BinanceRestClient(api_key, api_secret, env="testnet") as client:
        await client.ping()
    # client is closed automatically here.

We deliberately offer ONLY the async API. Mixing sync and async is a recipe
for deadlocks in an event-loop-driven trading system, and NautilusTrader is
async-native anyway.

Endpoints are added incrementally in subsequent commits. This file currently
only contains the lifecycle scaffolding — no HTTP requests yet.
"""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

import httpx

from hermes.core.exceptions import (
    BinanceAPIError,
    ConfigurationError,
    RateLimitError,
)
from hermes.exchanges._signing import sign
from hermes.exchanges.binance_contracts import Kline, KlineInterval
from hermes.exchanges.binance_credentials import BinanceEnvironment

if TYPE_CHECKING:
    from types import TracebackType


# --- Endpoint base URLs -------------------------------------------------------
# Mainnet vs testnet differ only in hostname. Spot only for now; futures will
# add fapi.binance.com / testnet.binancefuture.com when we need them.
#
# Sources:
#   https://binance-docs.github.io/apidocs/spot/en/#general-info
#   https://testnet.binance.vision/   (testnet UI, lists the API host)

_SPOT_BASE_URLS: dict[BinanceEnvironment, str] = {
    BinanceEnvironment.MAINNET: "https://api.binance.com",
    BinanceEnvironment.TESTNET: "https://testnet.binance.vision",
    # DEMO uses the same testnet host. We keep the distinction at the
    # credentials layer so operators can tell which key set is active.
    BinanceEnvironment.DEMO: "https://testnet.binance.vision",
}

# Default request timeout, in seconds. Binance's docs recommend 5s for spot
# market data and 10s for order operations; we go with 10s globally and let
# individual call sites override if needed.
DEFAULT_TIMEOUT_S = 10.0

# Default recv window for signed requests, in milliseconds. Binance rejects
# signed requests whose timestamp is older than this. 5000 is the safe default
# from the docs; tighter (e.g. 2000) reduces replay risk but increases false
# rejections on slow networks.
DEFAULT_RECV_WINDOW_MS = 5_000


class BinanceRestClient:
    """Async HTTP client for the Binance Spot REST API.

    This skeleton only handles lifecycle and URL construction. Endpoint methods
    (ping, server_time, klines, account, new_order, ...) are added in the
    following commits.

    Args:
        api_key: Plain-text API key. Caller is responsible for pulling this out
            of SecretStr via .get_secret_value().
        api_secret: Plain-text API secret. Same as above.
        env: Binance environment selector. Defaults to TESTNET to make
            accidental misuse harmless.
        timeout_s: Per-request timeout in seconds.
        recv_window_ms: recvWindow value used on signed requests. Must be
            <= 60000 (Binance hard limit).

    Raises:
        ConfigurationError: If credentials are empty or recv_window_ms is out
            of range.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        env: BinanceEnvironment = BinanceEnvironment.TESTNET,
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        recv_window_ms: int = DEFAULT_RECV_WINDOW_MS,
    ) -> None:
        # --- Validate credentials -------------------------------------------
        if not isinstance(api_key, str) or not api_key:
            raise ConfigurationError("api_key must be a non-empty string")
        if not isinstance(api_secret, str) or not api_secret:
            raise ConfigurationError("api_secret must be a non-empty string")

        # --- Validate env ----------------------------------------------------
        if not isinstance(env, BinanceEnvironment):
            raise ConfigurationError(
                f"env must be a BinanceEnvironment, got {type(env).__name__}"
            )

        # --- Validate recv_window_ms ----------------------------------------
        if not (0 < recv_window_ms <= 60_000):
            raise ConfigurationError(
                f"recv_window_ms must be in (0, 60000], got {recv_window_ms}"
            )

        # --- Validate timeout -----------------------------------------------
        if timeout_s <= 0:
            raise ConfigurationError(
                f"timeout_s must be positive, got {timeout_s}"
            )

        # --- Store --------------------------------------------------------
        self._api_key = api_key
        self._api_secret = api_secret
        self._env = env
        self._timeout_s = timeout_s
        self._recv_window_ms = recv_window_ms

        # The actual httpx client is created lazily in __aenter__ / connect().
        # Reason: instantiating BinanceRestClient should be cheap and side-
        # effect-free so tests can construct one without an event loop.
        self._client: httpx.AsyncClient | None = None

    # --- Public read-only properties ----------------------------------------

    @property
    def env(self) -> BinanceEnvironment:
        return self._env

    @property
    def base_url(self) -> str:
        return _SPOT_BASE_URLS[self._env]

    @property
    def timeout_s(self) -> float:
        return self._timeout_s

    @property
    def recv_window_ms(self) -> int:
        return self._recv_window_ms

    @property
    def is_connected(self) -> bool:
        return self._client is not None

    # --- URL helpers --------------------------------------------------------

    def _make_url(self, path: str) -> str:
        """Compose a full URL from a path like '/api/v3/ping'.

        Accepts both '/api/v3/ping' and 'api/v3/ping' for caller convenience.
        """
        if not path:
            raise ValueError("path must be non-empty")
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url}{path}"

    # --- Lifecycle ----------------------------------------------------------

    async def connect(self) -> None:
        """Create the underlying httpx.AsyncClient. Idempotent."""
        if self._client is not None:
            return
        self._client = httpx.AsyncClient(
            timeout=self._timeout_s,
            headers={"X-MBX-APIKEY": self._api_key},
        )

    async def aclose(self) -> None:
        """Close the underlying httpx.AsyncClient. Idempotent."""
        if self._client is None:
            return
        await self._client.aclose()
        self._client = None

    async def __aenter__(self) -> "BinanceRestClient":
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: "TracebackType | None",
    ) -> None:
        await self.aclose()
    # --- Public endpoints ---------------------------------------------------
    async def get_klines(
        self,
        symbol: str,
        interval: KlineInterval,
        *,
        limit: int = 500,
    ) -> list[Kline]:
        """Fetch recent kline (candlestick) bars for a symbol.

        Endpoint: GET /api/v3/klines (public, no auth, weight 2 for limit<=500)

        Args:
            symbol: Trading pair, e.g. "SOLUSDT". Upper-cased automatically.
            interval: Kline interval enum.
            limit: Number of bars to return. Binance caps this at 1000.

        Returns:
            List of Kline objects, oldest first. Returns an empty list if
            Binance has no data for the symbol/interval (rare, but possible
            for new listings).

        Raises:
            ValueError: If limit is out of range.
            BinanceAPIError: If Binance rejects the request (e.g. invalid
                symbol, code -1121).
        """
        if not 1 <= limit <= 1000:
            raise ValueError(f"limit must be in [1, 1000], got {limit}")

        params = {
            "symbol": symbol.upper(),
            "interval": interval.value,
            "limit": limit,
        }
        rows = await self._request("GET", "/api/v3/klines", params=params)

        if not isinstance(rows, list):
            # Binance always returns a list here. If we got something else,
            # the response shape changed — surface loudly rather than silently
            # returning [].
            from hermes.core.exceptions import BinanceAPIError
            raise BinanceAPIError(
                code=-1,
                message=f"expected list from /api/v3/klines, got {type(rows).__name__}",
                http_status=200,
            )

        return [
            Kline.from_binance_row(row, symbol=symbol.upper(), interval=interval)
            for row in rows
        ]
    async def server_time_ms(self) -> int:
        """Return Binance's current server time as Unix milliseconds.

        Endpoint: GET /api/v3/time (public, no auth, weight 1)

        Used as the source of truth for the `timestamp` param on signed
        requests. We could just use local time(), but if the local clock
        drifts by more than `recv_window_ms` Binance will reject every
        signed call with -1021 "Timestamp for this request is outside of
        the recvWindow."
        """
        body = await self._request("GET", "/api/v3/time")
        return int(body["serverTime"])

    async def time_offset_ms(self) -> int:
        """Measure (server_time - local_time) in milliseconds.

        Positive value = local clock is BEHIND Binance.
        Negative value = local clock is AHEAD of Binance.

        Sampled once. The result includes round-trip latency, so it's an
        upper-bound estimate of the actual offset. For a tighter measurement
        we'd do an NTP-style 4-timestamp dance, but a single sample is
        sufficient for the use case here (alerting if the host clock is
        clearly broken).
        """
        local_before = self._now_ms()
        server = await self.server_time_ms()
        local_after = self._now_ms()
        local_midpoint = (local_before + local_after) // 2
        return server - local_midpoint
    async def ping(self) -> dict:
        """Test connectivity to Binance. Returns an empty dict on success.

        This is the canonical first call to validate that base URL, TLS,
        connection pool, and the _request pipeline all work end-to-end.
        Binance returns `{}` and we pass it through unchanged.

        Endpoint: GET /api/v3/ping (public, no auth, weight 1)
        """
        return await self._request("GET", "/api/v3/ping")

    # DORMANT (E2.5-b3b 起): 此方法 (new_order) 属自建链 a 环. binance_rest.py 本身是 live REST 路径非 dormant, 仅此方法随自建链挂起. 见 handoff 6.3.
    async def new_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: Decimal,
        *,
        price: Decimal | None = None,
        time_in_force: str = "GTC",
        new_client_order_id: str | None = None,
    ) -> dict[str, Any]:
        """Place a new Spot order on Binance.

        Endpoint: POST /api/v3/order (signed, weight 1)

        Args:
            symbol: Trading pair, e.g. "SOLUSDT". Upper-cased automatically.
            side: "BUY" or "SELL".
            order_type: "MARKET" or "LIMIT".
            quantity: Order quantity. Must be a Decimal > 0 (float rejected).
            price: Limit price. Required for LIMIT; must be None for MARKET.
            time_in_force: "GTC", "IOC", or "FOK". LIMIT only.
            new_client_order_id: Optional caller-assigned order ID.

        Returns:
            Raw Binance order response dict (orderId, status, fills, ...).

        Raises:
            ValueError: Parameter invalid — checked before any network call.
            BinanceAPIError: Binance-side rejection (insufficient balance, etc.).
        """
        # --- Validate all inputs before touching the network -----------------
        if side not in {"BUY", "SELL"}:
            raise ValueError(f"side must be 'BUY' or 'SELL', got {side!r}")
        if order_type not in {"MARKET", "LIMIT"}:
            raise ValueError(f"order_type must be 'MARKET' or 'LIMIT', got {order_type!r}")
        if not isinstance(quantity, Decimal) or quantity <= 0:
            raise ValueError(f"quantity must be a positive Decimal, got {quantity!r}")
        if order_type == "LIMIT":
            if price is None or not isinstance(price, Decimal) or price <= 0:
                raise ValueError("LIMIT order requires a positive Decimal price")
            if time_in_force not in {"GTC", "IOC", "FOK"}:
                raise ValueError(
                    f"time_in_force must be 'GTC', 'IOC', or 'FOK', got {time_in_force!r}"
                )
        if order_type == "MARKET" and price is not None:
            raise ValueError("MARKET order must not include a price")

        # --- Build params ----------------------------------------------------
        # format(d, 'f') avoids scientific notation: Decimal("1E-8") -> "0.00000001"
        # str() gives "1E-8" which Binance rejects; normalize() gives "1E+2" for 100.
        params: dict[str, str | int] = {
            "symbol": symbol.upper(),
            "side": side,
            "type": order_type,
            "quantity": format(quantity, "f"),
        }
        if order_type == "LIMIT":
            assert price is not None  # narrowing — validated above
            params["price"] = format(price, "f")
            params["timeInForce"] = time_in_force
        if new_client_order_id is not None:
            params["newClientOrderId"] = new_client_order_id

        # max_retries=0: order submission must never auto-retry (duplicate order risk).
        # timestamp / recvWindow / signature are injected by _request(signed=True).
        result = await self._request(
            "POST", "/api/v3/order", params=params, signed=True, max_retries=0
        )
        assert isinstance(result, dict)
        return result

    async def get_account(self) -> dict[str, Any]:
        """Fetch account information including balances and commission rates.

        Endpoint: GET /api/v3/account (signed, weight 10)

        Returns:
            Raw Binance account response dict (makerCommission, takerCommission,
            canTrade, balances, ...).

        Raises:
            BinanceAPIError: If Binance rejects the request (e.g. invalid API key).
        """
        result = await self._request("GET", "/api/v3/account", signed=True)
        assert isinstance(result, dict)
        return result

    async def get_open_orders(
        self,
        symbol: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch all open orders, optionally filtered by symbol.

        Endpoint: GET /api/v3/openOrders (signed, weight 3 with symbol, 40 without)

        Args:
            symbol: Trading pair filter, e.g. "SOLUSDT". If omitted, returns
                open orders for ALL symbols (higher API weight — use sparingly).

        Returns:
            List of raw Binance order dicts. Empty list if no open orders.

        Raises:
            BinanceAPIError: If Binance rejects the request.
        """
        params: dict[str, str] | None = None
        if symbol is not None:
            params = {"symbol": symbol.upper()}
        result = await self._request("GET", "/api/v3/openOrders", params=params, signed=True)
        assert isinstance(result, list)
        return result

    async def get_my_trades(
        self,
        symbol: str,
        *,
        limit: int | None = None,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        from_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch trade history for a symbol.

        Endpoint: GET /api/v3/myTrades (signed, weight 10)

        Args:
            symbol: Trading pair, e.g. "SOLUSDT". Required by Binance.
            limit: Max trades to return (1-1000). Binance default is 500.
            start_time_ms: Return trades at or after this Unix ms timestamp.
            end_time_ms: Return trades at or before this Unix ms timestamp.
            from_id: Return trades with tradeId >= fromId.

        Returns:
            List of raw Binance trade dicts. Empty list if no matching trades.

        Raises:
            ValueError: If symbol is empty or limit is out of range.
            BinanceAPIError: If Binance rejects the request.
        """
        if not symbol:
            raise ValueError("symbol is required for get_my_trades")
        params: dict[str, str | int] = {"symbol": symbol.upper()}
        if limit is not None:
            if not 1 <= limit <= 1000:
                raise ValueError(f"limit must be in [1, 1000], got {limit}")
            params["limit"] = limit
        if start_time_ms is not None:
            params["startTime"] = start_time_ms
        if end_time_ms is not None:
            params["endTime"] = end_time_ms
        if from_id is not None:
            params["fromId"] = from_id
        result = await self._request("GET", "/api/v3/myTrades", params=params, signed=True)
        assert isinstance(result, list)
        return result

    # --- HTTP request engine ------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        signed: bool = False,
        keyed: bool = False,
        max_retries: int = 2,
    ) -> dict | list:
        """Send a single HTTP request to Binance and parse the response.

        This is the only place in the codebase that talks to the network for
        REST calls. Endpoint methods (ping, klines, account, ...) build their
        params, call _request, and translate the result into typed objects.

        Args:
            method: 'GET', 'POST', 'PUT', or 'DELETE'.
            path: API path starting with '/' (e.g. '/api/v3/ping').
            params: Query parameters as a dict. Will be URL-encoded.
            signed: If True, add timestamp/recvWindow and HMAC-SHA256 signature.
                Implies keyed=True (signed requests always need the API key
                header too).
            keyed: If True, send the X-MBX-APIKEY header. httpx already has
                this header on every request via the client default, so this
                flag is documentary right now — it becomes important once we
                add public clients that strip the header.
            max_retries: Number of additional attempts on network-level errors.
                Business errors (auth, validation, rate limit) are NOT retried —
                retrying a rejected order is dangerous.

        Returns:
            The parsed JSON body. Binance returns either an object (dict) or
            an array (list) depending on endpoint.

        Raises:
            ConfigurationError: If the client has not been connected.
            RateLimitError: On HTTP 429 or 418, or Binance code -1003.
            BinanceAPIError: On any other Binance-side error.
            httpx.HTTPError: On unrecoverable transport-level errors.
        """
        if self._client is None:
            raise ConfigurationError(
                "BinanceRestClient is not connected. "
                "Use `async with client:` or call `await client.connect()`."
            )

        # signed implies keyed; normalize so caller doesn't have to pass both.
        if signed:
            keyed = True

        # Build the parameter dict. We must NOT mutate the caller's dict.
        request_params: dict = dict(params or {})

        # For signed requests, append timestamp + recvWindow, then sign.
        # We use httpx's built-in QueryParams for URL encoding — passing
        # a dict to httpx.request(params=...) gives us the canonical form
        # we then need to feed to sign(). To stay in lockstep, we encode
        # ourselves first and reuse the encoded string for both signing
        # and the actual request.
        if signed:
            request_params["timestamp"] = self._now_ms()
            request_params["recvWindow"] = self._recv_window_ms
            # Stable ordering: httpx.QueryParams preserves dict insertion
            # order on Python 3.7+. The signature must match exactly what
            # gets sent on the wire — so we encode once and use the same
            # encoded string for both signing and the request URL.
            query_string = str(httpx.QueryParams(request_params))
            signature = sign(query_string, self._api_secret)
            # Pass the full encoded string to httpx as the URL suffix,
            # NOT as params= — otherwise httpx would re-encode and the
            # signature could mismatch on edge cases (spaces, plus signs).
            full_url = f"{self._make_url(path)}?{query_string}&signature={signature}"
            request_kwargs: dict = {"url": full_url}
        else:
            request_kwargs = {
                "url": self._make_url(path),
                "params": request_params if request_params else None,
            }

        # --- Send with retry on transport errors --------------------------
        attempt = 0
        while True:
            try:
                response = await self._client.request(method, **request_kwargs)
                break  # got a response (any status), stop retrying
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt >= max_retries:
                    raise
                attempt += 1
                # Backoff is intentionally simple: linear, no jitter. Binance
                # rate limits are weight-based, not request-based, so a tight
                # retry on a transient timeout is fine.
                # asyncio.sleep import deferred to here to keep top-level
                # imports clean.
                import asyncio
                await asyncio.sleep(0.5 * attempt)

        # --- Translate HTTP status / Binance error codes ------------------
        return self._parse_response(response)

    @staticmethod
    def _now_ms() -> int:
        """Current Unix time in milliseconds. Used for signed-request timestamp."""
        import time
        return int(time.time() * 1000)

    @staticmethod
    def _parse_response(response: httpx.Response) -> dict | list:
        """Map an httpx.Response to either a parsed body or a raised exception.

        Binance error envelope is `{"code": -1121, "msg": "Invalid symbol."}`.
        HTTP 429 and 418 are rate-limit / ban responses. Anything else 4xx/5xx
        without a Binance code is treated as a generic transport-level error.
        """
        # Rate limit FIRST — these have specific HTTP statuses.
        if response.status_code in (418, 429):
            # Binance puts the cool-down hint in Retry-After (seconds).
            retry_after = response.headers.get("Retry-After", "unknown")
            raise RateLimitError(
                code=-1003,
                message=(
                    f"HTTP {response.status_code} from Binance; "
                    f"Retry-After: {retry_after}"
                ),
                http_status=response.status_code,
            )

        # Try to parse the body. Even on 4xx Binance usually returns JSON.
        try:
            body = response.json()
        except Exception:  # ValueError, JSONDecodeError, etc.
            # If we got here with a 2xx but non-JSON body, surface as API error.
            raise BinanceAPIError(
                code=-1,
                message=f"non-JSON response: {response.text[:200]!r}",
                http_status=response.status_code,
            )

        # 2xx with a JSON body — happy path.
        if 200 <= response.status_code < 300:
            return body

        # 4xx/5xx with JSON — extract Binance code+msg if present.
        if isinstance(body, dict) and "code" in body and "msg" in body:
            code = int(body["code"])
            msg = str(body["msg"])
            # -1003 specifically is rate limit even outside 429.
            if code == -1003:
                raise RateLimitError(
                    code=code, message=msg, http_status=response.status_code
                )
            raise BinanceAPIError(
                code=code, message=msg, http_status=response.status_code
            )

        # 4xx/5xx without Binance's error envelope — unknown shape.
        raise BinanceAPIError(
            code=-1,
            message=f"unexpected response: {str(body)[:200]!r}",
            http_status=response.status_code,
        )
    # --- Safe repr (no key leakage) -----------------------------------------

    def __repr__(self) -> str:
        # Deliberately do NOT include api_key / api_secret. If someone logs
        # the client object, we don't want credentials in the log.
        return (
            f"BinanceRestClient(env={self._env.value}, "
            f"base_url={self.base_url}, "
            f"connected={self.is_connected})"
        )