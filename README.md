# Hermes AI v6 — SOL Quantitative Trading System

Institutional-grade Solana automated trading platform.

Core capabilities:
- HMM-based market regime detection (hmmlearn + LightGBM)
- Four-strategy orchestration: Trend CTA / Mean Reversion / AI Grid / Event-driven
- Production risk management: VaR / CVaR / Ruin-of-Ruin
- NautilusTrader 1.226 execution engine
- TimescaleDB + Redis data layer
- Binance REST + WebSocket client (exchange layer, Phase 2 complete)

## Tech Stack

| Layer | Choice |
|-------|--------|
| Trading engine | NautilusTrader 1.226 |
| Exchange client | Binance REST + WebSocket (async, httpx + websockets) |
| Database | TimescaleDB 2.x on PostgreSQL 16 |
| Cache | Redis 7 |
| ML | hmmlearn + LightGBM |
| Language | Python 3.11.15 |
| OS | Ubuntu 24.04 LTS |
| Deployment | Vultr Tokyo, 4 GB / 2 vCPU |

## Quick Start

```bash
# 1. Python version (enforced by .python-version)
pyenv local 3.11.15

# 2. Virtual environment
python -m venv venv && source venv/bin/activate
pip install -e ".[dev]"

# 3. Environment config — copy and fill in API keys
cp .env.example .env
# HERMES_ENV defaults to "testnet"; set to "mainnet" only for real trading

# 4. Verify everything works
pytest                    # all unit tests must pass
ruff check src tests      # zero warnings expected
mypy src/hermes           # strict mode, zero errors expected
```

## Project Structure

```
src/hermes/
  core/          Config (HermesConfig), logging, exceptions
  exchanges/     Binance REST + WebSocket client (Phase 2, active)
  data/          Ingestion, storage, features (stub)
  regime/        HMM + LightGBM regime detection (stub)
  strategies/    Four trading strategies (stub)
  risk/          Risk engine — VaR / CVaR / RoR (stub)
  execution/     Order routing, smart market-making (stub)
  orchestrator/  Strategy coordination (stub)
  monitoring/    Alerts, metrics (stub)
  backtest/      Backtesting engine (stub)

configs/         YAML configs
scripts/         Data download, training, deployment helpers
notebooks/       Research notebooks
tests/           unit/ + integration/ + e2e/
docs/            Architecture docs and roadmap
```

## Roadmap

Full phase plan (Phase 1–11): [docs/ROADMAP.md](docs/ROADMAP.md)

### Phase 2 Status — Binance Exchange Layer

| Sub-phase | Description | Status |
|-----------|-------------|--------|
| 2.A | `HermesConfig` + `BinanceCredentials` (pydantic-settings) | ✅ |
| 2.B | REST client: signing, `ping`, `server_time`, `get_klines` + tests | ✅ |
| 2.C | WS stream contracts: `Kline`, `BookTicker`, `Trade`, `StreamMessage` | ✅ |
| 2.D.3 | `BinanceWsClient` skeleton: validation, URL, queue | ✅ |
| 2.D.4a | WS message parser (`_parse_message`, `StreamKind`) | ✅ |
| 2.D.4b | Read loop, lifecycle (`__aenter__`/`__aexit__`), `stream()` | ✅ |
| 2.D.5b | Exponential-backoff reconnect with jitter, 60 s cap | ✅ |
| 2.D.6-i | WS keepalive (`ping_interval=20`, `ping_timeout=10`) + safety-net tests | ✅ |
| 2.D.6-ii | `WsMetrics` frozen dataclass + four counters in `BinanceWsClient` | ✅ |
| 2.D.6-iii | `WsMetrics` test suite (97 tests total) | ✅ |
| 2.E.1 | Testnet smoke test — 15 msgs/60 s, 3 streams, 0 reconnects | ✅ |
| 2.E.2 | README.md quickstart + phase status (this commit) | 🟡 |
| 2.E.3 | CHANGELOG.md backfilled from Phase 1 | ⬜ |
| 2.E.4 | docs/architecture/binance_ws.md design doc | ⬜ |

**Next major phase:** Phase 3 — TimescaleDB write layer.

## Development

```bash
pytest                                              # all tests
pytest tests/unit/exchanges/test_binance_ws.py     # single file
ruff check src tests && ruff format src tests
mypy src/hermes
```

`asyncio_mode = "auto"` — no `@pytest.mark.asyncio` needed on async test functions.

All env vars are prefixed `HERMES_` except Binance key pairs
(`BINANCE_TESTNET_API_KEY` / `BINANCE_TESTNET_API_SECRET`, etc.).

## License

Proprietary. All rights reserved.
