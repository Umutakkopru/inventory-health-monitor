"""Tests for the stock projection (CLAUDE.md section 6.6). Horizon: 60 days, alpha 0.3."""

import math

import numpy as np
import pandas as pd
import pytest

from inventory_monitor.config import DEFAULT_THRESHOLDS
from inventory_monitor.forecast import demand_rates, project, projection_dates

AS_OF = pd.Timestamp("2026-10-31")
KEY = {"material_id": "00000001", "plant": "1010"}


def _weekly(demands: list[float], complete: bool = True) -> pd.DataFrame:
    starts = pd.date_range(end="2026-10-19", periods=len(demands), freq="7D")
    return pd.DataFrame(KEY | {"week_start": starts, "demand": demands, "is_complete": complete})


def _rate(weekly: pd.DataFrame) -> float:
    metrics = pd.DataFrame([KEY | {"cutoff": AS_OF}])
    rates = demand_rates(weekly, metrics, DEFAULT_THRESHOLDS)
    return rates["projection_daily_demand"].iloc[0] if len(rates) else math.nan


def _dates(stock: float, safety: float, rate: float) -> pd.Series:
    metrics = pd.DataFrame(
        [KEY | {"stock": stock, "safety_stock": safety, "projection_daily_demand": rate}]
    )
    return projection_dates(metrics, AS_OF, DEFAULT_THRESHOLDS).iloc[0]


# --- Demand rate ---------------------------------------------------------------------------


def test_constant_weeks_give_a_constant_rate() -> None:
    assert _rate(_weekly([70.0, 70.0, 70.0])) == pytest.approx(10.0)  # 70 / 7


def test_rate_weights_recent_weeks_more() -> None:
    # EWMA, alpha 0.3: 0.7 * 70 + 0.3 * 140 = 91 per week, 13 per day
    assert _rate(_weekly([70.0, 140.0])) == pytest.approx(13.0)


def test_incomplete_weeks_are_ignored() -> None:
    assert math.isnan(_rate(_weekly([70.0], complete=False)))


# --- Crossing dates ------------------------------------------------------------------------


def test_dates_on_a_constructed_series() -> None:
    # Stock 100, 10 per day, safety stock 30.
    # Below safety: 100 - 10t < 30 <=> t > 7, first day t = 8 -> 08.11.2026
    # Stock-out:   100 - 10t <= 0 <=> t >= 10                -> 10.11.2026
    dates = _dates(stock=100.0, safety=30.0, rate=10.0)
    assert dates["projected_below_safety_date"] == pd.Timestamp("2026-11-08")
    assert dates["projected_stockout_date"] == pd.Timestamp("2026-11-10")


def test_no_crossing_inside_the_horizon_gives_nat() -> None:
    # 1000 / 10 = 100 days to stock-out, beyond the 60-day horizon; safety after 98 days.
    dates = _dates(stock=1000.0, safety=30.0, rate=10.0)
    assert pd.isna(dates["projected_below_safety_date"])
    assert pd.isna(dates["projected_stockout_date"])


def test_zero_or_unknown_rate_gives_nat() -> None:
    for rate in (0.0, np.nan):
        dates = _dates(stock=100.0, safety=30.0, rate=rate)
        assert pd.isna(dates["projected_stockout_date"])


def test_already_below_safety_or_empty_is_today() -> None:
    assert _dates(20.0, 30.0, 10.0)["projected_below_safety_date"] == AS_OF
    assert _dates(0.0, 30.0, 10.0)["projected_stockout_date"] == AS_OF


def test_crossing_exactly_on_the_horizon_counts() -> None:
    # 600 / 10 = 60 days: stock-out on the last day of the horizon
    assert _dates(600.0, 0.0, 10.0)["projected_stockout_date"] == AS_OF + pd.Timedelta(days=60)


# --- Projection for the chart --------------------------------------------------------------


def test_project_draws_stock_down_with_a_band() -> None:
    daily = pd.DataFrame({"date": pd.date_range(end=AS_OF, periods=3)})
    row = pd.Series({"stock": 100.0, "projection_daily_demand": 10.0, "sigma_weekly": 14.0})
    out = project(daily, row, DEFAULT_THRESHOLDS).set_index("date")
    assert len(out) == 61  # day 0 to day 60
    day7 = out.loc[AS_OF + pd.Timedelta(days=7)]
    assert day7["projected_stock"] == 30.0  # 100 - 7 * 10
    assert day7["upper"] == pytest.approx(44.0)  # 30 + 14 * sqrt(7 / 7)
    assert day7["lower"] == pytest.approx(16.0)  # 30 - 14
    assert out["projected_stock"].min() == 0.0  # clipped at zero after day 10
    assert out["lower"].min() >= 0.0


def test_project_without_rate_or_sigma_is_flat() -> None:
    daily = pd.DataFrame({"date": [AS_OF]})
    row = pd.Series({"stock": 100.0, "projection_daily_demand": np.nan, "sigma_weekly": np.nan})
    out = project(daily, row, DEFAULT_THRESHOLDS)
    assert set(out["projected_stock"]) == {100.0}
    assert (out["upper"] == out["lower"]).all()


def test_band_never_exceeds_todays_stock() -> None:
    # Stock 0: the projection stays at 0 and so does the whole band.
    daily = pd.DataFrame({"date": [AS_OF]})
    row = pd.Series({"stock": 0.0, "projection_daily_demand": 10.0, "sigma_weekly": 14.0})
    out = project(daily, row, DEFAULT_THRESHOLDS)
    assert out["upper"].max() == 0.0
    # Stock 100: on day 0 the band is exactly today's stock (100 + 14 * 0 = 100).
    row = pd.Series({"stock": 100.0, "projection_daily_demand": 1.0, "sigma_weekly": 14.0})
    assert project(daily, row, DEFAULT_THRESHOLDS)["upper"].max() == 100.0
