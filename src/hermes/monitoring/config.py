"""TelegramConfig — pydantic-settings config for the Hermes monitor bot."""
from __future__ import annotations

from decimal import Decimal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class TelegramConfig(BaseSettings):
    """Telegram bot + operational alert thresholds, loaded from .env.

    Mirrors BinanceCredentials model_config exactly (env_file, encoding,
    extra=ignore, case_sensitive=False).  bot_token has no default — a
    missing token raises ValidationError at construction time.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    bot_token: SecretStr = Field(alias="HERMES_TELEGRAM_BOT_TOKEN")
    chat_id: str = Field(alias="HERMES_TELEGRAM_CHAT_ID")
    poll_interval_s: int = Field(default=30, alias="HERMES_TELEGRAM_POLL_INTERVAL_S")

    # Operational alert thresholds
    clock_drift_warn_ms: int = Field(
        default=1000,
        alias="HERMES_TELEGRAM_CLOCK_DRIFT_WARN_MS",
    )
    price_move_warn_pct: Decimal = Field(
        default=Decimal("5.0"),
        alias="HERMES_TELEGRAM_PRICE_MOVE_WARN_PCT",
    )
    symbol: str = Field(default="SOLUSDT", alias="HERMES_TELEGRAM_SYMBOL")
