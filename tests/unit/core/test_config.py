"""Tests for the HermesConfig top-level configuration object.

Same isolation strategy as test_credentials: monkeypatch + _env_file=None
so we never accidentally read the dev's real .env. The model's responsibility
is narrow — load env vars, apply defaults, expose a credentials property —
so the tests stay short.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hermes.core.config import HermesConfig
from hermes.exchanges.binance_credentials import (
    BinanceCredentials,
    BinanceEnvironment,
)


# --- Fixtures -----------------------------------------------------------------

@pytest.fixture
def clean_env(monkeypatch):
    """Remove every HERMES_* and BINANCE_* var so tests see a blank environment."""
    for var in (
        "HERMES_ENV", "HERMES_TRADING_SYMBOL",
        "HERMES_LOG_LEVEL", "HERMES_LOG_DIR",
        "BINANCE_MAINNET_API_KEY", "BINANCE_MAINNET_API_SECRET",
        "BINANCE_TESTNET_API_KEY", "BINANCE_TESTNET_API_SECRET",
        "BINANCE_DEMO_API_KEY", "BINANCE_DEMO_API_SECRET",
    ):
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def _make_cfg() -> HermesConfig:
    """Build a config that ignores any real .env on disk."""
    return HermesConfig(_env_file=None)


# --- Defaults ------------------------------------------------------------------

class TestDefaults:
    """With no env vars set, every field should fall back to a safe default."""

    def test_env_defaults_to_testnet(self, clean_env):
        # Critical safety default: starting Hermes with a blank .env must NEVER
        # accidentally hit mainnet.
        cfg = _make_cfg()
        assert cfg.env == BinanceEnvironment.TESTNET

    def test_trading_symbol_defaults_to_solusdt(self, clean_env):
        cfg = _make_cfg()
        assert cfg.trading_symbol == "SOLUSDT"

    def test_log_level_defaults_to_info(self, clean_env):
        cfg = _make_cfg()
        assert cfg.log_level == "INFO"

    def test_log_dir_defaults_to_logs_path(self, clean_env):
        cfg = _make_cfg()
        assert cfg.log_dir == Path("logs")
        assert isinstance(cfg.log_dir, Path)


# --- Environment variable overrides --------------------------------------------

class TestEnvOverrides:
    """Each field can be overridden via its HERMES_* env var."""

    def test_env_can_be_set_to_mainnet(self, clean_env):
        clean_env.setenv("HERMES_ENV", "mainnet")
        cfg = _make_cfg()
        assert cfg.env == BinanceEnvironment.MAINNET

    def test_env_can_be_set_to_demo(self, clean_env):
        clean_env.setenv("HERMES_ENV", "demo")
        cfg = _make_cfg()
        assert cfg.env == BinanceEnvironment.DEMO

    def test_env_values_are_case_sensitive(self, clean_env):
        # Pydantic enum validation is case-sensitive for VALUES (the env-var
        # NAME is matched case-insensitively via SettingsConfigDict, but the
        # value 'TESTNET' vs 'testnet' is enforced strictly). This is the
        # intended behaviour: failing loud on uppercase typos prevents
        # subtle config drift between environments.
        import pydantic
        clean_env.setenv("HERMES_ENV", "TESTNET")
        with pytest.raises(pydantic.ValidationError):
            _make_cfg()

    def test_trading_symbol_override(self, clean_env):
        clean_env.setenv("HERMES_TRADING_SYMBOL", "BTCUSDT")
        cfg = _make_cfg()
        assert cfg.trading_symbol == "BTCUSDT"

    def test_log_level_override(self, clean_env):
        clean_env.setenv("HERMES_LOG_LEVEL", "DEBUG")
        cfg = _make_cfg()
        assert cfg.log_level == "DEBUG"

    def test_log_dir_override_returns_path(self, clean_env):
        clean_env.setenv("HERMES_LOG_DIR", "/var/log/hermes")
        cfg = _make_cfg()
        assert cfg.log_dir == Path("/var/log/hermes")
        assert isinstance(cfg.log_dir, Path)


# --- Credentials property ------------------------------------------------------

class TestCredentialsProperty:
    """`.credentials` should hand back a BinanceCredentials view of the same env."""

    def test_returns_binance_credentials_instance(self, clean_env):
        cfg = _make_cfg()
        creds = cfg.credentials
        assert isinstance(creds, BinanceCredentials)

    def test_credentials_pick_up_env_vars(self, clean_env):
        # End-to-end: set BINANCE_TESTNET_* and confirm we can read them back
        # through the cfg.credentials accessor.
        clean_env.setenv("BINANCE_TESTNET_API_KEY", "wired_key")
        clean_env.setenv("BINANCE_TESTNET_API_SECRET", "wired_secret")
        # The property constructs a fresh BinanceCredentials each access, and
        # by default it WILL try to load `.env`. To keep this test hermetic we
        # rely on the fact that the testnet vars we set above are read from
        # the process environment, which takes precedence over .env contents
        # for the keys we set.
        cfg = _make_cfg()
        key, secret = cfg.credentials.get_key_pair(BinanceEnvironment.TESTNET)
        assert key == "wired_key"
        assert secret == "wired_secret"

    def test_credentials_is_a_property_not_a_field(self, clean_env):
        # Guard against a refactor that turns this into a stored field — we
        # want it lazy so SecretStr values don't get copied onto HermesConfig.
        cfg = _make_cfg()
        descriptor = type(cfg).__dict__.get("credentials")
        assert isinstance(descriptor, property)


# --- from_env constructor ------------------------------------------------------

class TestFromEnv:
    """from_env() is the canonical entry point used by production code."""

    def test_returns_hermes_config_instance(self, clean_env):
        cfg = HermesConfig.from_env()
        assert isinstance(cfg, HermesConfig)

    def test_from_env_picks_up_env_vars(self, clean_env):
        clean_env.setenv("HERMES_TRADING_SYMBOL", "ETHUSDT")
        clean_env.setenv("HERMES_LOG_LEVEL", "WARNING")
        cfg = HermesConfig.from_env()
        assert cfg.trading_symbol == "ETHUSDT"
        assert cfg.log_level == "WARNING"


# --- Extra env vars are tolerated ---------------------------------------------

class TestExtraVarsIgnored:
    """`extra='ignore'` in SettingsConfigDict means unrelated env vars don't break us."""

    def test_unrelated_env_var_does_not_raise(self, clean_env):
        # BINANCE_* vars are unrelated to HermesConfig — they live on
        # BinanceCredentials. Setting them must not cause a ValidationError here.
        clean_env.setenv("BINANCE_TESTNET_API_KEY", "x")
        clean_env.setenv("BINANCE_TESTNET_API_SECRET", "y")
        clean_env.setenv("SOME_RANDOM_VAR", "z")
        # If extra='forbid' were set by mistake, this would raise.
        _make_cfg()