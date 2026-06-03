"""Tests for trade-live CLI wiring (b3b, X-path).

Safety invariants locked by these tests:
  A  exec config environment == TESTNET  (omission → mainnet)
  B  max_retries == 0                    (zero retries on order submission)
  C  --dry does not construct TradingNode (zero network, zero NT kernel init)
  D  credentials not in config           (api_key / api_secret are None)
  E  factory registered as "BINANCE"
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from nautilus_trader.adapters.binance import BinanceLiveExecClientFactory
from nautilus_trader.adapters.binance.common.enums import BinanceEnvironment

from hermes.cli import trade_live

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ETHUSDT_FILTERS = [
    {"filterType": "PRICE_FILTER", "minPrice": "0.01", "maxPrice": "1000000.00", "tickSize": "0.01"},
    {"filterType": "LOT_SIZE", "minQty": "0.0001", "maxQty": "9000.00", "stepSize": "0.0001"},
    {"filterType": "NOTIONAL", "minNotional": "5.00", "applyMinToMarket": True},
]


def _make_node_mock() -> MagicMock:
    node = MagicMock()
    node.build = MagicMock()
    node.run = MagicMock()
    node.add_exec_client_factory = MagicMock()
    return node


def _mock_exchange_resp() -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"symbols": [{"symbol": "ETHUSDT", "filters": _ETHUSDT_FILTERS}]}
    return resp


def _invoke_live(captured: dict) -> tuple[object, MagicMock]:
    """Invoke trade_live on the live path (no --dry); TradingNode + httpx fully mocked."""
    node_mock = _make_node_mock()

    def fake_node(config=None, loop=None) -> MagicMock:
        captured["config"] = config
        return node_mock

    with (
        patch("hermes.cli.TradingNode", side_effect=fake_node),
        patch("httpx.get", return_value=_mock_exchange_resp()),
    ):
        result = CliRunner().invoke(trade_live, ["--price", "1300", "--qty", "0.0039"])
    return result, node_mock


# ---------------------------------------------------------------------------
# A: environment must be TESTNET
# ---------------------------------------------------------------------------

def test_config_environment_is_testnet() -> None:
    """Omitting environment defaults to LIVE (mainnet) — must be explicit TESTNET."""
    captured: dict = {}
    _invoke_live(captured)
    assert captured["config"].exec_clients["BINANCE"].environment == BinanceEnvironment.TESTNET


# ---------------------------------------------------------------------------
# B: max_retries must be 0
# ---------------------------------------------------------------------------

def test_max_retries_zero() -> None:
    """Order submission must not be retried."""
    captured: dict = {}
    _invoke_live(captured)
    assert captured["config"].exec_clients["BINANCE"].max_retries == 0


# ---------------------------------------------------------------------------
# C: --dry must not construct TradingNode
# ---------------------------------------------------------------------------

def test_dry_does_not_construct_node() -> None:
    """--dry must return before TradingNode is instantiated — zero NT kernel init."""
    with patch("hermes.cli.TradingNode") as mock_node_cls:
        result = CliRunner().invoke(trade_live, ["--dry"])

    assert result.exit_code == 0
    assert result.exception is None
    mock_node_cls.assert_not_called()
    assert "testnet" in result.output.lower()
    assert "dry" in result.output.lower()


# ---------------------------------------------------------------------------
# D: credentials must not be stored in config
# ---------------------------------------------------------------------------

def test_config_no_plaintext_credentials() -> None:
    """api_key and api_secret must be None in config (read from env at runtime)."""
    captured: dict = {}
    _invoke_live(captured)
    exec_cfg = captured["config"].exec_clients["BINANCE"]
    assert exec_cfg.api_key is None
    assert exec_cfg.api_secret is None


# ---------------------------------------------------------------------------
# E: factory must be registered as "BINANCE"
# ---------------------------------------------------------------------------

def test_factory_registered() -> None:
    """add_exec_client_factory must be called with ("BINANCE", BinanceLiveExecClientFactory)."""
    captured: dict = {}
    _, node_mock = _invoke_live(captured)
    node_mock.add_exec_client_factory.assert_called_once_with(
        "BINANCE", BinanceLiveExecClientFactory
    )
