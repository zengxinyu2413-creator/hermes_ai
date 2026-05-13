"""Custom exception hierarchy for Hermes AI v6.

All Hermes errors inherit from HermesError. This makes catching
all Hermes-related exceptions easy:

    try:
        ...
    except HermesError as e:
        log.error("Hermes failed", error=e)

Specific exception types allow for targeted handling:

    try:
        client.create_order(...)
    except RateLimitError:
        # back off and retry
        ...
    except OrderError as e:
        # log and continue
        ...
"""


class HermesError(Exception):
    """Base exception for all Hermes errors."""


# === Configuration ===


class ConfigurationError(HermesError):
    """Configuration is invalid or required values are missing."""


# === Binance / Exchange ===


class BinanceError(HermesError):
    """Base exception for all Binance-related errors."""


class BinanceAPIError(BinanceError):
    """Binance API returned an error response.

    Attributes:
        code: Binance error code (negative integer, e.g. -1021).
        message: Human-readable error message from Binance.
        http_status: HTTP status code from the response.
    """

    def __init__(self, code: int, message: str, http_status: int = 0) -> None:
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(f"[{code}] {message} (HTTP {http_status})")


class RateLimitError(BinanceAPIError):
    """Binance rate limit exceeded (HTTP 429 or 418)."""


class OrderError(BinanceError):
    """Order placement, modification, or cancellation failed."""


class SigningError(BinanceError):
    """HMAC-SHA256 signing failed."""
