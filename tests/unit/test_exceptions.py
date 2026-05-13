"""Tests for the Hermes exception hierarchy.

We deliberately keep these tests structural rather than behavioural — exceptions
don't have logic, just types and a tiny constructor on BinanceAPIError. The
real value of these tests is catching accidental hierarchy changes (e.g. some
later refactor moves RateLimitError out from under BinanceAPIError, breaking
`except BinanceAPIError` catches in client code).
"""
from __future__ import annotations

import pytest

from hermes.core.exceptions import (
    BinanceAPIError,
    BinanceError,
    ConfigurationError,
    HermesError,
    OrderError,
    RateLimitError,
    SigningError,
)


class TestHierarchy:
    """All Hermes errors must inherit from HermesError so callers can catch broadly."""

    @pytest.mark.parametrize(
        "exc_cls",
        [
            ConfigurationError,
            BinanceError,
            BinanceAPIError,
            RateLimitError,
            OrderError,
            SigningError,
        ],
    )
    def test_inherits_from_hermes_error(self, exc_cls):
        assert issubclass(exc_cls, HermesError)

    def test_hermes_error_inherits_from_builtin(self):
        # Sanity: HermesError must still be a real Exception so it propagates.
        assert issubclass(HermesError, Exception)

    def test_binance_specific_errors_inherit_from_binance_error(self):
        # Anything related to Binance must catch under BinanceError too.
        assert issubclass(BinanceAPIError, BinanceError)
        assert issubclass(RateLimitError, BinanceError)
        assert issubclass(OrderError, BinanceError)
        assert issubclass(SigningError, BinanceError)

    def test_rate_limit_is_a_kind_of_api_error(self):
        # Rate-limit responses come from the API, so RateLimitError should be
        # catchable as BinanceAPIError.
        assert issubclass(RateLimitError, BinanceAPIError)


class TestBinanceAPIError:
    """The only error with a non-trivial constructor."""

    def test_stores_code_message_and_http_status(self):
        err = BinanceAPIError(code=-1121, message="Invalid symbol.", http_status=400)
        assert err.code == -1121
        assert err.message == "Invalid symbol."
        assert err.http_status == 400

    def test_str_includes_all_fields(self):
        err = BinanceAPIError(code=-2010, message="Insufficient balance", http_status=400)
        text = str(err)
        # Don't pin the exact format; assert the important pieces are present.
        assert "-2010" in text
        assert "Insufficient balance" in text
        assert "400" in text

    def test_http_status_defaults_to_zero_when_omitted(self):
        # The signature allows http_status=0 as a sentinel for "no HTTP context".
        err = BinanceAPIError(code=-1000, message="UNKNOWN")
        assert err.http_status == 0

    def test_is_raiseable_and_catchable_as_hermes_error(self):
        with pytest.raises(HermesError) as exc_info:
            raise BinanceAPIError(code=-1, message="boom", http_status=500)
        assert isinstance(exc_info.value, BinanceAPIError)


class TestRateLimitError:
    """RateLimitError uses the same constructor as BinanceAPIError."""

    def test_can_be_constructed_and_caught_as_api_error(self):
        with pytest.raises(BinanceAPIError):
            raise RateLimitError(code=-1003, message="Too many requests", http_status=429)