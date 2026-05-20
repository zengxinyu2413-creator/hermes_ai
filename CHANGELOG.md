# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

## [0.5.0] — 2026-05-17 — Phase 2.D.6: WS Hardening

### Added
- `WsMetrics` frozen dataclass (7 fields) tracking messages received, reconnects,
  parse errors, connect time, last message time, connect count, disconnect count
- `BinanceWsClient._metrics` property exposing live `WsMetrics` snapshot
- WS keepalive: `ping_interval=20 s`, `ping_timeout=10 s` passed to `websockets.connect`
- structlog safety-net test: verifies logger is bound before first WS connect (Phase 2.D.6-i)
- `TestWsMetrics` test class with 6 cases; total unit test count raised to 97 (Phase 2.D.6-iii)

## [0.4.0] — 2026-05-15 — Phase 2.D.5b: Reconnect

### Added
- `_compute_backoff_delay(attempt)`: exponential backoff with ±25 % jitter, 60 s cap
- `_run_with_reconnect`: infinite reconnect loop wrapping `_run_one`; clean-close resets
  the attempt counter to 0
- End-to-end reconnect test suite (Phase 2.D.5b-iv)

### Fixed
- Non-`CancelledError` exceptions from `_run_one` now re-raised instead of silently swallowed

## [0.3.0] — 2026-05-14 — Phase 2.C / 2.D.3-4b: WebSocket Client

### Added
- WS stream contracts: `Kline`, `BookTicker`, `Trade`, `StreamMessage`, `StreamKind`
  (all prices/volumes as `Decimal`; frozen dataclasses with `slots=True`)
- `BinanceWsClient`: async context manager for Binance combined-stream WebSockets;
  streams fixed at construction, queue created in `__aenter__`
- `_parse_message`: never raises — malformed frames produce `StreamKind.UNKNOWN`
- Read loop, `__aenter__`/`__aexit__` lifecycle, `stream()` async generator

### Fixed
- Stream-type matching accepts camelCase Binance stream names (e.g. `kline_1m`)

## [0.2.0] — 2026-05-13 — Phase 2.A / 2.B: Config + REST Client

### Added
- `HermesConfig` (pydantic-settings): single config object per process, built via
  `HermesConfig.from_env()`; nothing else reads `os.environ` directly
- `BinanceCredentials` + `BinanceEnvironment` enum; credentials accessed via
  `config.credentials` lazy property
- `BinanceRestClient`: async httpx client with HMAC-SHA256 signing (`_signing.py`)
- REST endpoints: `ping`, `server_time`, `get_klines`
- Exception hierarchy: `HermesError → BinanceError → BinanceAPIError → RateLimitError`,
  plus `ConfigurationError`, `OrderError`, `SigningError`
- Full REST client unit tests with mocked httpx transport

## [0.1.0] — 2026-05-12 — Phase 1: Infrastructure

### Added
- Hermes AI v6 project skeleton (Python 3.11.15, pyproject.toml)
- Linting: ruff (`E, F, I, N, W, UP, B, SIM, RUF`); type checking: mypy strict over `src/hermes`
- Module stubs: `core`, `exchanges`, `data`, `regime`, `strategies`, `risk`,
  `execution`, `orchestrator`, `monitoring`, `backtest`
- Test layout: `tests/unit/`, `tests/integration/`, `tests/e2e/`;
  `asyncio_mode = "auto"` (no `@pytest.mark.asyncio` needed)
- `.env.example` with `HERMES_ENV=testnet` default; all env vars prefixed `HERMES_`
- v5 codebase archived to `archive/hermes_v5/`
