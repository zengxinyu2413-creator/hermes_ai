# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Setup (Python 3.11.15 required — enforced by .python-version)
pyenv local 3.11.15
python -m venv venv && source venv/bin/activate
pip install -e ".[dev]"

# Run all tests
pytest

# Run a single test file
pytest tests/unit/exchanges/test_binance_ws.py

# Run a single test by name
pytest tests/unit/exchanges/test_binance_ws.py::TestStreamsValidation::test_empty_list_rejected

# Lint
ruff check src tests

# Format
ruff format src tests

# Type check
mypy src/hermes
```

## Environment

Copy `.env.example` to `.env` before running anything. `HERMES_ENV` defaults to `testnet` — switching to `mainnet` (real money) requires an explicit `HERMES_ENV=mainnet`. All env vars are prefixed `HERMES_` except the Binance key pairs (`BINANCE_<ENV>_API_KEY` / `BINANCE_<ENV>_API_SECRET`).

## Architecture

### Configuration layer (`src/hermes/core/`)

`HermesConfig` (pydantic-settings) is the single config object per process. Build it once at startup with `HermesConfig.from_env()`. Nothing else reads `os.environ` directly. `BinanceCredentials` is a separate model so credentials can be passed around without dragging unrelated config; access them via `config.credentials` (lazy property, not a stored field).

All exceptions inherit from `HermesError` (`core/exceptions.py`). Subtree: `BinanceError → BinanceAPIError → RateLimitError`, plus `ConfigurationError`, `OrderError`, `SigningError`.

### Exchange layer (`src/hermes/exchanges/`)

Responsibility is split across four files:
- `_signing.py` — pure HMAC-SHA256 signing, no I/O.
- `binance_credentials.py` — `BinanceCredentials` + `BinanceEnvironment` enum.
- `binance_contracts.py` — typed data contracts: `Kline`, `BookTicker`, `Trade`, `StreamMessage`, `StreamKind`. All prices and volumes use `Decimal`, not `float`. These are frozen dataclasses with `slots=True` (immutable, hashable, memory-efficient for backtest volumes). The rest of the codebase never touches raw Binance JSON — it always receives one of these typed objects.
- `binance_ws.py` — `BinanceWsClient`: async context manager for Binance combined-stream WebSockets. Streams are fixed at construction; construction itself is event-loop-free (queue is created in `__aenter__`). `_run_with_reconnect` wraps `_run_one` in an infinite loop with exponential backoff + jitter; `_run_one` does the actual `websockets.connect`. Consumers call `async for msg in ws.stream()` and receive `StreamMessage` envelopes. `_parse_message` never raises — malformed frames produce `StreamKind.UNKNOWN`.
- `binance_rest.py` — `BinanceRestClient`: httpx async client.

### Module status

`src/hermes/regime`, `strategies`, `risk`, `execution`, `orchestrator`, `monitoring`, and `backtest` are stubs — they contain only `__init__.py`. Active development is in `exchanges`.

### Test layout

```
tests/unit/        # fast, no I/O — mock network in WS tests
tests/integration/ # requires running services (DB, Redis)
tests/e2e/         # full stack
```

`asyncio_mode = "auto"` in `pyproject.toml` — all `async def` test functions are treated as coroutines automatically; no `@pytest.mark.asyncio` needed. `pythonpath = ["src"]` means imports are `from hermes.exchanges...`, not `from src.hermes...`.

## Key conventions

- Line length: 100 (ruff `E501` is ignored — long lines allowed).
- Ruff rule set: `E, F, I, N, W, UP, B, SIM, RUF`.
- Mypy runs in `strict` mode over `src/hermes` only.
- Stream names passed to `BinanceWsClient` must have lowercase symbol parts (`solusdt@kline_1m`, not `SOLUSDT@kline_1m`) — Binance silently drops incorrectly-cased subscriptions.
- `Kline.from_binance_ws_payload` accepts the inner `k` dict, not the outer event — the WS client unwraps before calling.
