"""Per-material KPIs as of a date (Methodology, "Key figures").

Only data up to `as_of` is used. Derived consumption on a gap day is spread from the next
observed snapshot, so a gap that is still open on `as_of` would pull in a snapshot from
after `as_of`. Such days, and weeks that contain them, are therefore left out: the cutoff
per material is its last observed date on or before `as_of`.

The order of the steps matters: the ABC class needs the annual consumption value, and the
safety stock needs the ABC class (through the service level).
"""

from statistics import NormalDist

import numpy as np
import pandas as pd

from inventory_monitor.classify import assign_abc, assign_xyz
from inventory_monitor.config import (
    ANNUAL_WINDOW_DAYS,
    DAYS_PER_WEEK,
    MIN_COMPLETE_WEEKS,
    Thresholds,
)
from inventory_monitor.models import DailyTables

KEY = ["material_id", "plant"]
MASTER_COLUMNS = [
    *KEY,
    "description",
    "unit",
    "unit_price_eur",
    "lead_time_days",
    "min_stock",
    "max_stock",
]


def compute_metrics(
    tables: DailyTables, materials: pd.DataFrame, as_of: pd.Timestamp, thresholds: Thresholds
) -> pd.DataFrame:
    """One row per material-plant with the KPIs from Methodology section "Key figures".

    Material-plants without any snapshot on or before `as_of` (not yet in the data) are
    left out. Statuses are assigned afterwards by `detect.assign_status`.
    """
    as_of = pd.Timestamp(as_of).normalize()
    daily = _usable_daily(tables.daily, as_of)
    base = _stock_and_history(daily, as_of).merge(materials[MASTER_COLUMNS], on=KEY)
    frame = (
        base.merge(_demand(daily, as_of, thresholds), on=KEY, how="left")
        .merge(_weekly(tables.weekly, daily, thresholds), on=KEY, how="left")
        .merge(_last_consumption(daily), on=KEY, how="left")
    )
    frame = frame.assign(
        stock_value=frame["stock"] * frame["unit_price_eur"],
        annual_consumption_value=frame["annual_consumption"] * frame["unit_price_eur"],
        cv_weekly=_ratio(frame["sigma_weekly"], frame["mean_weekly"]),
        days_since_consumption=(as_of - frame["last_consumption_date"])
        .dt.days.fillna(frame["history_days"])
        .astype(int),
    )
    frame = assign_xyz(assign_abc(frame, thresholds), thresholds)
    return _policy(frame, thresholds).sort_values(KEY, ignore_index=True)


def _usable_daily(daily: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """Rows up to `as_of`; consumption after the last observed date is set to NaN.

    Also adds `cutoff`, the last observed date on or before `as_of` per material-plant.
    """
    past = daily[daily["date"] <= as_of]
    observed_dates = past["date"].where(past["is_observed"])
    cutoff = observed_dates.groupby([past["material_id"], past["plant"]]).transform("max")
    open_gap = past["date"] > cutoff
    return past.assign(
        cutoff=cutoff,
        consumption=past["consumption"].mask(open_gap),
    )


def _stock_and_history(daily: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """Stock on `as_of` (last observed stock carried forward) and the length of history."""
    grouped = daily.sort_values("date").groupby(KEY)
    first_observed = (
        daily["date"]
        .where(daily["is_observed"])
        .groupby([daily["material_id"], daily["plant"]])
        .min()
    )
    out = grouped.agg(stock=("stock_filled", "last"), cutoff=("cutoff", "first"))
    out = out.assign(
        first_date=first_observed,
        history_days=(as_of - first_observed).dt.days + 1,
    )
    return out.reset_index()


def _demand(daily: pd.DataFrame, as_of: pd.Timestamp, thresholds: Thresholds) -> pd.DataFrame:
    """Average daily demand over the demand window and consumption over the last year."""
    window_start = as_of - pd.Timedelta(days=thresholds.demand_window_days)
    year_start = as_of - pd.Timedelta(days=ANNUAL_WINDOW_DAYS)
    recent = daily["consumption"].where(daily["date"] > window_start)
    year = daily["consumption"].where(daily["date"] > year_start)
    keys = [daily["material_id"], daily["plant"]]
    return pd.DataFrame(
        {
            "avg_daily_demand": recent.groupby(keys).mean(),
            "annual_consumption": year.groupby(keys).sum(min_count=0),
        }
    ).reset_index()


def _weekly(weekly: pd.DataFrame, daily: pd.DataFrame, thresholds: Thresholds) -> pd.DataFrame:
    """Mean and sample standard deviation of the last complete weeks before the cutoff.

    Weekly rather than daily figures on purpose: weekends have no demand, so a daily
    standard deviation would mostly measure the weekly rhythm. With fewer than
    MIN_COMPLETE_WEEKS weeks both are NaN.
    """
    cutoffs = daily.groupby(KEY)["cutoff"].first().reset_index()
    weeks = weekly.merge(cutoffs, on=KEY)
    week_end = weeks["week_start"] + pd.Timedelta(days=DAYS_PER_WEEK - 1)
    usable = weeks[weeks["is_complete"] & (week_end <= weeks["cutoff"])]
    last = usable.sort_values("week_start").groupby(KEY).tail(thresholds.variability_window_weeks)
    stats = last.groupby(KEY)["demand"].agg(
        mean_weekly="mean", sigma_weekly="std", complete_weeks="size"
    )
    enough = stats["complete_weeks"] >= MIN_COMPLETE_WEEKS
    stats = stats.assign(
        mean_weekly=stats["mean_weekly"].where(enough),
        sigma_weekly=stats["sigma_weekly"].where(enough),
    )
    return stats.reset_index()


def _last_consumption(daily: pd.DataFrame) -> pd.DataFrame:
    consumed = daily[daily["consumption"] > 0]
    return consumed.groupby(KEY)["date"].max().rename("last_consumption_date").reset_index()


def _ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """numerator / denominator, NaN where the denominator is zero or missing."""
    return numerator / denominator.where(denominator != 0)


def _policy(frame: pd.DataFrame, thresholds: Thresholds) -> pd.DataFrame:
    """Safety stock, reorder point, coverage, overstock limit and excess/shortfall."""
    z = frame["abc"].map(lambda c: NormalDist().inv_cdf(thresholds.service_level(c)))
    overstock_days = frame["abc"].map(thresholds.overstock_days)
    lead = frame["lead_time_days"]
    demand = frame["avg_daily_demand"]
    stock = frame["stock"]

    safety_calc = z * frame["sigma_weekly"] * np.sqrt(lead / DAYS_PER_WEEK)
    # Master data wins over the calculated value; both are kept for comparison.
    safety = frame["min_stock"].fillna(safety_calc)
    reorder_point = demand * lead + safety
    max_target = frame["max_stock"].fillna(demand * overstock_days)
    excess = (stock - max_target).clip(lower=0)
    # Zero demand: unlimited coverage when there is stock, undefined when there is none.
    coverage = _ratio(stock, demand).mask((demand == 0) & (stock > 0), np.inf)

    return frame.assign(
        z=z,
        safety_stock_calc=safety_calc,
        safety_stock=safety,
        min_stock_deviation_pct=_ratio(frame["min_stock"] - safety_calc, safety_calc) * 100,
        reorder_point=reorder_point,
        coverage_days=coverage,
        max_target=max_target,
        excess_qty=excess,
        excess_value=excess * frame["unit_price_eur"],
        shortfall_qty=(reorder_point - stock).clip(lower=0),
    )
