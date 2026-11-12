"""Tests for the configuration constants and the Thresholds dataclass."""

import dataclasses

import pytest

from inventory_monitor.config import (
    DEFAULT_THRESHOLDS,
    MATERIAL_COLUMNS,
    RECEIPT_COLUMNS,
    STOCK_COLUMNS,
    STRING_HEADERS,
    Thresholds,
)


def test_thresholds_are_hashable_and_equal_by_value() -> None:
    # st.cache_data uses the thresholds as a cache key, so equal values must hash equally.
    assert hash(Thresholds()) == hash(Thresholds())
    assert Thresholds(dead_stock_days=120) != DEFAULT_THRESHOLDS


def test_thresholds_are_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        DEFAULT_THRESHOLDS.dead_stock_days = 1


def test_per_class_lookups() -> None:
    assert DEFAULT_THRESHOLDS.service_level("A") == 0.98
    assert DEFAULT_THRESHOLDS.service_level("C") == 0.90
    assert DEFAULT_THRESHOLDS.overstock_days("B") == 90


def test_canonical_names_are_unique_per_sheet() -> None:
    for mapping in (STOCK_COLUMNS, RECEIPT_COLUMNS, MATERIAL_COLUMNS):
        assert len(set(mapping.values())) == len(mapping)


def test_string_headers_exist_in_some_sheet() -> None:
    all_headers = set(STOCK_COLUMNS) | set(RECEIPT_COLUMNS) | set(MATERIAL_COLUMNS)
    assert set(STRING_HEADERS) <= all_headers
