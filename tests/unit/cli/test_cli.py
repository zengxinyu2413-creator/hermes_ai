"""D2: CLI unit tests — Click runner, all network/node mocked, no testnet connection."""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from hermes.cli import main

_ETHUSDT_FILTERS = [
    {
        "filterType": "PRICE_FILTER",
        "minPrice": "0.01000000",
        "maxPrice": "1000000.00000000",
        "tickSize": "0.01000000",
    },
    {
        "filterType": "LOT_SIZE",
        "minQty": "0.00010000",
        "maxQty": "9000.00000000",
        "stepSize": "0.00010000",
    },
    {
        "filterType": "NOTIONAL",
        "minNotional": "5.00000000",
        "applyMinToMarket": True,
    },
]


class TestTradeLiveDry:
    def test_dry_exits_zero(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["trade-live", "--dry"])
        assert result.exit_code == 0

    def test_dry_prints_testnet(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["trade-live", "--dry"])
        assert "TESTNET" in result.output.upper()

    def test_dry_prints_max_retries_zero(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["trade-live", "--dry"])
        assert "max_retries=0" in result.output

    def test_dry_with_all_params_exits_zero(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["trade-live", "--dry", "--symbol", "ETHUSDT",
             "--side", "BUY", "--price", "1300", "--qty", "0.0039"],
        )
        assert result.exit_code == 0

    def test_dry_no_network_call(self) -> None:
        runner = CliRunner()
        with patch("httpx.get") as mock_get:
            runner.invoke(main, ["trade-live", "--dry"])
            mock_get.assert_not_called()


class TestTradeLiveLiveParams:
    def test_missing_price_errors(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["trade-live", "--qty", "0.0039"])
        assert result.exit_code != 0

    def test_missing_qty_errors(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["trade-live", "--price", "1300"])
        assert result.exit_code != 0

    def test_missing_both_errors(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["trade-live"])
        assert result.exit_code != 0


class _FakeMoney:
    def __init__(self, value: str) -> None:
        self._decimal = Decimal(value)

    def as_decimal(self) -> Decimal:
        return self._decimal


def _fake_live_instrument() -> MagicMock:
    """Build a fake NT instrument exposing the 7 direct attrs + .info["filters"]
    that nt_instrument_to_limits_from_info/nt_instrument_to_limits read.

    Values are parsed from the same _ETHUSDT_FILTERS dicts the deleted
    _parse_instrument_limits consumed — same Decimal value *and* precision —
    so the resulting InstrumentLimits, and therefore order_spec, stay
    numerically identical to the pre-refactor wiring (the wiring assertions
    below were tuned against that exact rounding output).
    """
    price_filter = next(f for f in _ETHUSDT_FILTERS if f["filterType"] == "PRICE_FILTER")
    lot_size_filter = next(f for f in _ETHUSDT_FILTERS if f["filterType"] == "LOT_SIZE")
    notional_filter = next(f for f in _ETHUSDT_FILTERS if f["filterType"] == "NOTIONAL")

    instrument = MagicMock()
    instrument.price_increment = Decimal(price_filter["tickSize"])
    instrument.size_increment = Decimal(lot_size_filter["stepSize"])
    instrument.min_quantity = Decimal(lot_size_filter["minQty"])
    instrument.max_quantity = Decimal(lot_size_filter["maxQty"])
    instrument.min_price = Decimal(price_filter["minPrice"])
    instrument.max_price = Decimal(price_filter["maxPrice"])
    instrument.min_notional = _FakeMoney(notional_filter["minNotional"])
    instrument.info = {
        "filters": [
            *_ETHUSDT_FILTERS,
            {
                "filterType": "PERCENT_PRICE_BY_SIDE",
                "bidMultiplierUp": "5",
                "bidMultiplierDown": "0.2",
                "askMultiplierUp": "5",
                "askMultiplierDown": "0.2",
            },
        ]
    }
    return instrument


class TestTradeLiveLiveWiring:
    """Verify params correctly passed in and add_strategy called."""

    def _invoke_live(self, extra_args: list[str] | None = None) -> tuple[MagicMock, MagicMock]:
        """Invoke trade-live with mocked node/provider; return (mock_node, added_strategy)."""
        mock_node = MagicMock()
        added = {}

        def capture_add_strategy(s: object) -> None:
            added["strategy"] = s
            # simulate accepted order so on_done is called → result populated
            if hasattr(s, "_on_done"):
                s._on_done("venue-order-999", None)

        mock_node.trader.add_strategy.side_effect = capture_add_strategy
        mock_node.run.return_value = None

        args = ["trade-live", "--symbol", "ETHUSDT", "--side", "BUY",
                "--price", "1300", "--qty", "0.0039"]
        if extra_args:
            args += extra_args

        runner = CliRunner()
        with (
            patch("hermes.cli.TradingNode", return_value=mock_node),
            patch("hermes.cli.BinanceLiveExecClientFactory"),
            patch("hermes.cli.BinanceSpotInstrumentProvider") as mock_provider_cls,
            patch("hermes.cli.BinanceHttpClient"),
        ):
            mock_provider_cls.return_value.find.return_value = _fake_live_instrument()
            result = runner.invoke(main, args)

        return mock_node, added.get("strategy"), result

    def test_add_strategy_called(self) -> None:
        mock_node, _strategy, _result = self._invoke_live()
        mock_node.trader.add_strategy.assert_called_once()

    def test_node_run_called(self) -> None:
        mock_node, _, _ = self._invoke_live()
        mock_node.run.assert_called_once()

    def test_node_build_called(self) -> None:
        mock_node, _, _ = self._invoke_live()
        mock_node.build.assert_called_once()

    def test_strategy_instrument_id(self) -> None:
        _, strategy, _ = self._invoke_live()
        assert strategy is not None
        assert strategy._instrument_id is not None

    def test_strategy_price_matches_param(self) -> None:
        from nautilus_trader.model.objects import Price

        _, strategy, _ = self._invoke_live()
        assert strategy is not None
        assert strategy._price == Price.from_str("1300.00")

    def test_strategy_quantity_matches_param(self) -> None:
        from nautilus_trader.model.objects import Quantity

        _, strategy, _ = self._invoke_live()
        assert strategy is not None
        assert strategy._quantity == Quantity.from_str("0.0039")

    def test_j2_output_printed(self) -> None:
        _, _, result = self._invoke_live()
        assert "J2 pre-submit" in result.output
        assert "ETHUSDT" in result.output
        assert "BUY" in result.output
        assert "1300" in result.output
        assert "0.0039" in result.output

    def test_accepted_result_printed(self) -> None:
        _, _, result = self._invoke_live()
        assert "ORDER ACCEPTED" in result.output
        assert "venue-order-999" in result.output
