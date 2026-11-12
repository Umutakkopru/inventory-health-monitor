"""Structural rules from CLAUDE.md sections 3, 6 and 7, checked on the source code."""

import ast
from pathlib import Path

import pytest

from inventory_monitor.config import REPO_ROOT

LIBRARY = REPO_ROOT / "inventory_monitor"
APP_FILES = [*(REPO_ROOT / "app").rglob("*.py"), REPO_ROOT / "streamlit_app.py"]
# The only analytics modules the dashboard may import (section 7).
APP_MAY_IMPORT = {"pipeline", "models", "config", "report"}
# Calls that read the real clock. The data is static, so "today" is always as_of.
CLOCK_CALLS = {"now", "today", "utcnow"}


def _python_files(*roots: Path) -> list[Path]:
    files = []
    for root in roots:
        files.extend([root] if root.suffix == ".py" else root.rglob("*.py"))
    return [f for f in files if f.exists()]


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


@pytest.mark.parametrize("path", _python_files(LIBRARY), ids=lambda p: p.name)
def test_library_never_imports_streamlit(path: Path) -> None:
    imported = _imported_modules(path)
    assert not any(m == "streamlit" or m.startswith("streamlit.") for m in imported)


@pytest.mark.parametrize("path", _python_files(LIBRARY), ids=lambda p: p.name)
def test_library_never_imports_the_app(path: Path) -> None:
    assert not any(m == "app" or m.startswith("app.") for m in _imported_modules(path))


@pytest.mark.parametrize(
    "path", _python_files(LIBRARY, *APP_FILES), ids=lambda p: str(p.relative_to(REPO_ROOT))
)
def test_no_real_clock(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    calls = [
        ast.unparse(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in CLOCK_CALLS
    ]
    assert calls == []


@pytest.mark.parametrize(
    "path", _python_files(*APP_FILES), ids=lambda p: str(p.relative_to(REPO_ROOT))
)
def test_app_imports_only_the_public_analytics_modules(path: Path) -> None:
    library = {
        m.split(".")[1]
        for m in _imported_modules(path)
        if m.startswith("inventory_monitor.") and m.count(".") >= 1
    }
    assert library <= APP_MAY_IMPORT | {"Status", "Thresholds"}


def test_clock_check_detects_a_clock_call(tmp_path: Path) -> None:
    # Guard against a check that can never fail.
    sample = tmp_path / "sample.py"
    sample.write_text("import pandas as pd\nx = pd.Timestamp.now()\n", encoding="utf-8")
    with pytest.raises(AssertionError):
        test_no_real_clock(sample)
