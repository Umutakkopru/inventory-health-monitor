"""Tests for the per-material KPIs (CLAUDE.md section 6.3).

Base case, built by hand: material 00000001 in plant 1010, price 2 EUR, lead time 7 days.
Snapshots run from Sunday 04.01.2026 to Sunday 01.03.2026 (57 days). The first day has
no consumption; then eight Monday-to-Sunday weeks with weekly demand

    week of:  05.01  12.01  19.01  26.01  02.02  09.02  16.02  23.02
    demand:      50     50     40     60     50     50     40     60

spread evenly over Monday to Friday (weekends zero). Stock on 01.03. is 100.
The tests use a 14-day demand window and a 4-week variability window.
"""

import math

import numpy as np
import pandas as pd
import pytest

from inventory_monitor.config import Thresholds
from inventory_monitor.metrics import compute_metrics
from inventory_monitor.models import DailyTables

MAT, PLANT = "00000001", "1010"
START, AS_OF = pd.Timestamp("2026-01-04"), pd.Timestamp("2026-03-01")
WEEKS = pd.date_range("2026-01-05", periods=8, freq="7D")
DEMAND = [50, 50, 40, 60, 50, 50, 40, 60]
T = Thresholds(demand_window_days=14, variability_window_weeks=4)

Z_98 = 2.053748910631822  # NormalDist().inv_cdf(0.98), class A
SIGMA = 8.16496580927726  # stdev([50, 50, 40, 60]) = sqrt(200 / 3)


def _daily(
    material: str = MAT, demand: list[float] = DEMAND, stock_end: float = 100.0
) -> pd.DataFrame:
    dates = pd.date_range(START, AS_OF)
    consumption = []
    for date in dates:
        if date == START:
            consumption.append(np.nan)  # first observed day
        elif date.day_of_week >= 5:
            consumption.append(0.0)
        else:
            week = (date - WEEKS[0]).days // 7
            consumption.append(demand[week] / 5)
    stock = np.full(len(dates), stock_end)  # stock level is irrelevant to the demand KPIs
    return pd.DataFrame(
        {
            "material_id": material,
            "plant": PLANT,
            "date": dates,
            "stock_qty": stock,
            "stock_filled": stock,
            "receipt_qty": 0.0,
            "consumption_raw": consumption,
            "consumption": consumption,
            "is_observed": True,
            "is_imputed": False,
            "is_negative_outflow": False,
        }
    )


def _weekly(daily: pd.DataFrame) -> pd.DataFrame:
    """Weekly sums as the SQL step produces them (complete = 7 values)."""
    week_start = daily["date"] - pd.to_timedelta(daily["date"].dt.day_of_week, unit="D")
    grouped = daily.groupby(["material_id", "plant", week_start.rename("week_start")])
    out = grouped["consumption"].agg(demand="sum", days_with_value="count").reset_index()
    return out.assign(is_complete=out["days_with_value"] == 7)


def _materials(**changes) -> pd.DataFrame:
    row = {
        "material_id": MAT,
        "plant": PLANT,
        "description": "Kugellager 6204",
        "unit": "ST",
        "unit_price_eur": 2.0,
        "lead_time_days": 7,
        "min_stock": np.nan,
        "max_stock": np.nan,
    }
    return pd.DataFrame([row | changes])


def _metrics(daily=None, materials=None, as_of=AS_OF, thresholds=T) -> pd.Series:
    daily = _daily() if daily is None else daily
    tables = DailyTables(daily=daily, weekly=_weekly(daily), by_sloc=pd.DataFrame())
    frame = compute_metrics(
        tables, _materials() if materials is None else materials, as_of, thresholds
    )
    return frame.set_index(["material_id", "plant"]).loc[(MAT, PLANT)]


# --- Base case -----------------------------------------------------------------------------


def test_stock_and_history() -> None:
    m = _metrics()
    assert m["stock"] == 100.0
    assert m["stock_value"] == 200.0  # 100 * 2 EUR
    assert m["history_days"] == 57  # 04.01. to 01.03. inclusive: 28 + 28 + 1


def test_average_daily_demand_uses_the_demand_window() -> None:
    # Last 14 days are the weeks of 16.02. and 23.02.: (40 + 60) / 14
    assert _metrics()["avg_daily_demand"] == pytest.approx(100 / 14)


def test_weekly_sigma_uses_the_last_complete_weeks() -> None:
    m = _metrics()
    # Last 4 complete weeks: 50, 50, 40, 60 -> mean 50, sample variance 200 / 3
    assert m["mean_weekly"] == 50.0
    assert m["sigma_weekly"] == pytest.approx(SIGMA)
    assert m["cv_weekly"] == pytest.approx(SIGMA / 50)  # 0.1633
    assert m["complete_weeks"] == 4


def test_annual_value_and_classes() -> None:
    m = _metrics()
    assert m["annual_consumption_value"] == 800.0  # total demand 400 * 2 EUR
    assert m["abc"] == "A"  # the only material in its plant
    assert m["xyz"] == "X"  # CV 0.16 < 0.5


def test_days_since_consumption() -> None:
    m = _metrics()
    assert m["last_consumption_date"] == pd.Timestamp("2026-02-27")  # Friday
    assert m["days_since_consumption"] == 2  # 27.02. to 01.03.


def test_safety_stock_reorder_point_and_coverage() -> None:
    m = _metrics()
    safety = Z_98 * SIGMA * math.sqrt(7 / 7)  # 2.0537 * 8.1650 * 1 = 16.7688
    assert m["safety_stock_calc"] == pytest.approx(16.7688, abs=1e-4)
    assert m["safety_stock"] == pytest.approx(safety)  # no min_stock: calculated value
    assert m["reorder_point"] == pytest.approx(66.7688, abs=1e-4)  # 100/14 * 7 + 16.7688
    assert m["coverage_days"] == pytest.approx(14.0)  # 100 / (100/14)
    assert m["max_target"] == pytest.approx(428.5714, abs=1e-4)  # 100/14 * 60 days (A)
    assert m["excess_qty"] == 0.0
    assert m["shortfall_qty"] == 0.0
    assert np.isnan(m["min_stock_deviation_pct"])


def test_lead_time_scales_safety_stock_with_its_square_root() -> None:
    m = _metrics(materials=_materials(lead_time_days=14))
    # 2.0537 * 8.1650 * sqrt(14 / 7) = 23.7146
    assert m["safety_stock_calc"] == pytest.approx(23.7146, abs=1e-4)


def test_master_data_wins_and_the_deviation_is_reported() -> None:
    m = _metrics(materials=_materials(min_stock=30.0, max_stock=80.0))
    assert m["safety_stock"] == 30.0
    assert m["reorder_point"] == pytest.approx(80.0)  # 100/14 * 7 + 30 = 50 + 30
    assert m["max_target"] == 80.0
    assert m["excess_qty"] == 20.0  # 100 - 80
    assert m["excess_value"] == 40.0  # 20 * 2 EUR
    assert m["min_stock_deviation_pct"] == pytest.approx(78.9038, abs=1e-4)  # (30-16.77)/16.77


def test_shortfall_below_reorder_point() -> None:
    m = _metrics(daily=_daily(stock_end=40.0))
    assert m["shortfall_qty"] == pytest.approx(26.7688, abs=1e-4)  # 66.7688 - 40


# --- Edge cases ----------------------------------------------------------------------------


def test_zero_demand_with_stock_gives_unlimited_coverage() -> None:
    m = _metrics(daily=_daily(demand=[0] * 8))
    assert m["avg_daily_demand"] == 0.0
    assert m["coverage_days"] == np.inf
    assert np.isnan(m["cv_weekly"])  # mean weekly demand is zero
    assert m["xyz"] == "Z"
    assert m["abc"] == "C"  # zero consumption value
    assert m["days_since_consumption"] == 57  # never consumed: the whole history
    assert pd.isna(m["last_consumption_date"])


def test_zero_demand_and_zero_stock_gives_undefined_coverage() -> None:
    m = _metrics(daily=_daily(demand=[0] * 8, stock_end=0.0))
    assert np.isnan(m["coverage_days"])


def test_short_history_has_no_sigma() -> None:
    daily = _daily()
    short = daily[daily["date"] >= pd.Timestamp("2026-02-08")]  # Sunday, 22 days
    short = short.assign(
        consumption=short["consumption"].mask(short["date"] == short["date"].min())
    )
    m = _metrics(daily=short)
    assert m["history_days"] == 22
    assert m["complete_weeks"] == 3  # weeks of 09.02., 16.02., 23.02.
    assert np.isnan(m["sigma_weekly"])  # fewer than 4 complete weeks
    assert np.isnan(m["safety_stock_calc"])


def test_material_without_data_before_as_of_is_left_out() -> None:
    daily = pd.concat(
        [
            _daily(),
            _daily(material="00000002").assign(date=lambda f: f["date"] + pd.Timedelta(days=60)),
        ]
    )
    materials = pd.concat([_materials(), _materials(material_id="00000002")])
    tables = DailyTables(daily=daily, weekly=_weekly(daily), by_sloc=pd.DataFrame())
    frame = compute_metrics(tables, materials, AS_OF, T)
    assert frame["material_id"].tolist() == [MAT]


# --- Nothing after as_of -------------------------------------------------------------------


def test_data_after_as_of_has_no_influence() -> None:
    base = _daily()
    later = base.assign(
        date=base["date"] + pd.Timedelta(days=57),
        stock_filled=9999.0,
        consumption=500.0,
    )
    extended = pd.concat([base, later], ignore_index=True)
    with_future = _metrics(daily=extended)
    without = _metrics(daily=base)
    pd.testing.assert_series_equal(with_future, without)


def test_open_gap_at_as_of_does_not_use_the_next_snapshot() -> None:
    # 27.02. to 01.03. are missing; their imputed consumption (999) would come from a
    # snapshot after as_of, so it must not count.
    daily = _daily()
    gap = daily["date"] >= pd.Timestamp("2026-02-27")
    daily = daily.assign(
        is_observed=~gap,
        stock_qty=daily["stock_qty"].mask(gap),
        consumption=daily["consumption"].mask(gap, 999.0),
    )
    m = _metrics(daily=daily)
    # Window 16.02. to 01.03. without the 3 gap days: week of 16.02. (40) plus
    # 23.02. to 26.02. (4 * 12 = 48) over 11 days = 88 / 11 = 8.0
    assert m["avg_daily_demand"] == pytest.approx(8.0)
    # The week of 23.02. ends after the last observed day 26.02.: the last 4 usable
    # weeks are 26.01. to 16.02.: 60, 50, 50, 40 -> same mean and sigma as before
    assert m["mean_weekly"] == 50.0
    assert m["sigma_weekly"] == pytest.approx(SIGMA)
    assert m["last_consumption_date"] == pd.Timestamp("2026-02-26")


def test_inputs_are_not_mutated() -> None:
    daily, materials = _daily(), _materials()
    before_daily, before_materials = daily.copy(), materials.copy()
    _metrics(daily=daily, materials=materials)
    pd.testing.assert_frame_equal(daily, before_daily)
    pd.testing.assert_frame_equal(materials, before_materials)
