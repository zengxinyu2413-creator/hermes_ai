"""Hermes-internal execution event types. No nautilus imports."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PostOnlyRejected:
    """Published on topic 'exec.post_only_rejected' when an order is rejected due to post-only."""

    client_order_id: str
    reason: str
    ts_event: int
