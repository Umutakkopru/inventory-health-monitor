"""Tests for the SQL transformation (CLAUDE.md section 6.2).

The hand-built cases use one material 00000001 in plant 1010 starting on Thursday
01.01.2026. Expected consumption is worked out by hand in each test with the formula

    outflow = stock(p) + receipts in (p, d] - stock(d),   spread evenly over the n days.
"""

import json
import math

import numpy as np
import pandas as pd
import pytest

from inventory_monitor import generate_data
from inventory_monitor.config import SAMPLE_WORKBOOK, SCENARIO_MANIFEST
from inventory_monitor.ingest import load_workbook
from inventory_monitor.models import CleanData
from inventory_monitor.quality import check_negative_outflow, run_checks
from inventory_monitor.transform import build_tables

MAT, PLANT = "00000001", "1010"


def _day(n: int) -> pd.Timestamp:
    """Day n of January 2026 (01.01.2026 is a Thursday)."""
    return pd.Timestamp(2026, 1, n)


def _clean(
    stock: dict[int, float],
    receipts: dict[int, float] | None = None,
    second_sloc: dict[int, float] | None = None,
) -> CleanData:
    """Snapshots per day for 0001 (and optionally 0002); a day left out is a gap."""
    rows = [
        {"date": _day(d), "storage_location": loc, "stock_qty": qty}
        for loc, values in (("0001", stock), ("0002", second_sloc or {}))
        for d, qty in values.items()
    ]
    stock_frame = pd.DataFrame(rows).assign(material_id=MAT, plant=PLANT, unit="ST")
    receipt_frame = pd.DataFrame(
        {
            "date": [_day(d) for d in (receipts or {})],
            "material_id": MAT,
            "plant": PLANT,
            "storage_location": "0001",
            "receipt_qty": list((receipts or {}).values()),
            "supplier": "Lieferant 01",
            "po_number": "4500000001",
        }
    )
    materials = pd.DataFrame(
        {
            "material_id": [MAT],
            "plant": [PLANT],
            "description": ["Kugellager 6204"],
            "unit_price_eur": [2.0],
            "lead_time_days": [7],
            "min_stock": [np.nan],
            "max_stock": [np.nan],
            "unit": ["ST"],
        }
    )
    return CleanData(stock=stock_frame, receipts=receipt_frame, materials=materials)


def _daily(clean: CleanData) -> pd.DataFrame:
    return build_tables(clean).daily.set_index("date")


def _values(series: pd.Series) -> list:
    """Floats with NaN as None, so lists compare cleanly."""
    return [None if pd.isna(v) else v for v in series]


# --- Derived consumption -------------------------------------------------------------------


def test_no_gap() -> None:
    # day 2: 10 - 9 = 1;  day 3: 9 + 8 - 15 = 2;  day 4: 15 - 12 = 3
    daily = _daily(_clean({1: 10, 2: 9, 3: 15, 4: 12}, receipts={3: 8}))
    assert _values(daily["consumption"]) == [None, 1.0, 2.0, 3.0]
    assert not daily["is_imputed"].any()
    assert daily["receipt_qty"].tolist() == [0.0, 0.0, 8.0, 0.0]


def test_one_day_gap_is_spread_over_two_days() -> None:
    # p = day 1, d = day 3, n = 2: outflow 10 - 6 = 4, so 2 per day on days 2 and 3
    daily = _daily(_clean({1: 10, 3: 6}))
    assert _values(daily["consumption"]) == [None, 2.0, 2.0]
    assert daily["is_imputed"].tolist() == [False, True, True]
    assert daily["is_observed"].tolist() == [True, False, True]
    assert _values(daily["stock_qty"]) == [10.0, None, 6.0]
    assert daily["stock_filled"].tolist() == [10.0, 10.0, 6.0]


def test_three_day_gap_with_a_receipt_inside() -> None:
    # p = day 1, d = day 5, n = 4: outflow 20 + 10 - 18 = 12, so 3 per day on days 2 to 5
    daily = _daily(_clean({1: 20, 5: 18}, receipts={3: 10}))
    assert _values(daily["consumption"]) == [None, 3.0, 3.0, 3.0, 3.0]
    assert daily["is_imputed"].tolist() == [False, True, True, True, True]
    assert daily["receipt_qty"].tolist() == [0.0, 0.0, 10.0, 0.0, 0.0]
    assert daily["stock_filled"].tolist() == [20.0, 20.0, 20.0, 20.0, 18.0]


def test_partial_storage_location_snapshot_makes_the_day_missing() -> None:
    # 0002 has no snapshot on day 2, so day 2 is missing for the material-plant.
    # p = day 1 (10 + 5 = 15), d = day 3 (8 + 3 = 11), n = 2: outflow 4, so 2 per day.
    clean = _clean({1: 10, 2: 9, 3: 8}, second_sloc={1: 5, 3: 3})
    tables = build_tables(clean)
    daily = tables.daily.set_index("date")
    assert _values(daily["stock_qty"]) == [15.0, None, 11.0]
    assert _values(daily["consumption"]) == [None, 2.0, 2.0]
    by_sloc = tables.by_sloc.query("storage_location == '0002'")
    assert by_sloc["is_observed"].tolist() == [True, False, True]


def test_negative_outflow_is_flagged_and_clipped() -> None:
    # Stock rises from 10 to 30 without a receipt: 10 - 30 = -20.
    daily = _daily(_clean({1: 10, 2: 30, 3: 28}))
    assert _values(daily["consumption_raw"]) == [None, -20.0, 2.0]
    assert _values(daily["consumption"]) == [None, 0.0, 2.0]
    assert daily["is_negative_outflow"].tolist() == [False, True, False]


def test_negative_outflow_across_a_gap_flags_every_day_of_the_segment() -> None:
    # p = day 1, d = day 3, n = 2: outflow 10 - 30 = -20, so -10 per day.
    daily = _daily(_clean({1: 10, 3: 30}))
    assert _values(daily["consumption_raw"]) == [None, -10.0, -10.0]
    assert daily["is_negative_outflow"].tolist() == [False, True, True]


def test_floating_point_noise_is_not_a_negative_outflow() -> None:
    # 0.3 + (0.1 + 0.2) - 0.6 is 5.6e-17 in floating point, not zero.
    assert 0.3 + (0.1 + 0.2) - 0.6 != 0
    clean = _clean({1: 0.3, 2: 0.6}, receipts={2: 0.1})
    clean = CleanData(
        stock=clean.stock,
        receipts=pd.concat([clean.receipts, clean.receipts.assign(receipt_qty=0.2)]),
        materials=clean.materials,
    )
    daily = _daily(clean)
    assert daily.loc[_day(2), "consumption_raw"] == 0.0
    assert not daily["is_negative_outflow"].any()


def test_materials_do_not_influence_each_other() -> None:
    clean = _clean({1: 10, 2: 9})
    other = clean.stock.assign(material_id="00000002", stock_qty=[100.0, 50.0])
    clean = CleanData(
        stock=pd.concat([clean.stock, other]), receipts=clean.receipts, materials=clean.materials
    )
    daily = build_tables(clean).daily
    first = daily.query("material_id == @MAT")
    assert _values(first["consumption"]) == [None, 1.0]  # 10 - 9, not affected by 00000002


def test_weekly_demand_and_complete_weeks() -> None:
    # Monday 05.01. to Sunday 18.01.: stock falls by 1 per day from 100.
    # Week of 05.01.: day 1 has no consumption -> 6 values, demand 6, incomplete.
    # Week of 12.01.: 7 values, demand 7, complete.
    stock = {d: 100.0 - (d - 5) for d in range(5, 19)}
    weekly = build_tables(_clean(stock)).weekly
    assert weekly["week_start"].tolist() == [_day(5), _day(12)]
    assert weekly["demand"].tolist() == [6.0, 7.0]
    assert weekly["days_with_value"].tolist() == [6, 7]
    assert weekly["is_complete"].tolist() == [False, True]


def test_output_types_and_repeatability() -> None:
    clean = _clean({1: 10, 3: 6}, receipts={2: 1})
    first, second = build_tables(clean), build_tables(clean)
    pd.testing.assert_frame_equal(first.daily, second.daily)
    assert first.daily["date"].dtype == "datetime64[ns]"
    assert first.weekly["week_start"].dtype == "datetime64[ns]"


# --- DQ08 and the sample workbook ----------------------------------------------------------


def test_dq08_one_issue_per_negative_segment() -> None:
    daily = build_tables(_clean({1: 10, 3: 30, 4: 28, 5: 40})).daily
    # Segment (1, 3]: (10 - 30) / 2 = -10 per day, closed on day 3.
    # Segment (4, 5]: 28 - 40 = -12, closed on day 5.
    issues = check_negative_outflow(daily)
    assert issues["date"].tolist() == [_day(3), _day(5)]
    assert issues["detail"].tolist() == ["-10", "-12"]
    assert set(issues["check_id"]) == {"DQ08"}


@pytest.fixture(scope="module")
def sample() -> tuple[pd.DataFrame, dict]:
    clean, _ = run_checks(load_workbook(SAMPLE_WORKBOOK))
    manifest = json.loads(SCENARIO_MANIFEST.read_text(encoding="utf-8"))
    return build_tables(clean).daily, manifest


def test_sample_dq08_finds_exactly_the_unrecorded_receipts(sample) -> None:
    daily, manifest = sample
    issues = check_negative_outflow(daily)
    found = set(zip(issues["material_id"], issues["plant"], issues["date"], strict=True))
    injected = {
        (d["material_id"], d["plant"], pd.Timestamp(d["date"]))
        for d in manifest["defects"]
        if d["defect"] == "unrecorded_receipt"
    }
    assert found == injected


def test_sample_derived_consumption_equals_the_simulated_truth(sample) -> None:
    # Phase 3 gate: on material-plants without defects, derived consumption is exactly
    # the consumption the generator simulated.
    daily, manifest = sample
    truth = generate_data.generate().simulation.daily.set_index(["material_id", "plant", "date"])
    clean_keys = [tuple(k) for k in manifest["clean_material_plants"]]
    assert len(clean_keys) >= 3
    for material, plant in clean_keys:
        selected = (daily["material_id"] == material) & (daily["plant"] == plant)
        mine = daily[selected].set_index(["material_id", "plant", "date"])
        derived = mine["consumption"].dropna()
        expected = truth.loc[derived.index, "consumption"]
        assert len(derived) == 364  # 365 days, the first has no previous snapshot
        assert not mine["is_imputed"].any()
        assert all(math.isclose(a, b, abs_tol=1e-9) for a, b in zip(derived, expected, strict=True))
