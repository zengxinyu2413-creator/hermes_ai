"""D2: CLI unit tests — Click runner, all network/node mocked, no testnet connection."""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from hermes.cli import _parse_instrument_limits, main

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


def _mock_exchange_info_response(symbol: str = "ETHUSDT") -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {
        "symbols": [{"symbol": symbol, "filters": _ETHUSDT_FILTERS}]
    }
    return mock_resp


class TestParseInstrumentLimits:
    def test_price_tick_from_filter(self) -> None:
        limits = _parse_instrument_limits(_ETHUSDT_FILTERS)
        assert limits.price_tick == Decimal("0.01000000")

    def test_qty_step_from_filter(self) -> None:
        limits = _parse_instrument_limits(_ETHUSDT_FILTERS)
        assert limits.qty_step == Decimal("0.00010000")

    def test_min_notional_from_filter(self) -> None:
        limits = _parse_instrument_limits(_ETHUSDT_FILTERS)
        assert limits.min_notional == Decimal("5.00000000")

    def test_apply_min_to_market(self) -> None:
        limits = _parse_instrument_limits(_ETHUSDT_FILTERS)
        assert limits.apply_min_to_market is True

    def test_default_bid_multiplier_when_no_percent_price(self) -> None:
        limits = _parse_instrument_limits(_ETHUSDT_FILTERS)
        assert limits.bid_multiplier_up == Decimal("5")

    def test_percent_price_by_side_parsed_when_present(self) -> None:
        filters_with_pps = [
            *_ETHUSDT_FILTERS,
            {
                "filterType": "PERCENT_PRICE_BY_SIDE",
                "bidMultiplierUp": "1.2",
                "bidMultiplierDown": "0.8",
                "askMultiplierUp": "1.2",
                "askMultiplierDown": "0.8",
            },
        ]
        limits = _parse_instrument_limits(filters_with_pps)
        assert limits.bid_multiplier_up == Decimal("1.2")
        assert limits.ask_multiplier_down == Decimal("0.8")


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


class TestTradeLiveLiveWiring:
    """Verify params correctly passed in and add_strategy called."""

    def _invoke_live(self, extra_args: list[str] | None = None) -> tuple[MagicMock, MagicMock]:
        """Invoke trade-live with mocked node/httpx; return (mock_node, added_strategy)."""
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
            patch("hermes.cli.BinanceSpotInstrumentProvider"),
            patch("hermes.cli.BinanceHttpClient"),
            patch("httpx.get", return_value=_mock_exchange_info_response()),
        ):
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
