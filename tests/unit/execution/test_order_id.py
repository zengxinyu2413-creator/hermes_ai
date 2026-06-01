"""Tests for OrderIdFactory — CR12 T1~T6."""

from __future__ import annotations

import re
from unittest.mock import MagicMock

from nautilus_trader.model.identifiers import ClientOrderId

from hermes.execution.order_id import OrderIdFactory

_PATTERN = re.compile(r"^[A-Za-z0-9]+-\d+-[A-Za-z0-9_-]{6,}$")


class TestOrderIdFactory:
    def test_t1_1000_unique(self):
        factory = OrderIdFactory()
        ids = [factory.generate().value for _ in range(1000)]
        assert len(set(ids)) == 1000

    def test_t2_returns_client_order_id(self):
        coid = OrderIdFactory().generate()
        assert isinstance(coid, ClientOrderId)

    def test_t3_format_regex(self):
        factory = OrderIdFactory()
        for _ in range(50):
            coid = factory.generate()
            assert _PATTERN.match(coid.value), f"format mismatch: {coid.value!r}"

    def test_t4_register_and_is_seen_positive_negative(self):
        factory = OrderIdFactory()
        coid = factory.generate()
        # generate() auto-registers
        assert factory.is_seen(coid)
        # unregistered ID is not seen
        assert not factory.is_seen(ClientOrderId("HRM-0-notregistered"))

    def test_t5_seed_seen_is_tracked_and_generate_differs(self):
        seed = {"HRM-X-Y"}
        factory = OrderIdFactory(seen=seed)
        coid = factory.generate()
        assert coid.value != "HRM-X-Y"
        assert factory.is_seen(coid)
        # seed entry is also seen
        assert factory.is_seen(ClientOrderId("HRM-X-Y"))

    def test_t6_mock_clock_same_ms_nonce_still_unique(self):
        clock = MagicMock()
        clock.timestamp_ns.return_value = 1_000_000_000  # always same epoch_ms
        factory = OrderIdFactory(clock=clock)
        ids = [factory.generate().value for _ in range(200)]
        assert len(set(ids)) == 200
