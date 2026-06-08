"""CBP3: AST isolation check — monitoring/ must not call new_order or _request.

SS6.8.2 contract: the monitoring process must not import or call any
signed-write endpoint.  This test is a runnable assertion (not grep).
"""
from __future__ import annotations

import ast
from pathlib import Path

_MONITORING_DIR = Path("src/hermes/monitoring")
_S_FORBIDDEN = {"new_order", "_request"}


def _collect_attr_calls(tree: ast.AST) -> list[tuple[str, int]]:
    """Return (attr_name, lineno) for every Call whose func is an Attribute."""
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            hits.append((node.func.attr, node.lineno))
        # Also direct Name calls (e.g. new_order(...) without a receiver)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            hits.append((node.func.id, node.lineno))
    return hits


def test_no_forbidden_calls_in_monitoring() -> None:
    """CBP3: AST verifies {new_order, _request} call count == 0 across monitoring/."""
    violations: list[str] = []
    for py_file in sorted(_MONITORING_DIR.glob("*.py")):
        src = py_file.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(py_file))
        for attr, lineno in _collect_attr_calls(tree):
            if attr in _S_FORBIDDEN:
                violations.append(f"{py_file.name}:{lineno} calls {attr!r}")
    assert violations == [], (
        "SS6.8.2 violation — forbidden calls found:\n" + "\n".join(violations)
    )
