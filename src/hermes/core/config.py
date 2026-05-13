"""Top-level Hermes AI v6 configuration.

This module wires together all environment-driven settings for the system.
It loads values from `.env` via pydantic-settings and exposes them through a
single `HermesConfig` model that the rest of the codebase imports.

Design rules:
    * One config object per process, constructed at startup from `from_env()`.
    * Never read os.environ directly anywhere else. Always go through this.
    * Credentials live in `BinanceCredentials` (separate model) so we can
      pass them around without dragging unrelated config along.
    * Default environment is TESTNET. Switching to MAINNET requires an
      explicit `HERMES_ENV=mainnet` in `.env` — no accidents.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from hermes.exchanges.binance_credentials import (
    BinanceCredentials,
    BinanceEnvironment,
)


class HermesConfig(BaseSettings):
    """Top-level runtime configuration for Hermes AI v6.

    Loaded from environment variables (and `.env` file). All env vars are
    prefixed `HERMES_` so they don't collide with other tooling.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",       # ignore unrelated keys (BINANCE_*, etc.)
        case_sensitive=False,
    )

    # --- Trading environment --------------------------------------------------

    env: BinanceEnvironment = Field(
        default=BinanceEnvironment.TESTNET,
        alias="HERMES_ENV",
        description="Active Binance environment: mainnet / testnet / demo. "
                    "Defaults to TESTNET so accidental starts never trade real money.",
    )

    trading_symbol: str = Field(
        default="SOLUSDT",
        alias="HERMES_TRADING_SYMBOL",
        description="Primary trading pair. v6 focuses on SOL.",
    )

    # --- Logging --------------------------------------------------------------

    log_level: str = Field(
        default="INFO",
        alias="HERMES_LOG_LEVEL",
        description="Root log level: DEBUG / INFO / WARNING / ERROR.",
    )

    log_dir: Path = Field(
        default=Path("logs"),
        alias="HERMES_LOG_DIR",
        description="Directory for structured log files. Relative paths resolve "
                    "against the project root.",
    )

    # --- Credentials accessor -------------------------------------------------

    @property
    def credentials(self) -> BinanceCredentials:
        """Lazily construct a BinanceCredentials view of the same .env file.

        Kept as a property (not a field) so we don't deep-copy SecretStr
        values onto this object — fewer surfaces that could log keys by
        accident.
        """
        return BinanceCredentials()

    # --- Convenience constructors --------------------------------------------

    @classmethod
    def from_env(cls) -> "HermesConfig":
        """Build the config from .env / environment. The canonical entry point."""
        return cls()