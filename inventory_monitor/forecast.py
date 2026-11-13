"""Stock projection "if no further receipt arrives" (Methodology, "Projection").

This is not a demand forecast. The stock is drawn down linearly at the recent demand rate
(an exponentially weighted mean of weekly demand), with a band of plus and minus one
weekly standard deviation scaled by the square root of the elapsed weeks.
"""

import numpy as np
import pandas as pd

from inventory_monitor.config import DAYS_PER_WEEK, Thresholds

KEY = ["material_id", "plant"]


def demand_rates(
    weekly: pd.DataFrame, metrics: pd.DataFrame, thresholds: Thresholds
) -> pd.DataFrame:
    """Daily demand rate per material-plant: EWMA of complete weekly demand, divided by 7.

    Only complete weeks that end on or before the material's `cutoff` count, so nothing
    after `as_of` enters. Recent weeks weigh more: with alpha 0.3 the last week has a
    weight of 0.3, the one before 0.21, and so on.
    """
    weeks = weekly.merge(metrics[[*KEY, "cutoff"]], on=KEY)
    week_end = weeks["week_start"] + pd.Timedelta(days=DAYS_PER_WEEK - 1)
    weeks = weeks[weeks["is_complete"] & (week_end <= weeks["cutoff"])].sort_values("week_start")
    ewma = weeks.groupby(KEY)["demand"].transform(
        lambda s: s.ewm(alpha=thresholds.ewma_alpha, adjust=False).mean()
    )
    last = weeks.assign(ewma=ewma).groupby(KEY)["ewma"].last() / DAYS_PER_WEEK
    return last.rename("projection_daily_demand").reset_index()


def projection_dates(
    metrics: pd.DataFrame, as_of: pd.Timestamp, thresholds: Thresholds
) -> pd.DataFrame:
    """First projected day below safety stock and first day with zero stock.

    `metrics` needs `stock`, `safety_stock` and `projection_daily_demand`. A date is NaT
    when it falls after the projection horizon or the demand rate is zero or unknown; it is
    `as_of` itself when the condition already holds today.
    """
    rate = metrics["projection_daily_demand"].where(metrics["projection_daily_demand"] > 0)
    stock = metrics["stock"]
    # stock - rate * t < safety  <=>  t > (stock - safety) / rate
    days_below = np.floor((stock - metrics["safety_stock"]) / rate) + 1
    days_below = days_below.where(stock >= metrics["safety_stock"], 0)
    # stock - rate * t <= 0  <=>  t >= stock / rate
    days_out = np.ceil(stock / rate).where(stock > 0, 0)
    return metrics[KEY].assign(
        projected_below_safety_date=_to_date(days_below, as_of, thresholds),
        projected_stockout_date=_to_date(days_out, as_of, thresholds),
    )


def _to_date(days: pd.Series, as_of: pd.Timestamp, thresholds: Thresholds) -> pd.Series:
    inside = days.where(days <= thresholds.projection_horizon_days)
    return pd.Timestamp(as_of) + pd.to_timedelta(inside, unit="D")


def project(
    daily_one_material: pd.DataFrame, metrics_row: pd.Series, thresholds: Thresholds
) -> pd.DataFrame:
    """Projected stock per day for one material, from its last date over the horizon.

    `daily_one_material` must already be limited to dates up to `as_of`; its last date is
    day 0. The projection and its band stay between zero and today's stock.
    """
    start = daily_one_material["date"].max()
    days = np.arange(thresholds.projection_horizon_days + 1)
    rate = metrics_row["projection_daily_demand"]
    rate = 0.0 if pd.isna(rate) else rate
    projected = np.clip(metrics_row["stock"] - rate * days, 0, None)
    spread = metrics_row["sigma_weekly"] * np.sqrt(days / DAYS_PER_WEEK)
    spread = np.zeros(len(days)) if pd.isna(metrics_row["sigma_weekly"]) else spread
    return pd.DataFrame(
        {
            "date": start + pd.to_timedelta(days, unit="D"),
            "projected_stock": projected,
            "lower": np.clip(projected - spread, 0, None),
            # Without receipts the stock can only fall, so the band never exceeds today's stock.
            "upper": np.minimum(projected + spread, metrics_row["stock"]),
        }
    )
