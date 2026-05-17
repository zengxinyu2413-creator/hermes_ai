# Hermes AI — Project Roadmap

**Version:** 0.6.0  
**Last updated:** 2026-05-17  
**HEAD:** fb625a4

This file is the single authoritative source for phase planning.
Sub-item numbering in commit messages (e.g. `Phase 2.D.6-ii`) follows the scheme defined here.

**Status legend:** ✅ Complete · 🟡 In progress · ⬜ Not started

---

## 1. Overall Progress

| Phase | Content | Status | Weight |
|-------|---------|--------|--------|
| 1 | Infrastructure (skeleton, deps, config, CI) | ✅ Complete | — |
| **2** | **Binance REST + WS client** | **🟡 In progress ~92%** | **15%** |
| 2.E | README + CHANGELOG + design docs | ⬜ | — |
| 3 | TimescaleDB write layer | ⬜ | 8% |
| 4 | Redis real-time data layer | ⬜ | 5% |
| 5 | Strategy layer skeleton | ⬜ | 10% |
| 6 | Backtesting engine | ⬜ | 15% |
| 7 | HMM market regime detection | ⬜ | 10% |
| 8 | Multi-strategy portfolio | ⬜ | 8% |
| 9 | Orchestrator (live scheduling) | ⬜ | 12% |
| 10 | Monitoring + alerting | ⬜ | 7% |
| 11 | Production deployment | ⬜ | 10% |

---

## 2. Phase 2 Detail

**Goal:** Build a production-ready Binance exchange layer — REST client (signing,
kline fetch, server-time sync) and WebSocket client (stream parsing, reconnect,
keepalive, metrics) — fully unit-tested with no live network dependency.

### 2.A – 2.D.5b — Core transport (complete)

| Milestone | Content | Status |
|-----------|---------|--------|
| 2.A | `HermesConfig` + `BinanceCredentials` (pydantic-settings) | ✅ |
| 2.B | REST client: signing, `ping`, `server_time`, `get_klines` + mock tests | ✅ |
| 2.C | WebSocket stream contracts (`Kline`, `BookTicker`, `Trade`, `StreamMessage`) | ✅ |
| 2.D.3 | `BinanceWsClient` skeleton: input validation, URL, queue | ✅ |
| 2.D.4a | WebSocket message parser (`_parse_message`, `StreamKind`) | ✅ |
| 2.D.4b | Read loop, lifecycle (`__aenter__`/`__aexit__`), `stream()` generator | ✅ |
| 2.D.5b | Exponential-backoff reconnect with jitter, 60 s cap, clean-close reset | ✅ |

### 2.D.6 — WS hardening (in progress)

| Sub-item | Content | Commit | Status |
|----------|---------|--------|--------|
| 2.D.6-i | WS keepalive (`ping_interval`/`ping_timeout`) + structlog safety-net tests (83→91 tests) | `4f18693` | ✅ |
| 2.D.6-ii | `WsMetrics` frozen dataclass + `BinanceWsClient` four counters | `094bb24` | ✅ |
| 2.D.6-iii | `WsMetrics` test coverage (`TestWsMetrics`, 6 tests, 91→97 passed) | `c8e93f7` | ✅ |
| 2.D.6-iv | Watchdog: 60 s stall detection (no-message timeout alert) | — | ⬜ |
| 2.D.6-v | `smoke_ws.py`: testnet smoke script | — | ⬜ |

### 2.E — Documentation

| Sub-item | Content | Status |
|----------|---------|--------|
| 2.E | README refresh + CHANGELOG + architecture design docs | ⬜ |

---

## 3. Current Position & Next Step

**Current position:** Phase 2.D.6-iii ✅ — Phase 2 overall ~92% complete.

**Near-term path:**

1. **Phase 2.D.6-iv** — watchdog: detect 60 s stall (no messages received), emit
   a structlog warning and increment a counter; unit-testable without live network.
2. **Phase 2.D.6-v** — `smoke_ws.py`: a runnable script that connects to Binance
   testnet, streams a few klines, prints metrics, and exits cleanly.
3. **Phase 2.E** — documentation pass (README, CHANGELOG, architecture diagrams).

**Next major phase:** Phase 3 — TimescaleDB write layer (historical kline ingestion,
schema migrations, async writer with backpressure).
