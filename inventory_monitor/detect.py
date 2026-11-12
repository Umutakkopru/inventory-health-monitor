"""Status assignment, priority and anomaly flags (Methodology, "Status rules").

Every material-plant gets exactly one status: the first rule in STATUS_RULES that matches.
There is deliberately no rule "coverage below lead time is critical": under a reorder-point
policy every healthy material spends part of each cycle below one lead time of stock while
its replenishment is on the way.

The data has no open purchase orders, so SHORTAGE_WARNING means "below the reorder point:
check that a replenishment order is open", not "act now".

Anomaly flags are informational and never change the status.
"""

import numpy as np
import pandas as pd

from inventory_monitor.config import (
    DAYS_PER_WEEK,
    MIN_COMPLETE_WEEKS,
    MIN_RECEIPT_HISTORY,
    RECEIPT_ANOMALY_WINDOW_DAYS,
    Thresholds,
)
from inventory_monitor.models import Status

KEY = ["material_id", "plant"]
SHORTAGES = (Status.SHORTAGE_CRITICAL, Status.SHORTAGE_WARNING)
EXCESS = (Status.OVERSTOCK, Status.DEAD_STOCK)
# Within the shortage statuses, class A comes first, then B, then C (lower tier first).
ABC_TIER = {"A": 0, "B": 1, "C": 2}


def assign_status(metrics: pd.DataFrame, thresholds: Thresholds) -> pd.DataFrame:
    """Add `status`, `value_at_risk` and `priority_score` to the metrics frame.

    For DEAD_STOCK the whole stock counts as excess. `value_at_risk` is the shortfall
    value for shortages and the excess value for overstock and dead stock. Sorting by
    `priority_score` descending within a status puts the most urgent material first.
    """
    m = metrics
    no_recent_use = m["days_since_consumption"] >= thresholds.dead_stock_days
    rules = [
        (Status.INSUFFICIENT_DATA, m["history_days"] < thresholds.min_history_days),
        (Status.INACTIVE, (m["stock"] == 0) & no_recent_use),
        (Status.SHORTAGE_CRITICAL, (m["stock"] <= 0) | (m["stock"] < m["safety_stock"])),
        (Status.SHORTAGE_WARNING, m["stock"] < m["reorder_point"]),
        (Status.DEAD_STOCK, (m["stock"] > 0) & no_recent_use),
        (Status.OVERSTOCK, m["stock"] > m["max_target"]),
    ]
    status = pd.Series(
        np.select([cond for _, cond in rules], [s.value for s, _ in rules], Status.OK.value),
        index=m.index,
    )
    excess_qty = m["excess_qty"].mask(status == Status.DEAD_STOCK, m["stock"])
    excess_value = excess_qty * m["unit_price_eur"]
    shortfall_value = m["shortfall_qty"] * m["unit_price_eur"]
    value_at_risk = (
        shortfall_value.where(status.isin(SHORTAGES), 0.0)
        + excess_value.where(status.isin(EXCESS), 0.0)
    ).fillna(0.0)
    return m.assign(
        status=status,
        excess_qty=excess_qty,
        excess_value=excess_value,
        value_at_risk=value_at_risk,
        priority_score=_priority(status, m["abc"], value_at_risk),
    )


def _priority(status: pd.Series, abc: pd.Series, value: pd.Series) -> pd.Series:
    """Value at risk, lifted by class for shortages so that A always ranks before B and C.

    The lift is one more than the largest value at risk, so it separates the classes
    whatever the values are, and the value still orders materials within a class.
    """
    step = value.max() + 1 if len(value) else 1.0
    lift = (len(ABC_TIER) - 1 - abc.map(ABC_TIER)) * step
    return value + lift.where(status.isin(SHORTAGES), 0.0)


def flag_anomalies(
    metrics: pd.DataFrame,
    weekly: pd.DataFrame,
    receipts: pd.DataFrame,
    as_of: pd.Timestamp,
    thresholds: Thresholds,
) -> pd.DataFrame:
    """Demand and receipt anomaly flags per material-plant, by the IQR rule.

    A value is unusual when it lies above Q3 + k * IQR of the history before it, with
    k = `anomaly_iqr_factor`. `metrics` supplies the material-plants and their `cutoff`
    (last observed date on or before `as_of`).
    """
    flags = metrics[[*KEY, "cutoff"]]
    demand = _demand_anomaly(weekly, flags, thresholds)
    receipt = _receipt_anomaly(receipts, flags, pd.Timestamp(as_of), thresholds)
    out = flags[KEY].merge(demand, on=KEY, how="left").merge(receipt, on=KEY, how="left")
    return out.fillna({"demand_anomaly": False, "receipt_anomaly": False}).astype(
        {"demand_anomaly": bool, "receipt_anomaly": bool}
    )


def _upper_fence(values: pd.Series, keys: list[pd.Series], factor: float) -> pd.Series:
    """Q3 + factor * IQR per group."""
    grouped = values.groupby(keys)
    q1, q3 = grouped.quantile(0.25), grouped.quantile(0.75)
    return q3 + factor * (q3 - q1)


def _demand_anomaly(
    weekly: pd.DataFrame, flags: pd.DataFrame, thresholds: Thresholds
) -> pd.DataFrame:
    """Last complete week's demand above the fence of the complete weeks before it."""
    weeks = weekly.merge(flags, on=KEY)
    week_end = weeks["week_start"] + pd.Timedelta(days=DAYS_PER_WEEK - 1)
    weeks = weeks[weeks["is_complete"] & (week_end <= weeks["cutoff"])].sort_values("week_start")
    is_last = ~weeks.duplicated(KEY, keep="last")
    history, last = weeks[~is_last], weeks[is_last].set_index(KEY)["demand"]
    counts = history.groupby(KEY).size()
    fence = _upper_fence(
        history["demand"], [history["material_id"], history["plant"]], thresholds.anomaly_iqr_factor
    )
    enough = counts.reindex(last.index) >= MIN_COMPLETE_WEEKS
    flag = (last > fence.reindex(last.index)) & enough
    return flag.rename("demand_anomaly").reset_index()


def _receipt_anomaly(
    receipts: pd.DataFrame, flags: pd.DataFrame, as_of: pd.Timestamp, thresholds: Thresholds
) -> pd.DataFrame:
    """A receipt in the last 30 days above the fence of the material's earlier receipts."""
    window_start = as_of - pd.Timedelta(days=RECEIPT_ANOMALY_WINDOW_DAYS)
    known = receipts.merge(flags[KEY], on=KEY)
    known = known[known["date"] <= as_of]
    recent = known["date"] > window_start
    history = known[~recent]
    keys = [history["material_id"], history["plant"]]
    fence = _upper_fence(history["receipt_qty"], keys, thresholds.anomaly_iqr_factor)
    fence = fence[history.groupby(keys).size() >= MIN_RECEIPT_HISTORY]
    largest = known[recent].groupby(KEY)["receipt_qty"].max()
    flag = largest > fence.reindex(largest.index)
    return flag.rename("receipt_anomaly").reset_index()
