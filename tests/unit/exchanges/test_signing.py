"""Tests for the HMAC-SHA256 signing module.

The most important test is `test_official_binance_vector` — Binance publishes
an exact (secret, query, signature) triple in their API docs. If that one
passes, the implementation is provably correct against their reference, and
we know the live API will accept our signatures.
"""
from __future__ import annotations

import pytest

from hermes.exchanges._signing import sign


class TestOfficialBinanceVector:
    """The canonical example from Binance's own API documentation.

    Source: https://binance-docs.github.io/apidocs/spot/en/#signed-trade-user_data-and-margin-endpoint-security

    Inputs:
        secret  = "NhqPtmdSJYdKjVHjA7PZj4Mge3R5YNiP1e3UZjInClVN65XAbvqqM6A7H5fATj0j"
        query   = "symbol=LTCBTC&side=BUY&type=LIMIT&timeInForce=GTC&quantity=1
                   &price=0.1&recvWindow=5000&timestamp=1499827319559"

    Expected signature:
        "c8db56825ae71d6d79447849e617115f4a920fa2acdcab2b053c4b2838bd6b71"
    """

    SECRET = "NhqPtmdSJYdKjVHjA7PZj4Mge3R5YNiP1e3UZjInClVN65XAbvqqM6A7H5fATj0j"
    QUERY = (
        "symbol=LTCBTC&side=BUY&type=LIMIT&timeInForce=GTC&quantity=1"
        "&price=0.1&recvWindow=5000&timestamp=1499827319559"
    )
    EXPECTED = "c8db56825ae71d6d79447849e617115f4a920fa2acdcab2b053c4b2838bd6b71"

    def test_matches_official_signature(self):
        # If this fails, our signing is wrong — Binance will reject every call.
        assert sign(self.QUERY, self.SECRET) == self.EXPECTED

    def test_signature_is_64_lowercase_hex_chars(self):
        result = sign(self.QUERY, self.SECRET)
        assert len(result) == 64
        assert result == result.lower()
        # All characters must be hex digits.
        assert all(c in "0123456789abcdef" for c in result)


class TestDeterminism:
    """Same inputs must always produce the same output — non-negotiable for HMAC."""

    def test_same_inputs_same_output(self):
        secret = "abc123"
        query = "symbol=BTCUSDT&timestamp=1234567890"
        a = sign(query, secret)
        b = sign(query, secret)
        assert a == b

    def test_different_secret_different_output(self):
        query = "symbol=BTCUSDT&timestamp=1234567890"
        a = sign(query, "secret_one")
        b = sign(query, "secret_two")
        assert a != b

    def test_different_query_different_output(self):
        secret = "shared_secret"
        a = sign("symbol=BTCUSDT&timestamp=1", secret)
        b = sign("symbol=BTCUSDT&timestamp=2", secret)
        assert a != b

    def test_empty_query_is_signable(self):
        # Edge case: some Binance endpoints accept signed requests with no
        # business params, only `timestamp`. We don't want to special-case
        # empty inputs — signing "" must just work.
        result = sign("", "some_secret")
        assert len(result) == 64


class TestTypeSafety:
    """Refuse non-string inputs loudly to catch SecretStr / bytes mix-ups early."""

    def test_rejects_non_string_query(self):
        with pytest.raises(TypeError):
            sign(b"bytes_not_str", "secret")  # type: ignore[arg-type]

    def test_rejects_non_string_secret(self):
        with pytest.raises(TypeError):
            sign("query=1", b"bytes_secret")  # type: ignore[arg-type]

    def test_rejects_none_query(self):
        with pytest.raises(TypeError):
            sign(None, "secret")  # type: ignore[arg-type]

    def test_rejects_none_secret(self):
        with pytest.raises(TypeError):
            sign("query=1", None)  # type: ignore[arg-type]

    def test_rejects_secretstr_like_object(self):
        # Simulate what would happen if someone forgot to call
        # .get_secret_value() and passed a SecretStr in. We don't import
        # pydantic here — just check that a class whose repr is "SecretStr"
        # doesn't accidentally pass through.
        class FakeSecretStr:
            def __str__(self) -> str:
                return "**********"

        with pytest.raises(TypeError):
            sign("query=1", FakeSecretStr())  # type: ignore[arg-type]


class TestUnicodeSafety:
    """Just in case Binance ever returns non-ASCII in a signed payload."""

    def test_unicode_in_query(self):
        # Not realistic for Binance (their params are all ASCII), but the
        # function should not crash on UTF-8 input.
        result = sign("symbol=BTCUSDT&note=测试", "secret")
        assert len(result) == 64

    def test_unicode_in_secret(self):
        # Same: Binance secrets are ASCII, but UTF-8 should still work.
        result = sign("query=1", "secret_测试")
        assert len(result) == 64