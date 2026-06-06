"""CE1~CE9: LC-EXEC-2 post_only routing unit tests. No NT process, no testnet."""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hermes.execution.events import PostOnlyRejected
from hermes.execution.exec_bridge import ExecBridge, _is_post_only_rejection


# ---------------------------------------------------------------------------
# CE1~CE5: _is_post_only_rejection unit tests
# ---------------------------------------------------------------------------

class TestIsPostOnlyRejection:
    def test_ce1_due_post_only_true_wins_regardless_of_reason(self):
        assert _is_post_only_rejection(True, "anything at all") is True

    def test_ce2_due_post_only_false_not_overridden_by_reason(self):
        assert _is_post_only_rejection(False, "post only order rejected") is False

    def test_ce3_none_fallback_would_immediately_match(self):
        assert _is_post_only_rejection(None, "Order would immediately match and take.") is True

    @pytest.mark.parametrize("reason", [
        "post-only not allowed",
        "POST_ONLY violation",
        "post only order",
    ])
    def test_ce4_none_fallback_three_substrings_case_insensitive(self, reason):
        assert _is_post_only_rejection(None, reason) is True

    def test_ce5_none_fallback_ordinary_rejection_not_matched(self):
        assert _is_post_only_rejection(None, "INSUFFICIENT_BALANCE") is False


# ---------------------------------------------------------------------------
# CE6~CE8: on_order_rejected routing behaviour
# ---------------------------------------------------------------------------

def _mock_rejected(due_post_only, reason="test reason", coid="O-1", ts_event=0):
    event = MagicMock()
    event.due_post_only = due_post_only
    event.reason = reason
    event.client_order_id.value = coid
    event.ts_event = ts_event
    return event


class TestOnOrderRejectedRouting:
    def _bridge(self):
        msgbus = MagicMock()
        bridge = ExecBridge(msgbus=msgbus, risk_guard=MagicMock())
        return bridge, msgbus

    def test_ce6_post_only_publishes_once_correct_topic_and_type(self):
        bridge, msgbus = self._bridge()
        bridge.on_order_rejected(_mock_rejected(True, "post only", "O-99", 999))
        assert msgbus.publish.call_count == 1
        topic, payload = msgbus.publish.call_args.args
        assert topic == "exec.post_only_rejected"
        assert isinstance(payload, PostOnlyRejected)

    def test_ce7_non_post_only_no_publish_log_still_called(self):
        bridge, msgbus = self._bridge()
        log = MagicMock()
        bridge._log = log
        bridge.on_order_rejected(_mock_rejected(False, "INSUFFICIENT_BALANCE"))
        msgbus.publish.assert_not_called()
        assert log.info.call_count == 1

    def test_ce8_post_only_rejected_fields_match_event(self):
        bridge, msgbus = self._bridge()
        bridge.on_order_rejected(_mock_rejected(True, "would immediately match", "O-42", 777))
        _, payload = msgbus.publish.call_args.args
        assert payload.client_order_id == "O-42"
        assert payload.reason == "would immediately match"
        assert payload.ts_event == 777


# ---------------------------------------------------------------------------
# CE9: neighbour zero-drift machine check
# ---------------------------------------------------------------------------

class TestNeighbourZeroDrift:
    def test_ce9_unchanged_sections_and_baseline_md5(self):
        src = Path("src/hermes/execution/exec_bridge.py").read_text()

        # __init__ LC-EXEC-4 guard verbatim
        assert "at most one may be non-null to prevent double-feeding RiskGuard (LC-EXEC-4)" in src

        # on_order_filled LC-EXEC-3 guard verbatim (L125 区段)
        assert "LC-EXEC-3: commission denominated in a currency other than the fill's" in src
        assert "if event.commission.currency.code != event.currency.code:" in src

        # on_order_canceled verbatim
        assert 'self._log.info("OrderCanceled: client_order_id=%s", event.client_order_id)' in src

        # four baseline md5s zero-drift
        baselines = {
            "src/hermes/execution/precision.py": "bb0308ce6cf0b50f5214e5d9819f2cc8",
            "src/hermes/execution/nt_translate.py": "a9cd0219475a99c6b1ea145d4e45f370",
            "src/hermes/execution/nt_submit.py": "db974054f08f4a15ee3357cd74a565cb",
            "src/hermes/risk/guard.py": "a0b23f0f9e6a1c910b06ddfd22489bf9",
        }
        for path, expected in baselines.items():
            actual = hashlib.md5(Path(path).read_bytes()).hexdigest()
            assert actual == expected, f"{path} md5 drifted: {actual} != {expected}"
