"""Smoke tests - verify basic environment integrity."""
import sys


def test_python_version():
    """Verify we are running on Python 3.12."""
    assert sys.version_info[:2] == (3, 12), (
        f"Expected Python 3.12, got {sys.version_info[:2]}"
    )


def test_hermes_importable():
    """Verify the hermes package is importable."""
    import hermes
    assert hermes.__version__ == "0.6.0"


def test_critical_dependencies_importable():
    """Verify all critical dependencies can be imported."""
    import nautilus_trader  # noqa: F401
    import numpy  # noqa: F401
    import pandas  # noqa: F401
    import polars  # noqa: F401
    import hmmlearn  # noqa: F401
    import lightgbm  # noqa: F401
    import psycopg  # noqa: F401
    import redis  # noqa: F401


def test_nautilus_version():
    """Verify NautilusTrader version is in expected range."""
    import nautilus_trader
    version = nautilus_trader.__version__
    parts = version.split(".")
    major, minor = int(parts[0]), int(parts[1])
    assert major == 1 and minor == 227, (
        f"Expected nautilus-trader 1.227.x, got {version}"
    )


def test_pyarrow_compatible_with_nautilus():
    """Verify pyarrow version satisfies nautilus-trader requirement."""
    import pyarrow
    major = int(pyarrow.__version__.split(".")[0])
    assert major >= 21, f"pyarrow >= 21 required, got {pyarrow.__version__}"
