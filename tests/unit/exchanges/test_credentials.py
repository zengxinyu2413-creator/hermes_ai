"""Tests for the BinanceCredentials model.

We use monkeypatch to inject fake env vars, AND we point pydantic-settings at
a non-existent .env file via `_env_file=None`. This isolates tests from the
developer's real .env — otherwise a test that "passes" on the dev machine
might fail in CI just because CI has no real credentials.

Why we test:
* get_key_pair returns the right pair per environment
* missing credentials raise ConfigurationError (not silent None returns)
* has_credentials_for is the truthy / non-raising version of the above
* SecretStr round-trip works (we get a plain string back, not <SecretStr>)
"""
from __future__ import annotations

import pytest

from hermes.core.exceptions import ConfigurationError
from hermes.exchanges.binance_credentials import (
    BinanceCredentials,
    BinanceEnvironment,
)


# --- Fixtures -----------------------------------------------------------------

@pytest.fixture
def clean_env(monkeypatch):
    """Strip every BINANCE_* var so each test starts from a known blank slate."""
    for var in (
        "BINANCE_MAINNET_API_KEY", "BINANCE_MAINNET_API_SECRET",
        "BINANCE_TESTNET_API_KEY", "BINANCE_TESTNET_API_SECRET",
        "BINANCE_DEMO_API_KEY", "BINANCE_DEMO_API_SECRET",
    ):
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def _make_creds() -> BinanceCredentials:
    """Build a credentials object that ignores any real .env on disk.

    `_env_file=None` tells pydantic-settings: don't load any file, only
    consider the process environment (which our fixture controls).
    """
    return BinanceCredentials(_env_file=None)


# --- Enum -------------------------------------------------------------------

class TestBinanceEnvironment:
    def test_has_three_canonical_values(self):
        assert BinanceEnvironment.MAINNET.value == "mainnet"
        assert BinanceEnvironment.TESTNET.value == "testnet"
        assert BinanceEnvironment.DEMO.value == "demo"

    def test_is_a_str_enum_for_easy_serialization(self):
        # str-subclass means JSON/log serialization works without custom encoders.
        assert isinstance(BinanceEnvironment.TESTNET, str)
        assert BinanceEnvironment.TESTNET == "testnet"


# --- get_key_pair --------------------------------------------------------------

class TestGetKeyPair:
    def test_returns_testnet_pair(self, clean_env):
        clean_env.setenv("BINANCE_TESTNET_API_KEY", "test_key_abc")
        clean_env.setenv("BINANCE_TESTNET_API_SECRET", "test_secret_xyz")
        creds = _make_creds()
        key, secret = creds.get_key_pair(BinanceEnvironment.TESTNET)
        assert key == "test_key_abc"
        assert secret == "test_secret_xyz"

    def test_returns_mainnet_pair(self, clean_env):
        clean_env.setenv("BINANCE_MAINNET_API_KEY", "main_key_111")
        clean_env.setenv("BINANCE_MAINNET_API_SECRET", "main_secret_222")
        creds = _make_creds()
        key, secret = creds.get_key_pair(BinanceEnvironment.MAINNET)
        assert key == "main_key_111"
        assert secret == "main_secret_222"

    def test_returns_demo_pair(self, clean_env):
        clean_env.setenv("BINANCE_DEMO_API_KEY", "demo_key")
        clean_env.setenv("BINANCE_DEMO_API_SECRET", "demo_secret")
        creds = _make_creds()
        key, secret = creds.get_key_pair(BinanceEnvironment.DEMO)
        assert key == "demo_key"
        assert secret == "demo_secret"

    def test_returns_plain_strings_not_secretstr_wrappers(self, clean_env):
        # If someone forgot to .get_secret_value(), this guards against logging
        # "<SecretStr>" instead of the actual key.
        clean_env.setenv("BINANCE_TESTNET_API_KEY", "plain_key")
        clean_env.setenv("BINANCE_TESTNET_API_SECRET", "plain_secret")
        creds = _make_creds()
        key, secret = creds.get_key_pair(BinanceEnvironment.TESTNET)
        assert isinstance(key, str)
        assert isinstance(secret, str)
        assert "SecretStr" not in key
        assert "SecretStr" not in secret


# --- Missing credentials -------------------------------------------------------

class TestMissingCredentials:
    def test_missing_key_raises_configuration_error(self, clean_env):
        # Secret present, key missing
        clean_env.setenv("BINANCE_TESTNET_API_SECRET", "only_secret")
        creds = _make_creds()
        with pytest.raises(ConfigurationError):
            creds.get_key_pair(BinanceEnvironment.TESTNET)

    def test_missing_secret_raises_configuration_error(self, clean_env):
        # Key present, secret missing
        clean_env.setenv("BINANCE_TESTNET_API_KEY", "only_key")
        creds = _make_creds()
        with pytest.raises(ConfigurationError):
            creds.get_key_pair(BinanceEnvironment.TESTNET)

    def test_completely_missing_raises_configuration_error(self, clean_env):
        creds = _make_creds()
        with pytest.raises(ConfigurationError):
            creds.get_key_pair(BinanceEnvironment.MAINNET)

    def test_error_message_mentions_the_environment(self, clean_env):
        # Helpful diagnostics: the error should tell the operator WHICH env
        # is broken, since they typically have 2-3 sets of keys.
        creds = _make_creds()
        with pytest.raises(ConfigurationError) as exc_info:
            creds.get_key_pair(BinanceEnvironment.DEMO)
        # Be lenient on exact wording; just check "demo" surfaces somewhere.
        assert "demo" in str(exc_info.value).lower()


# --- has_credentials_for -------------------------------------------------------

class TestHasCredentialsFor:
    def test_true_when_both_key_and_secret_present(self, clean_env):
        clean_env.setenv("BINANCE_TESTNET_API_KEY", "k")
        clean_env.setenv("BINANCE_TESTNET_API_SECRET", "s")
        creds = _make_creds()
        assert creds.has_credentials_for(BinanceEnvironment.TESTNET) is True

    def test_false_when_key_missing(self, clean_env):
        clean_env.setenv("BINANCE_TESTNET_API_SECRET", "s")
        creds = _make_creds()
        assert creds.has_credentials_for(BinanceEnvironment.TESTNET) is False

    def test_false_when_secret_missing(self, clean_env):
        clean_env.setenv("BINANCE_TESTNET_API_KEY", "k")
        creds = _make_creds()
        assert creds.has_credentials_for(BinanceEnvironment.TESTNET) is False

    def test_false_when_nothing_set(self, clean_env):
        creds = _make_creds()
        assert creds.has_credentials_for(BinanceEnvironment.MAINNET) is False

    def test_does_not_raise_when_missing(self, clean_env):
        # Contract: has_credentials_for is the *check* version — it must
        # never raise, whereas get_key_pair *will*.
        creds = _make_creds()
        # If this raises, the test fails. No assertion needed beyond that.
        creds.has_credentials_for(BinanceEnvironment.DEMO)

    def test_independent_environments(self, clean_env):
        # Only testnet configured; mainnet/demo should report False.
        clean_env.setenv("BINANCE_TESTNET_API_KEY", "k")
        clean_env.setenv("BINANCE_TESTNET_API_SECRET", "s")
        creds = _make_creds()
        assert creds.has_credentials_for(BinanceEnvironment.TESTNET) is True
        assert creds.has_credentials_for(BinanceEnvironment.MAINNET) is False
        assert creds.has_credentials_for(BinanceEnvironment.DEMO) is False