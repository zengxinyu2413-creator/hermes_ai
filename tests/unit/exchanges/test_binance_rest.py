"""Unit tests for BinanceRestClient — the bits we couldn't validate live.

The real Binance testnet has already covered:
    * Happy-path requests (ping, server_time, klines all returned real data)
    * One real error (invalid symbol -> -1121 / HTTP 400)

What's left to test is what we CAN'T easily trigger against the live API:
    * Rate-limit responses (HTTP 429 / 418 / Binance code -1003)
    * 5xx server errors
    * Network-level retries
    * Edge cases in the response body shape

We achieve this by:
    1. For _parse_response (pure function over httpx.Response): construct
       Response objects directly. No mocking at all.
    2. For _request (does I/O): use httpx.MockTransport to intercept calls
       at the transport layer. The rest of the client (signing, URL building,
       error routing) runs for real — only the actual socket I/O is faked.
"""
from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from hermes.core.exceptions import BinanceAPIError, RateLimitError
from hermes.exchanges.binance_rest import BinanceRestClient

from hermes.exchanges._signing import sign
from hermes.exchanges.binance_credentials import BinanceEnvironment
# --- Helpers ------------------------------------------------------------------

def _make_response(
    status_code: int,
    body: Any = None,
    *,
    body_is_text: bool = False,
    headers: dict | None = None,
) -> httpx.Response:
    """Build an httpx.Response with a parseable body, the way the real
    transport layer would deliver one. Used by all _parse_response tests."""
    if body_is_text:
        content = body if isinstance(body, bytes) else (body or "").encode()
    elif body is None:
        content = b""
    else:
        content = json.dumps(body).encode()

    return httpx.Response(
        status_code=status_code,
        content=content,
        headers=headers or {},
        # Without request= attached, raise_for_status crashes. Set a dummy.
        request=httpx.Request("GET", "https://testnet.binance.vision/api/v3/ping"),
    )


# --- Tests --------------------------------------------------------------------

class TestParseResponseHappyPath:
    """2xx responses with parseable JSON should return the body unchanged."""

    def test_returns_dict_on_2xx_with_dict_body(self):
        resp = _make_response(200, {"serverTime": 1234567890})
        result = BinanceRestClient._parse_response(resp)
        assert result == {"serverTime": 1234567890}

    def test_returns_empty_dict_on_2xx_with_empty_object(self):
        # /api/v3/ping returns literally `{}` — test that we pass it through.
        resp = _make_response(200, {})
        result = BinanceRestClient._parse_response(resp)
        assert result == {}

    def test_returns_list_on_2xx_with_array_body(self):
        # /api/v3/klines returns a list of 12-element arrays.
        kline_rows = [
            [1499040000000, "0.0163", "0.0163", "0.0163", "0.0163", "148.0",
             1499040059999, "2.4", 50, "100.0", "1.6", "0"],
        ]
        resp = _make_response(200, kline_rows)
        result = BinanceRestClient._parse_response(resp)
        assert isinstance(result, list)
        assert result[0][0] == 1499040000000

    def test_returns_list_on_2xx_with_empty_array(self):
        # Edge: a symbol with no recent activity — Binance may return [].
        resp = _make_response(200, [])
        result = BinanceRestClient._parse_response(resp)
        assert result == []


class TestParseResponseRateLimit:
    """Rate-limit cases — these are the cases we CAN'T safely trigger live."""

    def test_http_429_raises_rate_limit_error(self):
        # Binance returns 429 when we exceed per-minute weight.
        resp = _make_response(
            429,
            {"code": -1003, "msg": "Too many requests."},
            headers={"Retry-After": "60"},
        )
        with pytest.raises(RateLimitError) as exc_info:
            BinanceRestClient._parse_response(resp)
        err = exc_info.value
        assert err.http_status == 429
        # The implementation includes Retry-After in the message for visibility.
        assert "60" in err.message

    def test_http_418_raises_rate_limit_error(self):
        # HTTP 418 ("I'm a teapot") means the IP has been banned for repeated
        # violations. Same code path as 429 — must NOT be retried.
        resp = _make_response(418, {"code": -1003, "msg": "IP banned"})
        with pytest.raises(RateLimitError) as exc_info:
            BinanceRestClient._parse_response(resp)
        assert exc_info.value.http_status == 418

    def test_code_minus_1003_raises_rate_limit_even_at_2xx_or_4xx(self):
        # If Binance ever returns -1003 in a body without the matching 4xx
        # status, we still must route it to RateLimitError, not to the generic
        # BinanceAPIError bucket. Otherwise callers can't tell to back off.
        resp = _make_response(400, {"code": -1003, "msg": "Too many requests"})
        with pytest.raises(RateLimitError):
            BinanceRestClient._parse_response(resp)

    def test_rate_limit_retry_after_missing_is_tolerated(self):
        # 429 without Retry-After header — must still raise, just without the
        # backoff hint.
        resp = _make_response(429, {"code": -1003, "msg": "Too many requests"})
        with pytest.raises(RateLimitError) as exc_info:
            BinanceRestClient._parse_response(resp)
        # The message should mention 'unknown' or have no specific seconds.
        assert exc_info.value.http_status == 429


class TestParseResponseBinanceErrors:
    """4xx / 5xx with the standard Binance error envelope."""

    def test_http_400_with_envelope_raises_binance_api_error(self):
        # The real -1121 case we already saw on testnet, replayed offline.
        resp = _make_response(400, {"code": -1121, "msg": "Invalid symbol."})
        with pytest.raises(BinanceAPIError) as exc_info:
            BinanceRestClient._parse_response(resp)
        err = exc_info.value
        assert err.code == -1121
        assert err.message == "Invalid symbol."
        assert err.http_status == 400
        # It must NOT be a RateLimitError — otherwise caller would back off
        # forever instead of fixing the bad symbol.
        assert not isinstance(err, RateLimitError)

    def test_http_401_with_envelope_raises_binance_api_error(self):
        # Bad API key / signature -> -2014 / 401.
        resp = _make_response(
            401, {"code": -2014, "msg": "API-key format invalid."}
        )
        with pytest.raises(BinanceAPIError) as exc_info:
            BinanceRestClient._parse_response(resp)
        assert exc_info.value.code == -2014
        assert exc_info.value.http_status == 401

    def test_http_500_with_envelope_raises_binance_api_error(self):
        # Server-side error during a deploy or incident.
        resp = _make_response(
            500, {"code": -1000, "msg": "An unknown error occurred."}
        )
        with pytest.raises(BinanceAPIError) as exc_info:
            BinanceRestClient._parse_response(resp)
        assert exc_info.value.code == -1000
        assert exc_info.value.http_status == 500


class TestParseResponseMalformed:
    """Responses that don't fit Binance's contract — we should fail loudly."""

    def test_2xx_with_non_json_body_raises(self):
        # If Binance returns HTML (e.g. WAF page during DDoS), parsing must not
        # silently return {} — we want an exception so the caller knows.
        resp = _make_response(200, "<html>Cloudflare blocked</html>",
                              body_is_text=True)
        with pytest.raises(BinanceAPIError) as exc_info:
            BinanceRestClient._parse_response(resp)
        err = exc_info.value
        # code=-1 is our sentinel for "not a real Binance error envelope".
        assert err.code == -1

    def test_4xx_without_envelope_raises_binance_api_error(self):
        # 4xx where the body isn't a Binance error envelope — e.g. a stray
        # gateway response. Must still raise BinanceAPIError so callers handle
        # it uniformly.
        resp = _make_response(
            400, {"unexpected": "shape"}  # no code / msg keys
        )
        with pytest.raises(BinanceAPIError) as exc_info:
            BinanceRestClient._parse_response(resp)
        assert exc_info.value.code == -1
        assert exc_info.value.http_status == 400

    def test_4xx_with_string_body_still_raises(self):
        # NOTE: Current implementation calls response.raise_for_status() in the
        # error path, which surfaces httpx.HTTPStatusError for non-JSON 5xx.
        # This is a known gap to be normalized to BinanceAPIError later.
        import httpx
        resp = _make_response(503, "Service Unavailable", body_is_text=True)
        with pytest.raises((BinanceAPIError, httpx.HTTPStatusError)):
            BinanceRestClient._parse_response(resp)
# ============================================================================
# _request engine tests — mock httpx transport, real business logic
# ============================================================================

import pytest_asyncio
from urllib.parse import parse_qs, urlparse


def _build_mock_client(
    handler,
    *,
    api_key: str = "test_api_key",
    api_secret: str = "test_api_secret",
    env: BinanceEnvironment = BinanceEnvironment.TESTNET,
    recv_window_ms: int = 5000,
) -> BinanceRestClient:
    """Construct a BinanceRestClient whose httpx.AsyncClient routes through
    a MockTransport. The client is pre-'connected' so tests don't need
    async with.

    `handler` is a callable that receives an httpx.Request and returns an
    httpx.Response. This is httpx's standard MockTransport contract.
    """
    client = BinanceRestClient(
        api_key=api_key,
        api_secret=api_secret,
        env=env,
        recv_window_ms=recv_window_ms,
    )
    # Replace the real AsyncClient with one wired to MockTransport.
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={"X-MBX-APIKEY": api_key},
    )
    return client


# --- URL / method / params ----------------------------------------------------

class TestRequestUrlAndMethod:

    @pytest.mark.asyncio
    async def test_get_request_hits_correct_url(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["method"] = request.method
            return httpx.Response(200, json={"ok": True})

        client = _build_mock_client(handler)
        try:
            await client._request("GET", "/api/v3/ping")
        finally:
            await client.aclose()

        # Testnet base + the path we asked for.
        assert seen["method"] == "GET"
        assert seen["url"].startswith("https://testnet.binance.vision/api/v3/ping")

    @pytest.mark.asyncio
    async def test_post_request_uses_post_method(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["method"] = request.method
            return httpx.Response(200, json={"orderId": 1})

        client = _build_mock_client(handler)
        try:
            await client._request("POST", "/api/v3/order", signed=True)
        finally:
            await client.aclose()

        assert seen["method"] == "POST"

    @pytest.mark.asyncio
    async def test_unsigned_params_are_url_encoded(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["query"] = parse_qs(urlparse(str(request.url)).query)
            return httpx.Response(200, json=[])

        client = _build_mock_client(handler)
        try:
            await client._request(
                "GET", "/api/v3/klines",
                params={"symbol": "SOLUSDT", "interval": "1m", "limit": 10},
            )
        finally:
            await client.aclose()

        # parse_qs gives us {key: [value]} — values stay as lists.
        assert seen["query"]["symbol"] == ["SOLUSDT"]
        assert seen["query"]["interval"] == ["1m"]
        assert seen["query"]["limit"] == ["10"]

    @pytest.mark.asyncio
    async def test_mainnet_uses_correct_base_url(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            return httpx.Response(200, json={})

        client = _build_mock_client(handler, env=BinanceEnvironment.MAINNET)
        try:
            await client._request("GET", "/api/v3/ping")
        finally:
            await client.aclose()

        # Mainnet -> api.binance.com.
        assert seen["url"].startswith("https://api.binance.com/api/v3/ping")


# --- Headers -----------------------------------------------------------------

class TestRequestHeaders:

    @pytest.mark.asyncio
    async def test_apikey_header_present_on_unsigned_request(self):
        # X-MBX-APIKEY is always sent. Public endpoints ignore it, but
        # 'keyed' endpoints (e.g. listenKey) require it without a signature.
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["apikey"] = request.headers.get("X-MBX-APIKEY")
            return httpx.Response(200, json={})

        client = _build_mock_client(handler, api_key="hello_world_key")
        try:
            await client._request("GET", "/api/v3/ping")
        finally:
            await client.aclose()

        assert seen["apikey"] == "hello_world_key"

    @pytest.mark.asyncio
    async def test_apikey_header_present_on_signed_request(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["apikey"] = request.headers.get("X-MBX-APIKEY")
            return httpx.Response(200, json={"can_trade": True, "balances": []})

        client = _build_mock_client(handler, api_key="signed_key")
        try:
            await client._request("GET", "/api/v3/account", signed=True)
        finally:
            await client.aclose()

        assert seen["apikey"] == "signed_key"


# --- Signed request mechanics -------------------------------------------------

class TestRequestSigned:
    """Signed requests must inject timestamp + recvWindow AND a valid HMAC."""

    @pytest.mark.asyncio
    async def test_signed_request_includes_timestamp_recvwindow_signature(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["query"] = parse_qs(urlparse(str(request.url)).query)
            return httpx.Response(200, json={})

        client = _build_mock_client(handler)
        try:
            await client._request("GET", "/api/v3/account", signed=True)
        finally:
            await client.aclose()

        q = seen["query"]
        # Three mandatory keys.
        assert "timestamp" in q
        assert "recvWindow" in q
        assert "signature" in q
        # timestamp is a 13-digit ms epoch.
        assert len(q["timestamp"][0]) == 13
        # signature is a 64-char lowercase hex digest.
        sig = q["signature"][0]
        assert len(sig) == 64
        assert sig == sig.lower()

    @pytest.mark.asyncio
    async def test_signature_value_matches_signing_module(self):
        # Recompute the signature the same way _signing.sign does, using the
        # query string the client actually sent. If they match, _request is
        # signing the exact bytes that go on the wire.
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            url = urlparse(str(request.url))
            seen["raw_query"] = url.query
            return httpx.Response(200, json={})

        client = _build_mock_client(handler, api_secret="my_test_secret")
        try:
            await client._request("GET", "/api/v3/account", signed=True)
        finally:
            await client.aclose()

        # Split the query into the signed-portion and the signature.
        raw = seen["raw_query"]
        assert "&signature=" in raw, raw
        signed_portion, sent_sig = raw.rsplit("&signature=", 1)

        recomputed = sign(signed_portion, "my_test_secret")
        assert sent_sig == recomputed

    @pytest.mark.asyncio
    async def test_recv_window_uses_client_config(self):
        # Per-client recv_window_ms must propagate into the request.
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["query"] = parse_qs(urlparse(str(request.url)).query)
            return httpx.Response(200, json={})

        client = _build_mock_client(handler, recv_window_ms=3000)
        try:
            await client._request("GET", "/api/v3/account", signed=True)
        finally:
            await client.aclose()

        assert seen["query"]["recvWindow"] == ["3000"]


# --- Unsigned request mechanics ----------------------------------------------

class TestRequestUnsigned:
    """Public endpoints must NOT add signing artifacts to the URL."""

    @pytest.mark.asyncio
    async def test_unsigned_request_has_no_signing_params(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["query"] = parse_qs(urlparse(str(request.url)).query)
            return httpx.Response(200, json={})

        client = _build_mock_client(handler)
        try:
            await client._request("GET", "/api/v3/ping")
        finally:
            await client.aclose()

        # None of these should appear on an unsigned call.
        assert "timestamp" not in seen["query"]
        assert "recvWindow" not in seen["query"]
        assert "signature" not in seen["query"]


# --- Connection lifecycle guard ----------------------------------------------

class TestRequestNotConnected:
    """Calling _request before connect()/__aenter__ must fail loudly."""

    @pytest.mark.asyncio
    async def test_unconnected_client_raises_configuration_error(self):
        from hermes.core.exceptions import ConfigurationError

        client = BinanceRestClient(
            api_key="x",
            api_secret="x",
            env=BinanceEnvironment.TESTNET,
        )
        # Do NOT call connect() / enter context.
        with pytest.raises(ConfigurationError):
            await client._request("GET", "/api/v3/ping")


# --- End-to-end error routing -----------------------------------------------

class TestRequestErrorRouting:
    """End-to-end: from network response back through _parse_response,
    we should get the right typed exception out."""

    @pytest.mark.asyncio
    async def test_4xx_binance_envelope_raises_binance_api_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                400, json={"code": -1121, "msg": "Invalid symbol."}
            )

        client = _build_mock_client(handler)
        try:
            with pytest.raises(BinanceAPIError) as exc_info:
                await client._request("GET", "/api/v3/klines",
                                      params={"symbol": "BAD"})
            assert exc_info.value.code == -1121
            assert exc_info.value.http_status == 400
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_429_raises_rate_limit_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                429,
                json={"code": -1003, "msg": "Too many requests."},
                headers={"Retry-After": "30"},
            )

        client = _build_mock_client(handler)
        try:
            with pytest.raises(RateLimitError) as exc_info:
                await client._request("GET", "/api/v3/ping")
            assert exc_info.value.http_status == 429
        finally:
            await client.aclose() 
# ============================================================================
# Retry logic tests — only network-level errors retry; business errors don't
# ============================================================================

import time as _time


def _build_counting_client(
    handler_factory,
    *,
    max_retries: int = 2,
) -> BinanceRestClient:
    """Variant of _build_mock_client where the test can inject a handler
    that counts calls and behaves differently each time.

    `handler_factory` is a callable () -> handler, but we wrap it so each call
    to the transport invokes the same handler closure (which is responsible
    for tracking its own state).
    """
    client = BinanceRestClient(
        api_key="x",
        api_secret="x",
        env=BinanceEnvironment.TESTNET,
    )
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler_factory),
        headers={"X-MBX-APIKEY": "x"},
    )
    return client


# --- Retryable: network-level errors ----------------------------------------

class TestRequestRetryOnNetworkErrors:
    """TimeoutException and NetworkError should trigger automatic retry."""

    @pytest.mark.asyncio
    async def test_timeout_then_success_returns_success(self):
        """First call times out, second succeeds. _request should retry and
        return the eventual success, not propagate the timeout."""
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            if call_count["n"] == 1:
                # MockTransport will surface raised exceptions as if the
                # network layer raised them. This is how we simulate a
                # connection timeout.
                raise httpx.TimeoutException("simulated timeout", request=request)
            return httpx.Response(200, json={"ok": True})

        client = _build_counting_client(handler)
        try:
            result = await client._request(
                "GET", "/api/v3/ping", max_retries=2,
            )
        finally:
            await client.aclose()

        assert call_count["n"] == 2
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_network_error_then_success_returns_success(self):
        """NetworkError (e.g. connection reset) should also retry."""
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise httpx.NetworkError("simulated reset", request=request)
            return httpx.Response(200, json={})

        client = _build_counting_client(handler)
        try:
            result = await client._request("GET", "/api/v3/ping", max_retries=2)
        finally:
            await client.aclose()

        assert call_count["n"] == 2
        assert result == {}

    @pytest.mark.asyncio
    async def test_two_failures_then_success_uses_all_retries(self):
        """Verify the retry budget — 2 retries means 3 total attempts allowed."""
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise httpx.TimeoutException("flaky", request=request)
            return httpx.Response(200, json={"final": True})

        client = _build_counting_client(handler)
        try:
            result = await client._request("GET", "/api/v3/ping", max_retries=2)
        finally:
            await client.aclose()

        assert call_count["n"] == 3        # 1 initial + 2 retries
        assert result == {"final": True}


# --- Retry exhaustion --------------------------------------------------------

class TestRequestRetryExhaustion:
    """When max_retries is exceeded, the underlying exception must propagate."""

    @pytest.mark.asyncio
    async def test_persistent_timeout_raises_after_retries(self):
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            raise httpx.TimeoutException("never recovers", request=request)

        client = _build_counting_client(handler)
        try:
            with pytest.raises(httpx.TimeoutException):
                await client._request("GET", "/api/v3/ping", max_retries=2)
        finally:
            await client.aclose()

        # 1 initial + 2 retries = 3 attempts before giving up.
        assert call_count["n"] == 3

    @pytest.mark.asyncio
    async def test_max_retries_zero_disables_retries(self):
        """max_retries=0 should fail on the very first network error."""
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            raise httpx.TimeoutException("immediate", request=request)

        client = _build_counting_client(handler)
        try:
            with pytest.raises(httpx.TimeoutException):
                await client._request("GET", "/api/v3/ping", max_retries=0)
        finally:
            await client.aclose()

        assert call_count["n"] == 1


# --- Non-retryable: business errors -----------------------------------------

class TestRequestNoRetryOnBusinessErrors:
    """BinanceAPIError and similar must NEVER retry. Retrying a rejected order
    is dangerous — we could end up placing duplicate trades."""

    @pytest.mark.asyncio
    async def test_400_with_binance_envelope_does_not_retry(self):
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            return httpx.Response(
                400, json={"code": -1121, "msg": "Invalid symbol."}
            )

        client = _build_counting_client(handler)
        try:
            with pytest.raises(BinanceAPIError):
                await client._request("GET", "/api/v3/klines", max_retries=2)
        finally:
            await client.aclose()

        # Exactly ONE call. No retries on a clean Binance rejection.
        assert call_count["n"] == 1

    @pytest.mark.asyncio
    async def test_429_rate_limit_does_not_retry(self):
        """We surface RateLimitError so the caller can apply its own backoff
        strategy. Auto-retrying on 429 would compound the rate-limit problem."""
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            return httpx.Response(
                429,
                json={"code": -1003, "msg": "Too many requests."},
                headers={"Retry-After": "10"},
            )

        client = _build_counting_client(handler)
        try:
            with pytest.raises(RateLimitError):
                await client._request("GET", "/api/v3/ping", max_retries=5)
        finally:
            await client.aclose()

        assert call_count["n"] == 1


# --- Backoff timing ----------------------------------------------------------

class TestRequestBackoffTiming:
    """Light verification that the linear-backoff sleep actually happens.

    We don't pin exact timings (CI is noisy). We just verify that retrying
    N times takes AT LEAST the expected minimum total backoff time, so the
    code isn't busy-looping.
    """

    @pytest.mark.asyncio
    async def test_retries_apply_some_backoff(self):
        """With 2 retries at 0.5*attempt seconds each, total backoff is at
        least 0.5 + 1.0 = 1.5s before the 3rd attempt. We use a generous
        floor (1.0s) to keep this test stable on slow CI hosts."""
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise httpx.TimeoutException("flaky", request=request)
            return httpx.Response(200, json={})

        client = _build_counting_client(handler)
        start = _time.monotonic()
        try:
            await client._request("GET", "/api/v3/ping", max_retries=2)
        finally:
            await client.aclose()
        elapsed = _time.monotonic() - start

        # Linear backoff sums: 0.5 + 1.0 = 1.5s minimum (excluding handler
        # exec time). Floor at 1.0s for safety.
        assert elapsed >= 1.0, f"expected backoff > 1.0s, got {elapsed:.2f}s" 
# ============================================================================
# Endpoint-level mock tests — exercise each public method end-to-end with a
# mocked transport. Real Binance testnet has already covered happy paths;
# these tests lock down the response-parsing edges.
# ============================================================================

from decimal import Decimal as _Decimal

from hermes.exchanges.binance_contracts import KlineInterval, Kline


# --- ping() ------------------------------------------------------------------

class TestPingMock:

    @pytest.mark.asyncio
    async def test_ping_returns_dict_on_success(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/v3/ping"
            return httpx.Response(200, json={})

        client = _build_mock_client(handler)
        try:
            result = await client.ping()
        finally:
            await client.aclose()

        assert result == {}
        assert isinstance(result, dict)


# --- server_time_ms() / time_offset_ms() ------------------------------------

class TestServerTimeMock:

    @pytest.mark.asyncio
    async def test_server_time_parses_servertime_field(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/v3/time"
            return httpx.Response(200, json={"serverTime": 1700000000123})

        client = _build_mock_client(handler)
        try:
            result = await client.server_time_ms()
        finally:
            await client.aclose()

        assert isinstance(result, int)
        assert result == 1700000000123


class TestTimeOffsetMock:
    """time_offset_ms is server_time - local_midpoint. With a controlled mock
    we can verify the math without depending on wall-clock alignment."""

    @pytest.mark.asyncio
    async def test_zero_offset_when_server_matches_local(self):
        # The handler reads local time on the fly and returns it — so server
        # and local appear perfectly synchronized.
        def handler(request: httpx.Request) -> httpx.Response:
            now_ms = int(_time.time() * 1000)
            return httpx.Response(200, json={"serverTime": now_ms})

        client = _build_mock_client(handler)
        try:
            offset = await client.time_offset_ms()
        finally:
            await client.aclose()

        # Allow a few ms of slop from how _now_ms is called twice.
        assert abs(offset) < 100, f"expected near-zero offset, got {offset}ms"

    @pytest.mark.asyncio
    async def test_positive_offset_when_server_ahead(self):
        # Force server time to be ~500ms ahead of local — emulates a clock
        # that's behind Binance.
        def handler(request: httpx.Request) -> httpx.Response:
            future = int(_time.time() * 1000) + 500
            return httpx.Response(200, json={"serverTime": future})

        client = _build_mock_client(handler)
        try:
            offset = await client.time_offset_ms()
        finally:
            await client.aclose()

        # Should be roughly +500, with some round-trip noise.
        assert 400 < offset < 700, f"expected ~+500ms, got {offset}ms"


# --- get_klines() ------------------------------------------------------------

# A minimal but realistic 12-element row, in the shape Binance returns.
_SAMPLE_KLINE_ROW = [
    1700000000000,          # 0  open_time
    "100.50",               # 1  open
    "101.20",               # 2  high
    "100.40",               # 3  low
    "101.00",               # 4  close
    "12.345",               # 5  volume (base)
    1700000059999,          # 6  close_time
    "1244.42",              # 7  quote_volume
    87,                     # 8  trades
    "5.678",                # 9  taker_buy_base_volume
    "572.13",               # 10 taker_buy_quote_volume
    "0",                    # 11 ignored
]


class TestGetKlinesMock:

    @pytest.mark.asyncio
    async def test_parses_single_bar(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/v3/klines"
            return httpx.Response(200, json=[_SAMPLE_KLINE_ROW])

        client = _build_mock_client(handler)
        try:
            bars = await client.get_klines("SOLUSDT", KlineInterval.MIN_1, limit=1)
        finally:
            await client.aclose()

        assert len(bars) == 1
        b = bars[0]
        assert isinstance(b, Kline)
        assert b.symbol == "SOLUSDT"
        assert b.interval == KlineInterval.MIN_1
        assert b.open_time_ms == 1700000000000
        assert b.close_time_ms == 1700000059999
        # Decimal type matters for PnL accuracy downstream.
        assert isinstance(b.open, _Decimal)
        assert b.open == _Decimal("100.50")
        assert b.close == _Decimal("101.00")
        assert b.trades == 87  # int, not Decimal

    @pytest.mark.asyncio
    async def test_parses_multiple_bars_preserves_order(self):
        rows = [
            [t, "1", "1", "1", "1", "1", t + 59999, "1", 1, "1", "1", "0"]
            for t in (1700000000000, 1700000060000, 1700000120000)
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=rows)

        client = _build_mock_client(handler)
        try:
            bars = await client.get_klines("SOLUSDT", KlineInterval.MIN_1, limit=3)
        finally:
            await client.aclose()

        assert len(bars) == 3
        # Order is preserved — Binance returns oldest first; we don't re-sort.
        assert bars[0].open_time_ms < bars[1].open_time_ms < bars[2].open_time_ms

    @pytest.mark.asyncio
    async def test_empty_response_returns_empty_list(self):
        # Binance returns [] for symbols with no recent data. Strategy code
        # must be able to handle len(bars) == 0 without exception.
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[])

        client = _build_mock_client(handler)
        try:
            bars = await client.get_klines("NEWLISTING", KlineInterval.MIN_1)
        finally:
            await client.aclose()

        assert bars == []
        assert isinstance(bars, list)

    @pytest.mark.asyncio
    async def test_query_params_use_uppercase_symbol_and_interval_value(self):
        """Lowercase symbol input must be sent uppercase. Interval enum value
        must be sent as the literal Binance expects ('1m', not 'MIN_1')."""
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["query"] = dict(request.url.params)
            return httpx.Response(200, json=[])

        client = _build_mock_client(handler)
        try:
            await client.get_klines("solusdt", KlineInterval.HOUR_1, limit=42)
        finally:
            await client.aclose()

        assert seen["query"]["symbol"] == "SOLUSDT"
        assert seen["query"]["interval"] == "1h"
        assert seen["query"]["limit"] == "42"

    @pytest.mark.asyncio
    async def test_invalid_symbol_raises_binance_api_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                400, json={"code": -1121, "msg": "Invalid symbol."}
            )

        client = _build_mock_client(handler)
        try:
            with pytest.raises(BinanceAPIError) as exc_info:
                await client.get_klines("BADSYMBOL", KlineInterval.MIN_1)
        finally:
            await client.aclose()

        assert exc_info.value.code == -1121
        assert exc_info.value.http_status == 400

    @pytest.mark.asyncio
    async def test_limit_out_of_range_raises_value_error_locally(self):
        # The client must validate `limit` BEFORE making the network call.
        # Otherwise we waste a request and a rate-limit slot on something
        # we know upfront is invalid.
        # We use a handler that fails the test if called — no request expected.
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("network was hit; limit validation missing!")

        client = _build_mock_client(handler)
        try:
            with pytest.raises(ValueError):
                await client.get_klines("SOLUSDT", KlineInterval.MIN_1, limit=2000)
            with pytest.raises(ValueError):
                await client.get_klines("SOLUSDT", KlineInterval.MIN_1, limit=0)
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_non_list_response_surfaces_as_binance_api_error(self):
        """get_klines explicitly checks `isinstance(rows, list)` and raises
        if Binance ever returns a dict here. This guards against silent
        contract changes."""
        def handler(request: httpx.Request) -> httpx.Response:
            # Return a dict where a list is expected — broken shape.
            return httpx.Response(200, json={"unexpected": "dict"})

        client = _build_mock_client(handler)
        try:
            with pytest.raises(BinanceAPIError) as exc_info:
                await client.get_klines("SOLUSDT", KlineInterval.MIN_1)
        finally:
            await client.aclose()

        assert exc_info.value.code == -1


# ============================================================================
# new_order() tests — mock transport, all validation before network
# ============================================================================

class TestNewOrderMock:
    """new_order: POST /api/v3/order — signed, max_retries=0, no real network."""

    @pytest.mark.asyncio
    async def test_market_buy_post_to_order_endpoint_signed(self):
        """MARKET BUY: method=POST, path=/api/v3/order, signed params present,
        no price, no timeInForce in query."""
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["method"] = request.method
            seen["path"] = request.url.path
            seen["query"] = dict(parse_qs(urlparse(str(request.url)).query))
            return httpx.Response(200, json={"orderId": 1, "status": "FILLED"})

        client = _build_mock_client(handler)
        try:
            result = await client.new_order("solusdt", "BUY", "MARKET", _Decimal("1.5"))
        finally:
            await client.aclose()

        assert seen["method"] == "POST"
        assert seen["path"] == "/api/v3/order"
        q = seen["query"]
        assert "timestamp" in q
        assert "recvWindow" in q
        assert "signature" in q
        assert q["type"] == ["MARKET"]
        assert q["side"] == ["BUY"]
        assert q["symbol"] == ["SOLUSDT"]
        assert "price" not in q
        assert "timeInForce" not in q
        assert isinstance(result, dict)
        assert result["orderId"] == 1

    @pytest.mark.asyncio
    async def test_limit_sell_includes_price_and_time_in_force(self):
        """LIMIT SELL: params contain price and timeInForce=GTC."""
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["query"] = dict(parse_qs(urlparse(str(request.url)).query))
            return httpx.Response(200, json={"orderId": 2, "status": "NEW"})

        client = _build_mock_client(handler)
        try:
            await client.new_order(
                "BTCUSDT", "SELL", "LIMIT", _Decimal("0.01"),
                price=_Decimal("50000.00"),
            )
        finally:
            await client.aclose()

        q = seen["query"]
        assert q["type"] == ["LIMIT"]
        assert q["side"] == ["SELL"]
        assert "price" in q
        assert q["timeInForce"] == ["GTC"]

    @pytest.mark.asyncio
    async def test_small_quantity_not_scientific_notation(self):
        """quantity=Decimal('0.00000001') must arrive as '0.00000001', not '1E-8'."""
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["query"] = dict(parse_qs(urlparse(str(request.url)).query))
            return httpx.Response(200, json={"orderId": 3})

        client = _build_mock_client(handler)
        try:
            await client.new_order(
                "ETHUSDT", "BUY", "MARKET", _Decimal("0.00000001")
            )
        finally:
            await client.aclose()

        assert seen["query"]["quantity"] == ["0.00000001"]

    @pytest.mark.asyncio
    async def test_invalid_side_raises_before_network(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("network hit; side validation missing")

        client = _build_mock_client(handler)
        try:
            with pytest.raises(ValueError):
                await client.new_order("SOLUSDT", "LONG", "MARKET", _Decimal("1"))
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_invalid_order_type_raises_before_network(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("network hit; order_type validation missing")

        client = _build_mock_client(handler)
        try:
            with pytest.raises(ValueError):
                await client.new_order("SOLUSDT", "BUY", "STOP", _Decimal("1"))
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_zero_quantity_raises_before_network(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("network hit; quantity=0 validation missing")

        client = _build_mock_client(handler)
        try:
            with pytest.raises(ValueError):
                await client.new_order("SOLUSDT", "BUY", "MARKET", _Decimal("0"))
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_float_quantity_raises_before_network(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("network hit; float quantity validation missing")

        client = _build_mock_client(handler)
        try:
            with pytest.raises(ValueError):
                await client.new_order(
                    "SOLUSDT", "BUY", "MARKET", 1.5  # type: ignore[arg-type]
                )
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_limit_without_price_raises_before_network(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("network hit; LIMIT price validation missing")

        client = _build_mock_client(handler)
        try:
            with pytest.raises(ValueError):
                await client.new_order("SOLUSDT", "BUY", "LIMIT", _Decimal("1"))
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_market_with_price_raises_before_network(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("network hit; MARKET+price validation missing")

        client = _build_mock_client(handler)
        try:
            with pytest.raises(ValueError):
                await client.new_order(
                    "SOLUSDT", "BUY", "MARKET", _Decimal("1"),
                    price=_Decimal("100"),
                )
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_binance_rejection_raises_binance_api_error(self):
        """Binance 4xx + error envelope must propagate as BinanceAPIError."""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                400, json={"code": -2010, "msg": "Account has insufficient balance."}
            )

        client = _build_mock_client(handler)
        try:
            with pytest.raises(BinanceAPIError) as exc_info:
                await client.new_order("BTCUSDT", "BUY", "MARKET", _Decimal("0.001"))
        finally:
            await client.aclose()

        assert exc_info.value.code == -2010
        assert exc_info.value.http_status == 400

    @pytest.mark.asyncio
    async def test_new_client_order_id_included_in_params(self):
        """Optional new_client_order_id must appear as newClientOrderId in query."""
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["query"] = dict(parse_qs(urlparse(str(request.url)).query))
            return httpx.Response(200, json={"orderId": 99, "clientOrderId": "my-id-123"})

        client = _build_mock_client(handler)
        try:
            await client.new_order(
                "SOLUSDT", "BUY", "MARKET", _Decimal("1"),
                new_client_order_id="my-id-123",
            )
        finally:
            await client.aclose()

        assert seen["query"]["newClientOrderId"] == ["my-id-123"]


# ============================================================================
# get_account() / get_open_orders() / get_my_trades() — mock transport tests
# ============================================================================

# --- get_account() -----------------------------------------------------------

class TestGetAccountMock:

    @pytest.mark.asyncio
    async def test_returns_dict_on_success(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/v3/account"
            return httpx.Response(
                200, json={"makerCommission": 10, "canTrade": True, "balances": []}
            )

        client = _build_mock_client(handler)
        try:
            result = await client.get_account()
        finally:
            await client.aclose()

        assert isinstance(result, dict)
        assert result["canTrade"] is True

    @pytest.mark.asyncio
    async def test_signed_injects_timestamp_signature_no_symbol(self):
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["query"] = parse_qs(urlparse(str(request.url)).query)
            return httpx.Response(
                200, json={"makerCommission": 10, "canTrade": True, "balances": []}
            )

        client = _build_mock_client(handler)
        try:
            await client.get_account()
        finally:
            await client.aclose()

        q = seen["query"]
        assert "timestamp" in q
        assert "signature" in q
        assert "symbol" not in q

    @pytest.mark.asyncio
    async def test_error_response_raises_binance_api_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"code": -2014, "msg": "API-key format invalid."})

        client = _build_mock_client(handler)
        try:
            with pytest.raises(BinanceAPIError) as exc_info:
                await client.get_account()
        finally:
            await client.aclose()

        assert exc_info.value.code == -2014
        assert exc_info.value.http_status == 401


# --- get_open_orders() -------------------------------------------------------

class TestGetOpenOrdersMock:

    @pytest.mark.asyncio
    async def test_returns_empty_list_without_symbol(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/v3/openOrders"
            return httpx.Response(200, json=[])

        client = _build_mock_client(handler)
        try:
            result = await client.get_open_orders()
        finally:
            await client.aclose()

        assert isinstance(result, list)
        assert result == []

    @pytest.mark.asyncio
    async def test_no_symbol_sends_no_symbol_param(self):
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["query"] = parse_qs(urlparse(str(request.url)).query)
            return httpx.Response(200, json=[])

        client = _build_mock_client(handler)
        try:
            await client.get_open_orders()
        finally:
            await client.aclose()

        assert "symbol" not in seen["query"]

    @pytest.mark.asyncio
    async def test_symbol_uppercased_in_query(self):
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["query"] = dict(request.url.params)
            return httpx.Response(200, json=[])

        client = _build_mock_client(handler)
        try:
            await client.get_open_orders(symbol="solusdt")
        finally:
            await client.aclose()

        assert seen["query"]["symbol"] == "SOLUSDT"

    @pytest.mark.asyncio
    async def test_signed_injects_timestamp_and_signature(self):
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["query"] = parse_qs(urlparse(str(request.url)).query)
            return httpx.Response(200, json=[])

        client = _build_mock_client(handler)
        try:
            await client.get_open_orders()
        finally:
            await client.aclose()

        assert "timestamp" in seen["query"]
        assert "signature" in seen["query"]

    @pytest.mark.asyncio
    async def test_error_response_raises_binance_api_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"code": -1121, "msg": "Invalid symbol."})

        client = _build_mock_client(handler)
        try:
            with pytest.raises(BinanceAPIError) as exc_info:
                await client.get_open_orders(symbol="BADSYMBOL")
        finally:
            await client.aclose()

        assert exc_info.value.code == -1121
        assert exc_info.value.http_status == 400


# --- get_my_trades() ---------------------------------------------------------

_SAMPLE_TRADE = {
    "id": 12345,
    "symbol": "SOLUSDT",
    "orderId": 9876,
    "price": "100.50",
    "qty": "1.00",
    "quoteQty": "100.50",
    "commission": "0.10050",
    "commissionAsset": "USDT",
    "time": 1700000000000,
    "isBuyer": True,
    "isMaker": False,
    "isBestMatch": True,
}


class TestGetMyTradesMock:

    @pytest.mark.asyncio
    async def test_returns_list_on_success(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/v3/myTrades"
            return httpx.Response(200, json=[_SAMPLE_TRADE])

        client = _build_mock_client(handler)
        try:
            result = await client.get_my_trades("SOLUSDT")
        finally:
            await client.aclose()

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["id"] == 12345

    @pytest.mark.asyncio
    async def test_symbol_required_empty_raises_before_network(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("network hit; symbol validation missing")

        client = _build_mock_client(handler)
        try:
            with pytest.raises(ValueError):
                await client.get_my_trades("")
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_symbol_uppercased_in_query(self):
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["query"] = dict(request.url.params)
            return httpx.Response(200, json=[])

        client = _build_mock_client(handler)
        try:
            await client.get_my_trades("solusdt")
        finally:
            await client.aclose()

        assert seen["query"]["symbol"] == "SOLUSDT"

    @pytest.mark.asyncio
    async def test_signed_injects_timestamp_and_signature(self):
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["query"] = parse_qs(urlparse(str(request.url)).query)
            return httpx.Response(200, json=[])

        client = _build_mock_client(handler)
        try:
            await client.get_my_trades("SOLUSDT")
        finally:
            await client.aclose()

        assert "timestamp" in seen["query"]
        assert "signature" in seen["query"]

    @pytest.mark.asyncio
    async def test_optional_params_sent_when_provided(self):
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["query"] = dict(request.url.params)
            return httpx.Response(200, json=[])

        client = _build_mock_client(handler)
        try:
            await client.get_my_trades(
                "SOLUSDT",
                limit=100,
                start_time_ms=1700000000000,
                end_time_ms=1700086400000,
                from_id=99,
            )
        finally:
            await client.aclose()

        assert seen["query"]["limit"] == "100"
        assert seen["query"]["startTime"] == "1700000000000"
        assert seen["query"]["endTime"] == "1700086400000"
        assert seen["query"]["fromId"] == "99"

    @pytest.mark.asyncio
    async def test_invalid_limit_raises_before_network(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("network hit; limit validation missing")

        client = _build_mock_client(handler)
        try:
            with pytest.raises(ValueError):
                await client.get_my_trades("SOLUSDT", limit=2000)
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_error_response_raises_binance_api_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"code": -1121, "msg": "Invalid symbol."})

        client = _build_mock_client(handler)
        try:
            with pytest.raises(BinanceAPIError) as exc_info:
                await client.get_my_trades("BADSYMBOL")
        finally:
            await client.aclose()

        assert exc_info.value.code == -1121
        assert exc_info.value.http_status == 400
