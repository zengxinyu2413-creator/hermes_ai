"""Hermes AI CLI entry point.

Entry point registered in pyproject.toml:
    hermes = "hermes.cli:main"

Subcommands
-----------
trade-live  Launch the live/testnet order-submission node (b3, not yet implemented).
"""
from __future__ import annotations

import click


@click.group()
def main() -> None:
    """Hermes AI trading system."""


@main.command("trade-live")
@click.option("--dry", is_flag=True, help="Dry-run (accepted by CLI; execution not yet wired).")
def trade_live(dry: bool) -> None:
    """Launch the live/testnet order-submission node.

    Execution layer (exec client, TradingNode) is wired in b3.
    """
    raise NotImplementedError("trade-live execution not yet implemented (b3)")
