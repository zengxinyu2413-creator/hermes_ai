"""Binance API credentials configuration.

Loads three sets of API keys from .env file:
- Mainnet:  Real trading on Binance Futures
- Testnet:  Free testnet (5000 USDT virtual balance)
- Demo:     Demo account (typically used with proxy for restricted regions)

Usage:
    from hermes.exchanges.binance_credentials import (
        BinanceCredentials,
        BinanceEnvironment,
    )

    creds = BinanceCredentials()  # auto-loads from .env
    api_key, api_secret = creds.get_key_pair(BinanceEnvironment.TESTNET)
"""
from enum import Enum

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from hermes.core.exceptions import ConfigurationError


class BinanceEnvironment(str, Enum):
    """Three operational modes for Binance API access."""

    MAINNET = "mainnet"
    TESTNET = "testnet"
    DEMO = "demo"


class BinanceCredentials(BaseSettings):
    """Three sets of Binance API credentials, loaded from .env file.

    All values are SecretStr to prevent accidental logging.
    Use .get_secret_value() to extract the actual key string.

    Missing credentials are not an error at load time; only when
    .get_key_pair(env) is called for an environment without keys.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # === Mainnet ===
    mainnet_api_key: SecretStr | None = Field(
        default=None,
        alias="BINANCE_MAINNET_API_KEY",
    )
    mainnet_api_secret: SecretStr | None = Field(
        default=None,
        alias="BINANCE_MAINNET_API_SECRET",
    )

    # === Testnet ===
    testnet_api_key: SecretStr | None = Field(
        default=None,
        alias="BINANCE_TESTNET_API_KEY",
    )
    testnet_api_secret: SecretStr | None = Field(
        default=None,
        alias="BINANCE_TESTNET_API_SECRET",
    )

    # === Demo ===
    demo_api_key: SecretStr | None = Field(
        default=None,
        alias="BINANCE_DEMO_API_KEY",
    )
    demo_api_secret: SecretStr | None = Field(
        default=None,
        alias="BINANCE_DEMO_API_SECRET",
    )

    def get_key_pair(self, env: BinanceEnvironment) -> tuple[str, str]:
        """Get (api_key, api_secret) for the given environment.

        Args:
            env: Which Binance environment to fetch credentials for.

        Returns:
            Tuple of (api_key, api_secret) as plain strings.

        Raises:
            ConfigurationError: if the requested environment has no
                credentials configured in .env.
        """
        env_to_keys = {
            BinanceEnvironment.MAINNET: (self.mainnet_api_key, self.mainnet_api_secret),
            BinanceEnvironment.TESTNET: (self.testnet_api_key, self.testnet_api_secret),
            BinanceEnvironment.DEMO: (self.demo_api_key, self.demo_api_secret),
        }

        api_key, api_secret = env_to_keys[env]

        if api_key is None or api_secret is None:
            raise ConfigurationError(
                f"Missing credentials for {env.value!r}. "
                f"Set BINANCE_{env.value.upper()}_API_KEY and "
                f"BINANCE_{env.value.upper()}_API_SECRET in .env"
            )

        return api_key.get_secret_value(), api_secret.get_secret_value()

    def has_credentials_for(self, env: BinanceEnvironment) -> bool:
        """Check if credentials exist for the given environment (no raise)."""
        try:
            self.get_key_pair(env)
            return True
        except ConfigurationError:
            return False