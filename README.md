# Hermes AI v6 - SOL Quantitative Trading System

Institutional-grade Solana automated trading platform with:
- HMM-based market regime detection
- 4-strategy orchestration (Trend CTA / Mean Reversion / AI Grid / Event-driven)
- Production risk management (VaR / CVaR / RoR)
- NautilusTrader 1.226 execution engine
- TimescaleDB + Redis data layer

## Tech Stack

- Trading Engine: NautilusTrader 1.226
- Database: TimescaleDB 2.x on PostgreSQL 16
- Cache: Redis 7
- ML: hmmlearn + LightGBM
- Language: Python 3.11.15
- OS: Ubuntu 24.04 LTS
- Deployment: Vultr Tokyo, 4GB / 2 vCPU

## Project Structure

- src/hermes/core         Config, logging, types
- src/hermes/exchanges    Binance REST + WebSocket
- src/hermes/data         Ingestion, storage, features
- src/hermes/regime       HMM + LightGBM
- src/hermes/strategies   Four trading strategies
- src/hermes/risk         Risk engine
- src/hermes/execution    Order routing, smart making
- src/hermes/orchestrator Strategy coordination
- src/hermes/monitoring   Alerts, metrics
- src/hermes/backtest     Backtesting engine
- configs                 YAML configs
- scripts                 Data download, training, deployment
- notebooks               Research notebooks
- tests                   Unit + integration + e2e tests
- data                    Historical + features
- models                  Trained HMM/LGBM models
- docs                    Architecture and operations

## Development

After setting up venv and installing dependencies:

    cd ~/hermes_ai
    pyenv local 3.11.15
    pip install -e ".[dev]"
    pytest

## License

Proprietary. All rights reserved.
