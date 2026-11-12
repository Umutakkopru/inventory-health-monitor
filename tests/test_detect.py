"""Tests for status assignment, priority and anomaly flags (CLAUDE.md section 6.5).

Default thresholds: min_history_days 56, dead_stock_days 90, anomaly_iqr_factor 3.
"""

import numpy as np
import pandas as pd
import pytest

from inventory_monitor.config import DEFAULT_THRESHOLDS
from inventory_monitor.detect import assign_status, flag_anomalies
from inventory_monitor.models import Status

AS_OF = pd.Timestamp("2026-10-31")


def _row(**changes) -> dict:
    """A healthy material: stock 50 between reorder point 30 and maximum 100."""
    return {
        "material_id": "00000001",
        "plant": "1010",
        "abc": "A",
        "history_days": 365,
        "stock": 50.0,
        "days_since_consumption": 1,
        "safety_stock": 10.0,
        "reorder_point": 30.0,
        "max_target": 100.0,
        "excess_qty": 0.0,
        "shortfall_qty": 0.0,
        "unit_price_eur": 2.0,
    } | changes


def _status(**changes) -> str:
    return assign_status(pd.DataFrame([_row(**changes)]), DEFAULT_THRESHOLDS)["status"].iloc[0]


# --- One case per status -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, Status.OK),
        ({"history_days": 55}, Status.INSUFFICIENT_DATA),
        ({"stock": 0.0, "days_since_consumption": 90}, Status.INACTIVE),
        ({"stock": 5.0}, Status.SHORTAGE_CRITICAL),  # below safety stock 10
        ({"stock": 20.0}, Status.SHORTAGE_WARNING),  # between 10 and reorder point 30
        ({"days_since_consumption": 90}, Status.DEAD_STOCK),
        ({"stock": 150.0}, Status.OVERSTOCK),  # above maximum 100
    ],
)
def test_one_case_per_status(changes: dict, expected: Status) -> None:
    assert _status(**changes) == expected


def test_boundaries_are_strict_where_the_rule_says_below_or_above() -> None:
    assert _status(stock=10.0) == Status.SHORTAGE_WARNING  # equal to safety stock: not below
    assert _status(stock=30.0) == Status.OK  # equal to reorder point: not below
    assert _status(stock=100.0) == Status.OK  # equal to maximum: not above
    assert _status(history_days=56) == Status.OK  # 56 days is enough
    assert _status(days_since_consumption=89) == Status.OK  # 89 days is still in use


# --- Precedence: several conditions match, the first rule wins -----------------------------


def test_insufficient_data_wins_over_a_shortage() -> None:
    assert _status(history_days=20, stock=0.0) == Status.INSUFFICIENT_DATA


def test_inactive_wins_over_critical_when_unused_for_long() -> None:
    # Zero stock matches rule 3 too, but nobody has used it for 120 days.
    assert _status(stock=0.0, days_since_consumption=120) == Status.INACTIVE


def test_zero_stock_with_recent_use_is_critical() -> None:
    assert _status(stock=0.0, days_since_consumption=10) == Status.SHORTAGE_CRITICAL


def test_negative_stock_is_critical() -> None:
    assert _status(stock=-1.0, safety_stock=np.nan) == Status.SHORTAGE_CRITICAL


def test_critical_wins_over_dead_stock() -> None:
    assert _status(stock=5.0, days_since_consumption=200) == Status.SHORTAGE_CRITICAL


def test_warning_wins_over_dead_stock() -> None:
    assert _status(stock=20.0, days_since_consumption=200) == Status.SHORTAGE_WARNING


def test_dead_stock_wins_over_overstock() -> None:
    assert _status(stock=150.0, days_since_consumption=200) == Status.DEAD_STOCK


def test_missing_limits_do_not_trigger_a_status() -> None:
    # Unknown safety stock, reorder point and maximum: no comparison can match.
    unknown = {"safety_stock": np.nan, "reorder_point": np.nan, "max_target": np.nan}
    assert _status(**unknown) == Status.OK


# --- Excess, value at risk and priority ----------------------------------------------------


def test_dead_stock_counts_the_whole_stock_as_excess() -> None:
    out = assign_status(pd.DataFrame([_row(days_since_consumption=200)]), DEFAULT_THRESHOLDS)
    assert out["excess_qty"].iloc[0] == 50.0
    assert out["excess_value"].iloc[0] == 100.0  # 50 * 2 EUR
    assert out["value_at_risk"].iloc[0] == 100.0


def test_value_at_risk_for_shortage_and_ok() -> None:
    frame = pd.DataFrame([_row(stock=20.0, shortfall_qty=10.0), _row()])
    out = assign_status(frame, DEFAULT_THRESHOLDS)
    assert out["value_at_risk"].tolist() == [20.0, 0.0]  # 10 * 2 EUR; OK has none


def test_shortage_priority_puts_class_a_first_whatever_the_value() -> None:
    frame = pd.DataFrame(
        [
            _row(material_id="C-big", abc="C", stock=5.0, shortfall_qty=1000.0),
            _row(material_id="A-small", abc="A", stock=5.0, shortfall_qty=1.0),
            _row(material_id="B-mid", abc="B", stock=5.0, shortfall_qty=100.0),
            _row(material_id="A-big", abc="A", stock=5.0, shortfall_qty=50.0),
        ]
    )
    out = assign_status(frame, DEFAULT_THRESHOLDS).sort_values("priority_score", ascending=False)
    assert out["material_id"].tolist() == ["A-big", "A-small", "B-mid", "C-big"]


def test_overstock_priority_follows_excess_value() -> None:
    frame = pd.DataFrame(
        [
            _row(material_id="A-small", stock=150.0, excess_qty=50.0),  # 100 EUR
            _row(material_id="C-big", abc="C", stock=150.0, excess_qty=500.0),  # 1000 EUR
        ]
    )
    out = assign_status(frame, DEFAULT_THRESHOLDS).sort_values("priority_score", ascending=False)
    assert out["material_id"].tolist() == ["C-big", "A-small"]


def test_input_is_not_mutated() -> None:
    frame = pd.DataFrame([_row(days_since_consumption=200)])
    before = frame.copy()
    assign_status(frame, DEFAULT_THRESHOLDS)
    pd.testing.assert_frame_equal(frame, before)


# --- Anomaly flags -------------------------------------------------------------------------


def _metrics_for_flags() -> pd.DataFrame:
    return pd.DataFrame([{"material_id": "00000001", "plant": "1010", "cutoff": AS_OF}])


def _weeks(demands: list[float]) -> pd.DataFrame:
    # Complete weeks ending on Sunday 25.10.2026 at the latest.
    starts = pd.date_range(end="2026-10-19", periods=len(demands), freq="7D")
    return pd.DataFrame(
        {
            "material_id": "00000001",
            "plant": "1010",
            "week_start": starts,
            "demand": demands,
            "is_complete": True,
        }
    )


def _receipts(quantities: list[float], recent: list[float]) -> pd.DataFrame:
    old = pd.date_range(end="2026-08-31", periods=len(quantities), freq="14D")
    new = pd.date_range(end="2026-10-30", periods=len(recent), freq="D")
    return pd.DataFrame(
        {
            "material_id": "00000001",
            "plant": "1010",
            "date": pd.to_datetime(list(old) + list(new)),
            "receipt_qty": quantities + recent,
        }
    )


def _flags(weekly: pd.DataFrame, receipts: pd.DataFrame) -> pd.Series:
    out = flag_anomalies(_metrics_for_flags(), weekly, receipts, AS_OF, DEFAULT_THRESHOLDS)
    return out.iloc[0]


HISTORY = [10.0, 12.0, 11.0, 13.0, 10.0, 12.0, 11.0, 13.0]
# Sorted: 10 10 11 11 12 12 13 13. Q1 = 10.75, Q3 = 12.25 (linear), IQR = 1.5.
# Fence = 12.25 + 3 * 1.5 = 16.75.


def test_demand_anomaly_above_the_fence() -> None:
    assert bool(_flags(_weeks([*HISTORY, 50.0]), _receipts([], []))["demand_anomaly"])


def test_demand_below_the_fence_is_normal() -> None:
    assert not _flags(_weeks([*HISTORY, 16.0]), _receipts([], []))["demand_anomaly"]


def test_demand_anomaly_needs_enough_history() -> None:
    assert not _flags(_weeks([10.0, 11.0, 12.0, 50.0]), _receipts([], []))["demand_anomaly"]


def test_week_after_the_cutoff_is_not_used() -> None:
    weekly = pd.concat([_weeks(HISTORY), _weeks([50.0]).assign(week_start=AS_OF)])
    assert not _flags(weekly, _receipts([], []))["demand_anomaly"]


def test_receipt_anomaly() -> None:
    # History 80 100 100 100 120: Q1 = Q3 = 100, IQR = 0, fence = 100.
    history = [100.0, 100.0, 100.0, 120.0, 80.0]
    assert bool(_flags(_weeks(HISTORY), _receipts(history, [150.0]))["receipt_anomaly"])
    assert not _flags(_weeks(HISTORY), _receipts(history, [100.0]))["receipt_anomaly"]


def test_receipt_anomaly_needs_five_earlier_receipts() -> None:
    receipts = _receipts([100.0, 100.0, 100.0, 100.0], [1000.0])
    assert not _flags(_weeks(HISTORY), receipts)["receipt_anomaly"]


def test_anomaly_flags_do_not_change_the_status() -> None:
    frame = pd.DataFrame([_row()])
    flagged = frame.assign(demand_anomaly=True, receipt_anomaly=True)
    plain = assign_status(frame, DEFAULT_THRESHOLDS)["status"]
    with_flags = assign_status(flagged, DEFAULT_THRESHOLDS)["status"]
    pd.testing.assert_series_equal(plain, with_flags)
