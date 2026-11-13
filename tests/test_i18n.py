"""Tests for the UI strings and the number and date formatting (CLAUDE.md section 8.3)."""

import ast
import math
import re
import string

import pandas as pd
import pytest

from app import i18n
from app.i18n import (
    STRINGS,
    fmt_coverage,
    fmt_date,
    fmt_eur,
    fmt_eur_compact,
    fmt_number,
    fmt_pct,
    plotly_separators,
    translate,
)
from inventory_monitor.config import REPO_ROOT
from inventory_monitor.models import Status

APP_FILES = [*(REPO_ROOT / "app").rglob("*.py"), REPO_ROOT / "streamlit_app.py"]


def _t_calls() -> tuple[set[str], set[str]]:
    """Literal keys passed to t(), and the literal prefixes of f-string keys."""
    literal, prefixes = set(), set()
    for path in APP_FILES:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "t"):
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Constant):
                literal.add(arg.value)
            elif isinstance(arg, ast.JoinedStr):
                parts = arg.values  # noqa: PD011 - ast.JoinedStr.values, not a pandas object
                if isinstance(parts[0], ast.Constant):
                    prefixes.add(parts[0].value)
    return literal, prefixes


def _placeholders(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


# --- Dictionaries --------------------------------------------------------------------------


def test_both_languages_have_identical_keys() -> None:
    assert set(STRINGS["de"]) == set(STRINGS["en"])


def test_no_empty_values() -> None:
    empty = [(lang, k) for lang, strings in STRINGS.items() for k, v in strings.items() if not v]
    assert empty == []


def test_placeholders_match_between_languages() -> None:
    differ = [
        key
        for key in STRINGS["de"]
        if _placeholders(STRINGS["de"][key]) != _placeholders(STRINGS["en"][key])
    ]
    assert differ == []


def test_every_key_used_in_the_app_exists() -> None:
    literal, prefixes = _t_calls()
    assert literal, "no t() calls found: the scan is broken"
    assert sorted(literal - set(STRINGS["de"])) == []
    for prefix in prefixes:
        assert any(key.startswith(prefix) for key in STRINGS["de"]), prefix


def test_every_status_has_a_label() -> None:
    for lang in STRINGS:
        assert all(f"status.{s.value}" in STRINGS[lang] for s in Status)


def test_german_mode_has_no_english_status_or_nav_text() -> None:
    assert STRINGS["de"]["status.OK"] == "In Ordnung"
    assert STRINGS["de"]["nav.alerts"] == "Warnungen"
    assert STRINGS["en"]["nav.alerts"] == "Alerts"


def test_missing_key_raises_in_strict_mode_and_returns_the_key_otherwise(monkeypatch) -> None:
    with pytest.raises(KeyError):
        translate("no.such.key", "de")
    monkeypatch.delenv(i18n.STRICT_ENV)
    assert translate("no.such.key", "de") == "no.such.key"


def test_placeholders_are_filled() -> None:
    assert translate("alerts.count", "de", shown="3", total="90") == "3 von 90 Materialien"
    assert translate("alerts.count", "en", shown="3", total="90") == "3 of 90 materials"


# --- Formatting ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "decimals", "de", "en"),
    [
        (1234.5, 1, "1.234,5", "1,234.5"),
        (1234567, 0, "1.234.567", "1,234,567"),
        (0.25, 2, "0,25", "0.25"),
        (-3, 0, "-3", "-3"),
    ],
)
def test_fmt_number(value: float, decimals: int, de: str, en: str) -> None:
    assert fmt_number(value, decimals, lang="de") == de
    assert fmt_number(value, decimals, lang="en") == en


def test_missing_values_show_a_dash() -> None:
    for value in (None, math.nan, pd.NaT):
        assert fmt_number(value, lang="de") == "–"
        assert fmt_date(value, lang="en") == "–"


def test_fmt_eur() -> None:
    assert fmt_eur(1234.4, lang="de") == "1.234 €"
    assert fmt_eur(1234.4, lang="en") == "€1,234"


def test_fmt_eur_compact() -> None:
    assert fmt_eur_compact(8_204_118, lang="de") == "8,2 Mio. €"
    assert fmt_eur_compact(8_204_118, lang="en") == "€8.2M"
    assert fmt_eur_compact(820_000, lang="de") == "820,0 Tsd. €"
    assert fmt_eur_compact(950, lang="en") == "€950"


def test_fmt_pct() -> None:
    assert fmt_pct(0.123, 1, lang="de") == "12,3 %"
    assert fmt_pct(0.123, 1, lang="en") == "12.3%"


def test_fmt_coverage() -> None:
    assert fmt_coverage(math.inf, lang="de") == "> 365"
    assert fmt_coverage(14.4, lang="en") == "14"
    assert fmt_coverage(math.nan, lang="en") == "–"


def test_fmt_date() -> None:
    day = pd.Timestamp("2026-10-31")
    assert fmt_date(day, lang="de") == "31.10.2026"
    assert fmt_date(day, lang="en") == "2026-10-31"


def test_plotly_separators() -> None:
    assert plotly_separators("de") == ",."
    assert plotly_separators("en") == ".,"


def test_no_hard_coded_ui_text_in_views() -> None:
    # Views pass user-visible text through t(); a st.title("...") with a literal would not.
    pattern = re.compile(r"st\.(title|header|subheader|caption|info|warning|button)\(\s*\"")
    offenders = [p.name for p in APP_FILES if pattern.search(p.read_text(encoding="utf-8"))]
    assert offenders == []
