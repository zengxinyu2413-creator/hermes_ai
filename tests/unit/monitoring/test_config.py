"""CBP4: TelegramConfig mirrors BinanceCredentials style exactly."""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest
from pydantic import SecretStr, ValidationError


def test_bot_token_is_secret_str() -> None:
    """CBP4: bot_token field annotation is SecretStr (no accidental logging)."""
    from hermes.monitoring.config import TelegramConfig

    assert TelegramConfig.model_fields["bot_token"].annotation is SecretStr


def test_missing_token_raises_validation_error() -> None:
    """CBP4: bot_token has no default — omitting it raises ValidationError."""
    from hermes.monitoring.config import TelegramConfig

    with patch.dict("os.environ", {"HERMES_TELEGRAM_CHAT_ID": "123"}, clear=False):
        # Remove token if accidentally present in env
        import os
        env = {k: v for k, v in os.environ.items() if k != "HERMES_TELEGRAM_BOT_TOKEN"}
        with patch.dict("os.environ", env, clear=True), pytest.raises(ValidationError):
            TelegramConfig(_env_file=None)  # type: ignore[call-arg]


def test_config_from_env_vars() -> None:
    """CBP4: TelegramConfig reads from HERMES_TELEGRAM_* env vars."""
    from hermes.monitoring.config import TelegramConfig

    env = {
        "HERMES_TELEGRAM_BOT_TOKEN": "secret-bot-token",
        "HERMES_TELEGRAM_CHAT_ID": "99887766",
    }
    with patch.dict("os.environ", env, clear=True):
        cfg = TelegramConfig(_env_file=None)  # type: ignore[call-arg]
        assert cfg.bot_token.get_secret_value() == "secret-bot-token"
        assert cfg.chat_id == "99887766"


def test_poll_interval_default() -> None:
    """CBP4: poll_interval_s defaults to 30."""
    from hermes.monitoring.config import TelegramConfig

    env = {
        "HERMES_TELEGRAM_BOT_TOKEN": "tok",
        "HERMES_TELEGRAM_CHAT_ID": "1",
    }
    with patch.dict("os.environ", env, clear=True):
        cfg = TelegramConfig(_env_file=None)  # type: ignore[call-arg]
        assert cfg.poll_interval_s == 30


def test_threshold_defaults() -> None:
    """CBP4: Operational thresholds have sensible defaults."""
    from hermes.monitoring.config import TelegramConfig

    env = {
        "HERMES_TELEGRAM_BOT_TOKEN": "tok",
        "HERMES_TELEGRAM_CHAT_ID": "1",
    }
    with patch.dict("os.environ", env, clear=True):
        cfg = TelegramConfig(_env_file=None)  # type: ignore[call-arg]
        assert cfg.clock_drift_warn_ms == 1000
        assert cfg.price_move_warn_pct == Decimal("5.0")
        assert cfg.symbol == "SOLUSDT"


def test_model_config_mirrors_binance_credentials() -> None:
    """CBP4: model_config has env_file, extra=ignore, case_sensitive=False."""
    from hermes.monitoring.config import TelegramConfig

    mc = TelegramConfig.model_config
    assert mc.get("env_file") == ".env"
    assert mc.get("extra") == "ignore"
    assert mc.get("case_sensitive") is False
