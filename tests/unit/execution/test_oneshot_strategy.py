"""D1: OneShotStrategy unit tests — all mock, no network, no NT plumbing."""
from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock, patch

from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity

from hermes.execution.oneshot_strategy import OneShotConfig, OneShotStrategy

_INSTRUMENT = "ETHUSDT.BINANCE"
_PRICE = "1300.00"
_QTY = "0.0039"


def _make_config(
    instrument: str = _INSTRUMENT,
    side: str = "BUY",
    price: str = _PRICE,
    qty: str = _QTY,
) -> OneShotConfig:
    return OneShotConfig(
        instrument_id_str=instrument,
        order_side_str=side,
        price_str=price,
        quantity_str=qty,
    )


def _make_strategy(
    config: OneShotConfig | None = None,
    on_done: MagicMock | None = None,
) -> tuple[OneShotStrategy, MagicMock, MagicMock]:
    """Return (strategy, on_done_mock, order_factory_mock).

    submit_order is set to a MagicMock instance attribute (Cython method is
    settable but rejects non-Order args; shadow it to allow MagicMock orders).
    order_factory PropertyMock is NOT active here — callers wrap on_start()
    with patch.object(OneShotStrategy, 'order_factory', ...) themselves.
    """
    if config is None:
        config = _make_config()
    if on_done is None:
        on_done = MagicMock()
    strategy = OneShotStrategy(config=config, on_done=on_done)
    strategy.submit_order = MagicMock()  # type: ignore[method-assign]
    mock_factory = MagicMock()
    return strategy, on_done, mock_factory


class TestOneShotConfig:
    def test_fields_stored(self) -> None:
        cfg = _make_config()
        assert cfg.instrument_id_str == _INSTRUMENT
        assert cfg.order_side_str == "BUY"
        assert cfg.price_str == _PRICE
        assert cfg.quantity_str == _QTY


class TestOneShotStrategyInit:
    def test_instrument_id_parsed(self) -> None:
        strategy, _, _ = _make_strategy()
        assert strategy._instrument_id == InstrumentId.from_str(_INSTRUMENT)

    def test_side_buy(self) -> None:
        strategy, _, _ = _make_strategy(_make_config(side="BUY"))
        assert strategy._order_side == OrderSide.BUY

    def test_side_sell(self) -> None:
        strategy, _, _ = _make_strategy(_make_config(side="SELL"))
        assert strategy._order_side == OrderSide.SELL

    def test_price_parsed(self) -> None:
        strategy, _, _ = _make_strategy()
        assert strategy._price == Price.from_str(_PRICE)

    def test_quantity_parsed(self) -> None:
        strategy, _, _ = _make_strategy()
        assert strategy._quantity == Quantity.from_str(_QTY)

    def test_submitted_false_initially(self) -> None:
        strategy, _, _ = _make_strategy()
        assert strategy._submitted is False

    def test_side_case_insensitive_lower(self) -> None:
        strategy, _, _ = _make_strategy(_make_config(side="buy"))
        assert strategy._order_side == OrderSide.BUY


class TestOnStart:
    """order_factory is a read-only Cython property — mock via PropertyMock."""

    def test_submit_order_called_exactly_once(self) -> None:
        strategy, _, mock_factory = _make_strategy()
        mock_order = MagicMock()
        mock_factory.limit.return_value = mock_order
        with patch.object(OneShotStrategy, "order_factory", new_callable=PropertyMock, return_value=mock_factory):
            strategy.on_start()
        strategy.submit_order.assert_called_once_with(mock_order)

    def test_submitted_flag_set_after_on_start(self) -> None:
        strategy, _, mock_factory = _make_strategy()
        mock_factory.limit.return_value = MagicMock()
        with patch.object(OneShotStrategy, "order_factory", new_callable=PropertyMock, return_value=mock_factory):
            strategy.on_start()
        assert strategy._submitted is True

    def test_order_factory_receives_correct_instrument_id(self) -> None:
        strategy, _, mock_factory = _make_strategy()
        mock_factory.limit.return_value = MagicMock()
        with patch.object(OneShotStrategy, "order_factory", new_callable=PropertyMock, return_value=mock_factory):
            strategy.on_start()
        kwargs = mock_factory.limit.call_args.kwargs
        assert kwargs["instrument_id"] == InstrumentId.from_str(_INSTRUMENT)

    def test_order_factory_receives_correct_side(self) -> None:
        strategy, _, mock_factory = _make_strategy()
        mock_factory.limit.return_value = MagicMock()
        with patch.object(OneShotStrategy, "order_factory", new_callable=PropertyMock, return_value=mock_factory):
            strategy.on_start()
        kwargs = mock_factory.limit.call_args.kwargs
        assert kwargs["order_side"] == OrderSide.BUY

    def test_order_factory_receives_correct_price(self) -> None:
        strategy, _, mock_factory = _make_strategy()
        mock_factory.limit.return_value = MagicMock()
        with patch.object(OneShotStrategy, "order_factory", new_callable=PropertyMock, return_value=mock_factory):
            strategy.on_start()
        kwargs = mock_factory.limit.call_args.kwargs
        assert kwargs["price"] == Price.from_str(_PRICE)

    def test_order_factory_receives_correct_quantity(self) -> None:
        strategy, _, mock_factory = _make_strategy()
        mock_factory.limit.return_value = MagicMock()
        with patch.object(OneShotStrategy, "order_factory", new_callable=PropertyMock, return_value=mock_factory):
            strategy.on_start()
        kwargs = mock_factory.limit.call_args.kwargs
        assert kwargs["quantity"] == Quantity.from_str(_QTY)

    def test_sell_side_passed_to_factory(self) -> None:
        strategy, _, mock_factory = _make_strategy(_make_config(side="SELL"))
        mock_factory.limit.return_value = MagicMock()
        with patch.object(OneShotStrategy, "order_factory", new_callable=PropertyMock, return_value=mock_factory):
            strategy.on_start()
        kwargs = mock_factory.limit.call_args.kwargs
        assert kwargs["order_side"] == OrderSide.SELL


class TestOnOrderAccepted:
    def test_on_done_called_with_venue_order_id(self) -> None:
        on_done = MagicMock()
        strategy, _, _ = _make_strategy(on_done=on_done)
        event = MagicMock()
        event.venue_order_id = "987654321"
        with patch.object(OneShotStrategy, "shutdown_system") as mock_shutdown:
            strategy.on_order_accepted(event)
        on_done.assert_called_once_with("987654321", None)
        mock_shutdown.assert_called_once()

    def test_on_done_reason_is_none_on_accept(self) -> None:
        on_done = MagicMock()
        strategy, _, _ = _make_strategy(on_done=on_done)
        event = MagicMock()
        event.venue_order_id = "111"
        with patch.object(OneShotStrategy, "shutdown_system"):
            strategy.on_order_accepted(event)
        _, reason = on_done.call_args.args
        assert reason is None

    def test_venue_order_id_stringified(self) -> None:
        on_done = MagicMock()
        strategy, _, _ = _make_strategy(on_done=on_done)
        mock_id = MagicMock()
        mock_id.__str__ = lambda self: "VID-42"
        event = MagicMock()
        event.venue_order_id = mock_id
        with patch.object(OneShotStrategy, "shutdown_system"):
            strategy.on_order_accepted(event)
        vid, _ = on_done.call_args.args
        assert vid == "VID-42"


class TestOnOrderRejected:
    def test_on_done_called_with_reason(self) -> None:
        on_done = MagicMock()
        strategy, _, _ = _make_strategy(on_done=on_done)
        event = MagicMock()
        event.reason = "Insufficient balance"
        with patch.object(OneShotStrategy, "shutdown_system"):
            strategy.on_order_rejected(event)
        on_done.assert_called_once_with(None, "Insufficient balance")

    def test_on_done_venue_id_is_none_on_reject(self) -> None:
        on_done = MagicMock()
        strategy, _, _ = _make_strategy(on_done=on_done)
        event = MagicMock()
        event.reason = "Bad qty"
        with patch.object(OneShotStrategy, "shutdown_system"):
            strategy.on_order_rejected(event)
        vid, _ = on_done.call_args.args
        assert vid is None

    def test_reason_stringified(self) -> None:
        on_done = MagicMock()
        strategy, _, _ = _make_strategy(on_done=on_done)
        mock_reason = MagicMock()
        mock_reason.__str__ = lambda self: "ERR-1013"
        event = MagicMock()
        event.reason = mock_reason
        with patch.object(OneShotStrategy, "shutdown_system"):
            strategy.on_order_rejected(event)
        _, reason = on_done.call_args.args
        assert reason == "ERR-1013"
