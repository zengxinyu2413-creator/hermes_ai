"""HMAC-SHA256 signing for authenticated Binance REST requests.

Kept as a small, pure-function module so it can be tested without any network
or pydantic dependencies. The caller is responsible for:

1. Building the query string in the right order (Binance signs the exact
   bytes you send, including the `timestamp` and `recvWindow` params).
2. URL-encoding before signing (we sign the encoded string, not the raw dict).
3. Pulling the plaintext secret out of SecretStr (this module deliberately
   does not import pydantic — keeps the dependency graph shallow).

Reference: https://binance-docs.github.io/apidocs/spot/en/#signed-trade-user_data-and-margin-endpoint-security
"""
from __future__ import annotations

import hashlib
import hmac


def sign(query_string: str, secret: str) -> str:
    """Compute the HMAC-SHA256 hex digest of `query_string` using `secret`.

    Args:
        query_string: The URL-encoded query (no leading '?', no trailing '&').
            Example: "symbol=SOLUSDT&side=BUY&timestamp=1499827319559".
        secret: Binance API secret as a plain string. Caller pulls this out of
            SecretStr.

    Returns:
        Lowercase hex digest string (64 chars). This goes in the request as
        `&signature=<digest>`.

    Raises:
        TypeError: If either argument is not a string. We refuse to silently
            stringify a SecretStr — that would produce "**********" and the
            mistake would only surface at runtime when Binance returns
            -1022 "Signature for this request is not valid."
    """
    if not isinstance(query_string, str):
        raise TypeError(
            f"query_string must be str, got {type(query_string).__name__}"
        )
    if not isinstance(secret, str):
        raise TypeError(
            f"secret must be str (plain text, not SecretStr), got "
            f"{type(secret).__name__}"
        )

    return hmac.new(
        key=secret.encode("utf-8"),
        msg=query_string.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()