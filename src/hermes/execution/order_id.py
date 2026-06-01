"""OrderIdFactory: unique ClientOrderId generation with in-memory dedup."""

from __future__ import annotations

import secrets
import time
from typing import Optional, Set

from nautilus_trader.model.identifiers import ClientOrderId

from hermes.execution.seen_store import SeenStore


class OrderIdFactory:
    """
    Generates unique ClientOrderId values for order submission.

    In scope: generating unique client-side order IDs with collision resistance,
    idempotency tracking via an in-memory seen set, optional clock injection
    for deterministic unit testing, optional SeenStore injection for
    cross-restart persistence.

    LC-EXEC-1: When no store is provided, the seen set is in-memory only;
    duplicate IDs from prior process sessions are not detected.  Pass a
    SeenStore implementation (e.g. FileStore) to enable persistence.
    """

    def __init__(
        self,
        prefix: str = "HRM",
        clock=None,
        seen: Optional[Set[str]] = None,
        store: Optional[SeenStore] = None,
    ) -> None:
        self._prefix = prefix
        self._clock = clock
        self._store = store
        if store is not None:
            persisted = store.load()
            seed = set(seen) if seen is not None else set()
            self._seen: Set[str] = persisted | seed
        else:
            self._seen = set(seen) if seen is not None else set()

    def _epoch_ms(self) -> int:
        if self._clock is not None:
            return self._clock.timestamp_ns() // 1_000_000
        return time.time_ns() // 1_000_000

    def generate(self) -> ClientOrderId:
        """Generate a new unique ClientOrderId and register it in the seen set."""
        # secrets.token_urlsafe(6) → 8 URL-safe base64 chars; collision-resistant
        # even across clock rollback or same-millisecond calls.
        nonce = secrets.token_urlsafe(6)
        raw = f"{self._prefix}-{self._epoch_ms()}-{nonce}"
        coid = ClientOrderId(raw)
        self._seen.add(raw)
        if self._store is not None:
            self._store.add(raw)
        return coid

    def is_seen(self, coid: ClientOrderId) -> bool:
        """Return True if this ClientOrderId has been registered in the seen set."""
        return coid.value in self._seen

    def register(self, coid: ClientOrderId) -> None:
        """Register an externally-generated ClientOrderId in the seen set."""
        self._seen.add(coid.value)
        if self._store is not None:
            self._store.add(coid.value)
